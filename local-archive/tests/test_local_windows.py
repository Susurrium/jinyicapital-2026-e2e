import numpy as np
import pandas as pd
import pytest
from ptop._vendor.qlib.sampler import TSDataSampler

from ptop.data import normalize_bars, normalize_local_bars
from ptop.output import audit_output
from ptop.schema import FEATURES, SCALE_FIELDS, ContractError
from ptop.windows import DecisionBatchSampler, LocalAuditWindowDataset, WindowDataset, collate_windows, fit_row_union


def audit_fixture():
    grid = pd.DatetimeIndex(["2024-01-02 09:31", "2024-01-02 09:32", "2024-01-02 11:30",
                             "2024-01-02 13:01", "2024-01-03 09:31"])
    raw = pd.DataFrame({field: [10, 20, 30, 40] for field in FEATURES})
    raw.loc[:, list(SCALE_FIELDS)] *= 100
    raw["date"] = grid[[0, 2, 3, 4]]
    raw["instrument_id"] = 17
    raw.loc[0, "volume"] = 0
    raw.loc[2, "bid_price1"] = 0
    endpoints = pd.DataFrame({"sample_id": [4, 1, 2, 3], "decision_id": [2, 1, 2, 3],
                              "decision_time": grid[[3, 0, 3, 4]], "instrument_id": [23, 17, 17, 17]})
    return raw, endpoints, grid


def local_dataset(raw, endpoints, grid, **kwargs):
    return LocalAuditWindowDataset(normalize_local_bars(raw), endpoints, grid, length=4,
                                   bar_end_is_available=True, **kwargs)


def test_local_audit_windows_reuse_formal_sampling_values_and_masks():
    raw, endpoints, grid = audit_fixture()
    local = local_dataset(raw, endpoints, grid)
    formal = WindowDataset(normalize_bars(raw, source="local", instrument_map={17: "SH17", 23: "SZ23"}),
                           endpoints, grid, length=4, bar_end_is_available=True)
    actual, expected = local.get_batch([0, 1, 2, 3]), formal.get_batch([0, 1, 2, 3])
    for field in ("x", "observed", "step_valid", "predictable", "bar_times", "row_positions"):
        np.testing.assert_array_equal(getattr(actual, field), getattr(expected, field))
    assert all(isinstance(sampler, TSDataSampler) for sampler in local._samplers.values())
    assert actual.metadata["audit_scope"].eq("local_observed_grid").all()
    assert actual.metadata["visibility_basis"].eq("bar_end_only").all()
    assert actual.metadata["availability_assumption"].eq("bar_end_equals_available_at").all()
    assert not actual.metadata["production_visibility_verified"].any()
    assert "instrument" not in actual.metadata
    assert local.data.instrument_map == {}
    assert actual.predictable.tolist() == [False, True, True, True]
    assert actual.step_valid[1].tolist() == [False, False, False, True]
    assert actual.step_valid[3].tolist() == [False, False, False, True]
    assert actual.x[2, :, 0].tolist() == [10, 0, 20, 30]
    assert actual.bar_times[2, 2] == np.datetime64("2024-01-02T11:30")
    assert actual.bar_times[2, 3] == np.datetime64("2024-01-02T13:01")
    assert actual.observed[1, -1, FEATURES.index("volume")]


def test_formal_mapping_guard_and_audit_scope_are_preserved():
    raw, endpoints, grid = audit_fixture()
    unmapped = normalize_local_bars(raw)
    with pytest.raises(ContractError, match="instrument_map"):
        WindowDataset(unmapped, endpoints, grid, bar_end_is_available=True)
    mapped = normalize_bars(raw, source="local", instrument_map={17: "SH17", 23: "SZ23"})
    with pytest.raises(ContractError, match="未附股票代码映射"):
        LocalAuditWindowDataset(mapped, endpoints, grid, bar_end_is_available=True)
    dataset = local_dataset(raw, endpoints, grid)
    with pytest.raises(ContractError, match="WindowDataset"):
        DecisionBatchSampler(dataset)
    batch = dataset.get_batch([0, 1, 2, 3])
    with pytest.raises(ContractError, match="完整且非空"):
        audit_output(pd.DataFrame(columns=["date", "instrument", "score"]),
                     batch.metadata.rename(columns={"decision_time": "date"}),
                     start_date="2024-01-02", end_date="2024-01-03")


def test_local_audit_requires_explicit_availability_assumption():
    raw, endpoints, grid = audit_fixture()
    with pytest.raises(ContractError, match="available_at"):
        LocalAuditWindowDataset(normalize_local_bars(raw), endpoints, grid)
    for flag in ("true", 1, None, np.bool_(True)):
        with pytest.raises(ContractError, match="bar_end_is_available 必须为 bool"):
            LocalAuditWindowDataset(normalize_local_bars(raw), endpoints, grid, bar_end_is_available=flag)
    raw["available_at"] = raw["date"] + pd.Timedelta(seconds=1)
    batch = LocalAuditWindowDataset(normalize_local_bars(raw), endpoints, grid).get_batch([1])
    assert not batch.predictable.any()
    assert batch.metadata["availability_assumption"].eq("none").all()
    assert batch.metadata["visibility_basis"].eq("provided_available_at").all()
    assert not batch.metadata["production_visibility_verified"].any()


def test_local_audit_explicit_grid_and_endpoints_are_validated():
    raw, endpoints, grid = audit_fixture()
    with pytest.raises(ContractError, match="observed_grid.*DatetimeIndex"):
        local_dataset(raw, endpoints, grid.tolist())
    with pytest.raises(ContractError, match="唯一"):
        local_dataset(raw, endpoints, grid.append(grid[-1:]))
    with pytest.raises(ContractError, match="端点"):
        local_dataset(raw, endpoints, grid[:-1])
    with pytest.raises(ContractError, match="sample_id 必须唯一"):
        local_dataset(raw, pd.concat([endpoints, endpoints.iloc[[0]]]), grid)


def test_local_audit_future_changes_cannot_affect_earlier_endpoint():
    raw, endpoints, grid = audit_fixture()
    before = local_dataset(raw, endpoints, grid)[1]
    raw.loc[1:, list(FEATURES)] += 9000
    after = local_dataset(raw, endpoints, grid)[1]
    np.testing.assert_array_equal(before.x, after.x)
    np.testing.assert_array_equal(before.observed, after.observed)
    np.testing.assert_array_equal(before.row_positions, after.row_positions)
    selected = after.bar_times[after.step_valid]
    assert (selected <= grid[0].to_datetime64()).all()


def test_local_audit_fit_row_union_and_collation_preserve_scope():
    raw, endpoints, grid = audit_fixture()
    dataset = local_dataset(raw, endpoints, grid)
    union = fit_row_union(dataset, fit_start="2024-01-02", fit_end="2024-01-02")
    assert union.tolist() == [(grid[0], 17), (grid[2], 17), (grid[3], 17)]
    actual = collate_windows([dataset[2], dataset[1]])
    expected = dataset.get_batch([2, 1])
    for field in ("x", "observed", "step_valid", "predictable", "bar_times", "row_positions"):
        np.testing.assert_array_equal(getattr(actual, field), getattr(expected, field))
    pd.testing.assert_frame_equal(actual.metadata, expected.metadata)
    assert actual.metadata["audit_scope"].eq("local_observed_grid").all()
