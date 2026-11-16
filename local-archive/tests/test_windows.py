import numpy as np
import pandas as pd
import pytest
import torch
from ptop._vendor.qlib.sampler import TSDataSampler
from torch.utils.data import DataLoader

from ptop.data import CanonicalData, concat_partitions, normalize_bars
from ptop.schema import BOOK12_FIELDS, FEATURES, ContractError
from ptop.windows import DecisionBatchSampler, WindowDataset, build_windows, collate_windows, fit_row_union


def fixture_data():
    grid = pd.DatetimeIndex(["2024-01-02 09:31", "2024-01-02 09:32", "2024-01-02 11:30",
                             "2024-01-02 13:01", "2024-01-03 09:31"])
    raw = pd.DataFrame({name: [10., 20., 30., 40.] for name in FEATURES})
    raw["date"] = grid[[0, 2, 3, 4]]
    raw["instrument_id"] = 1
    raw["available_at"] = raw["date"]
    raw.loc[0, "volume"] = 0
    samples = pd.DataFrame({"sample_id": [40, 10, 20, 30], "decision_id": [2, 1, 2, 3],
                            "decision_time": grid[[3, 0, 3, 4]], "instrument_id": [2, 1, 1, 1]})
    return raw, samples, grid


def canonical(raw):
    return normalize_bars(raw, source="cloud", instrument_map={1: "SH1", 2: "SZ2"})


def test_lazy_sampler_retains_grid_masks_order_and_day_boundary():
    raw, expected, grid = fixture_data()
    data = canonical(raw)
    original = data.values.copy(deep=True)
    windows = build_windows(data, expected, grid, length=4)
    assert all(isinstance(sampler, TSDataSampler) for sampler in windows._samplers.values())
    batch = windows.get_batch(range(len(windows)))
    assert batch.metadata.sample_id.tolist() == [40, 10, 20, 30]
    assert batch.predictable.tolist() == [False, True, True, True]
    assert batch.step_valid[0].tolist() == [True, True, True, True]
    assert not batch.observed[0].any()
    assert batch.step_valid[1].tolist() == [False, False, False, True]
    assert batch.step_valid[3].tolist() == [False, False, False, True]
    assert batch.x[3, -1, 0] == 40
    assert batch.step_valid[2].tolist() == [True, True, True, True]
    assert not batch.observed[2, 1].any()
    assert batch.x[2, :, 0].tolist() == [10, 0, 20, 30]
    assert batch.observed[1, -1, FEATURES.index("volume")]
    assert not (batch.observed & ~batch.step_valid[..., None]).any()
    assert batch.bar_times[2, 2] == np.datetime64("2024-01-02T11:30")
    assert batch.bar_times[2, 3] == np.datetime64("2024-01-02T13:01")
    assert np.isfinite(batch.x).all()
    pd.testing.assert_frame_equal(data.values, original)


def test_future_and_not_yet_available_records_do_not_leak():
    raw, expected, grid = fixture_data()
    first = expected.iloc[[1]].copy()
    before = WindowDataset(canonical(raw), first, grid, length=4)[0]
    raw.loc[1:, list(FEATURES)] = 9000
    after = WindowDataset(canonical(raw), first, grid, length=4)[0]
    np.testing.assert_array_equal(before.x, after.x)
    raw.loc[0, "available_at"] = pd.Timestamp("2024-01-02 09:32")
    delayed = WindowDataset(canonical(raw), first, grid, length=4)[0]
    assert delayed.step_valid[0, -1]
    assert not delayed.observed.any()
    assert not delayed.predictable[0]


def test_fit_union_deduplicates_visible_rows_without_missing_grid_keys():
    raw, expected, grid = fixture_data()
    windows = WindowDataset(canonical(raw), expected, grid, length=4)
    index = fit_row_union(windows, fit_start="2024-01-02", fit_end="2024-01-02")
    assert index.tolist() == [(grid[0], 1), (grid[2], 1), (grid[3], 1)]
    assert index.is_unique
    with pytest.raises(ContractError, match="完整日历日"):
        fit_row_union(windows, fit_start="2024-01-02", fit_end="2024-01-02 13:01")
    raw.loc[2, "available_at"] += pd.Timedelta(minutes=1)
    delayed = WindowDataset(canonical(raw), expected, grid, length=4)
    visible = fit_row_union(delayed, fit_start="2024-01-02", fit_end="2024-01-02")
    assert (grid[3], 1) not in visible


def test_partition_invariance_and_subset_predictable():
    raw, expected, grid = fixture_data()
    joined = concat_partitions([canonical(raw.iloc[:2]), canonical(raw.iloc[2:])])
    original = WindowDataset(canonical(raw), expected, grid, length=4).get_batch([2, 1])
    split = WindowDataset(joined, expected, grid, length=4).get_batch([2, 1])
    np.testing.assert_array_equal(original.x, split.x)
    np.testing.assert_array_equal(original.observed, split.observed)
    raw.loc[:, list(BOOK12_FIELDS)] = np.nan
    batch = WindowDataset(canonical(raw), expected, grid, fields=BOOK12_FIELDS).get_batch([1, 2])
    assert not batch.predictable.any()
    assert batch.observed.any()


def test_required_availability_and_grid_validation():
    raw, expected, grid = fixture_data()
    data = canonical(raw.drop(columns="available_at"))
    with pytest.raises(ContractError, match="available_at"):
        WindowDataset(data, expected, grid)
    assert WindowDataset(data, expected, grid, bar_end_is_available=True)[1].predictable[0]
    with pytest.raises(ContractError, match="端点"):
        WindowDataset(canonical(raw), expected, grid[:-1])
    with pytest.raises(ContractError, match="唯一"):
        WindowDataset(canonical(raw), expected, grid.append(grid[-1:]))
    invalid = expected.copy()
    invalid.loc[2, "decision_id"] = 99
    with pytest.raises(ContractError, match="共用"):
        WindowDataset(canonical(raw), invalid, grid)


def test_overflow_fails_and_empty_batch_is_supported():
    raw, expected, grid = fixture_data()
    data = canonical(raw)
    data.values.iloc[0, 0] = 1e40
    windows = WindowDataset(data, expected, grid)
    with pytest.raises(ContractError, match="float32"):
        windows.get_batch([1])
    assert windows.get_batch([]).x.shape == (0, 120, 25)


@pytest.mark.parametrize("value", ["false", 1, None, np.bool_(True)])
def test_window_availability_requires_python_bool_even_with_available_at(value):
    raw, expected, grid = fixture_data()
    with pytest.raises(ContractError, match="bar_end_is_available 必须为 bool"):
        WindowDataset(canonical(raw), expected, grid, bar_end_is_available=value)


def assert_same_batch(actual, expected):
    for name in ("x", "observed", "step_valid", "predictable", "bar_times", "row_positions"):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name))
    pd.testing.assert_frame_equal(actual.metadata, expected.metadata)


def test_collate_preserves_values_masks_and_metadata_order():
    raw, expected, grid = fixture_data()
    dataset = WindowDataset(canonical(raw), expected, grid, length=4)
    actual = collate_windows([dataset[3], dataset.get_batch([1, 2]), dataset[0]])
    assert_same_batch(actual, dataset.get_batch([3, 1, 2, 0]))
    with pytest.raises(ContractError, match="非空"):
        collate_windows([])
    shorter = WindowDataset(canonical(raw), expected, grid, length=2)
    with pytest.raises(ContractError, match="相同长度"):
        collate_windows([dataset[0], shorter[1]])


@pytest.mark.parametrize("num_workers", [0, 1])
def test_real_dataloader_complete_decisions_and_spawn(num_workers):
    raw, expected, grid = fixture_data()
    dataset = WindowDataset(canonical(raw), expected, grid, length=4)
    sampler = DecisionBatchSampler(dataset)
    options = {} if num_workers == 0 else {"multiprocessing_context": "spawn", "timeout": 30}
    # pytest 在受保护的入口调用测试函数；worker 只导入顶层 dataset 与 collate 定义。
    loader = DataLoader(dataset, batch_sampler=sampler, collate_fn=collate_windows,
                        num_workers=num_workers, generator=torch.Generator().manual_seed(101), **options)
    batches = list(loader)
    assert len(loader) == len(sampler) == len(batches) == 3
    assert [batch.metadata.sample_id.tolist() for batch in batches] == [[40, 20], [10], [30]]
    assert [len(batch.metadata) for batch in batches] == [2, 1, 1]
    for batch, positions in zip(batches, [[0, 2], [1], [3]]):
        assert batch.metadata.decision_id.nunique() == 1
        assert_same_batch(batch, dataset.get_batch(positions))
    assert sorted(pd.concat([batch.metadata for batch in batches]).sample_id.tolist()) == sorted(expected.sample_id.tolist())


def test_decision_shuffle_is_reproducible_complete_and_keeps_global_rng():
    raw, expected, grid = fixture_data()
    dataset = WindowDataset(canonical(raw), expected, grid, length=4)
    global_state = torch.get_rng_state().clone()
    first = DecisionBatchSampler(dataset, shuffle=True, seed=17)
    second = DecisionBatchSampler(dataset, shuffle=True, generator=torch.Generator().manual_seed(17))
    for _ in range(2):
        actual, repeated = list(first), list(second)
        assert actual == repeated
        assert sorted(index for group in actual for index in group) == list(range(len(dataset)))
        assert sorted(actual) == [[0, 2], [1], [3]]
    assert torch.equal(global_state, torch.get_rng_state())


@pytest.mark.parametrize("kwargs", [{"shuffle": True}, {"shuffle": "false"}, {"seed": True},
                                    {"shuffle": True, "seed": 17, "generator": torch.Generator()},
                                    {"shuffle": True, "generator": 17}])
def test_decision_sampler_rejects_ambiguous_randomness(kwargs):
    raw, expected, grid = fixture_data()
    dataset = WindowDataset(canonical(raw), expected, grid, length=4)
    with pytest.raises(ContractError):
        DecisionBatchSampler(dataset, **kwargs)
