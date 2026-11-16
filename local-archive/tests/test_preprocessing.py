import copy
import json

import numpy as np
import pandas as pd
import pytest
from ptop._vendor.qlib.processors import Fillna, RobustZScoreNorm, ZScoreNorm

from ptop.preprocessing import FrozenPreprocessor
from ptop.schema import FEATURES, PRICE_FIELDS, ContractError


@pytest.fixture
def raw_data():
    index = pd.MultiIndex.from_product(
        [pd.date_range("2026-09-01 09:31", periods=16, freq="min"), [1, 2]],
        names=["datetime", "instrument"],
    )
    rng = np.random.default_rng(101)
    values = pd.DataFrame(rng.uniform(10, 100, (len(index), len(FEATURES))), index=index, columns=FEATURES)
    values.iloc[3, 0] = np.nan
    values.iloc[5, 7] = np.nan
    values.loc[:, "volume"] = np.arange(len(values), dtype=np.float64)
    return values, values.notna()


def fit_processor(values, observed, mode="N0", **kwargs):
    processor = FrozenPreprocessor(mode, **kwargs)
    return processor.fit(
        values, observed, referenced_rows=values.index, fit_start="2026-09-01", fit_end="2026-09-01"
    )


@pytest.mark.parametrize("mode,official_class", [("N0", RobustZScoreNorm), ("N1", ZScoreNorm)])
def test_matches_embedded_processor_and_preserves_input(raw_data, mode, official_class):
    values, observed = raw_data
    original = values.copy(deep=True)
    processor = fit_processor(values, observed, mode).freeze(scale_review="synthetic-equivalence")
    expected = values.copy()
    expected.columns = pd.MultiIndex.from_product([["feature"], FEATURES])
    kwargs = {"clip_outlier": False} if mode == "N0" else {}
    official = official_class("2026-09-01", "2026-09-02", fields_group="feature", **kwargs)
    official.fit(expected)
    expected = Fillna(fields_group="feature")(official(expected))["feature"].astype(np.float32)
    pd.testing.assert_frame_equal(processor.transform(values, observed), expected)
    pd.testing.assert_frame_equal(values, original)
    assert processor.transform(values, observed).loc[values.index[3], "open"] == 0
    assert observed.loc[values.index[0], "volume"]


@pytest.mark.parametrize("mode,base", [("N0", "N0"), ("N1", "N1"), ("N2", "N0"), ("N2", "N1")])
def test_per_column_fit_partition_transform_and_json_reload(raw_data, tmp_path, mode, base):
    values, observed = raw_data
    whole = fit_processor(values, observed, mode, n2_base=base).freeze(scale_review="synthetic-equivalence")
    by_column = FrozenPreprocessor(mode, n2_base=base).fit(
        values,
        observed,
        referenced_rows=values.index,
        fit_start="2026-09-01",
        fit_end="2026-09-01",
        by_column=True,
    ).freeze(scale_review="synthetic-equivalence")
    # nanmean/nanstd 在不同内存布局的约简末位可能不同，按 float32 验收容差核对。
    np.testing.assert_allclose(
        whole.transform(values, observed), by_column.transform(values, observed), atol=1e-6, rtol=1e-5
    )
    path = tmp_path / "processor.json"
    whole.save(path)
    restored = FrozenPreprocessor.load(path)
    assert whole.fingerprint == restored.fingerprint
    combined = pd.concat(
        [restored.transform(values.iloc[:11], observed.iloc[:11]), restored.transform(values.iloc[11:], observed.iloc[11:])]
    )
    pd.testing.assert_frame_equal(whole.transform(values, observed), combined)
    restored.transform(values.iloc[::-1], observed.iloc[::-1])
    assert restored.fingerprint == whole.fingerprint


def test_fit_uses_unique_referenced_training_rows_only(raw_data):
    values, observed = raw_data
    tomorrow = values.iloc[:8].copy()
    tomorrow.index = pd.MultiIndex.from_arrays(
        [tomorrow.index.get_level_values("datetime") + pd.Timedelta(days=1), tomorrow.index.get_level_values("instrument")],
        names=values.index.names,
    )
    tomorrow[:] = 1e8
    full = pd.concat([values, tomorrow])
    reference = values.index[:20].append(values.index[:12]).append(tomorrow.index)
    fitted = FrozenPreprocessor("N1").fit(
        full, full.notna(), referenced_rows=reference, fit_start="2026-09-01", fit_end="2026-09-01"
    ).freeze(scale_review="synthetic-equivalence")
    expected = fit_processor(values.iloc[:20], observed.iloc[:20], "N1").freeze(scale_review="synthetic-equivalence")
    assert fitted.fit_row_count == 20
    pd.testing.assert_frame_equal(fitted.transform(values, observed), expected.transform(values, observed))
    assert fitted.fit_rows_fingerprint == expected.fit_rows_fingerprint


@pytest.mark.parametrize("base,official_class", [("N0", RobustZScoreNorm), ("N1", ZScoreNorm)])
def test_n2_shared_price_scale_matches_official_single_column(raw_data, base, official_class):
    values, observed = raw_data
    fitted = fit_processor(values, observed, "N2", n2_base=base).freeze(scale_review="synthetic-equivalence")
    pooled_values = values.loc[:, list(PRICE_FIELDS)].to_numpy().reshape(-1)
    index = pd.MultiIndex.from_arrays(
        [np.repeat(values.index.get_level_values("datetime"), len(PRICE_FIELDS)), np.arange(len(pooled_values))],
        names=values.index.names,
    )
    pooled = pd.DataFrame(pooled_values, index=index, columns=pd.MultiIndex.from_tuples([("feature", "price")]))
    kwargs = {"clip_outlier": False} if base == "N0" else {}
    official = official_class("2026-09-01", "2026-09-02", fields_group="feature", **kwargs)
    official.fit(pooled)
    state = fitted.state_dict()["statistics"]
    positions = [FEATURES.index(field) for field in PRICE_FIELDS]
    np.testing.assert_array_equal(np.asarray(state["center"])[positions], np.repeat(official.mean_train, 10))
    np.testing.assert_array_equal(np.asarray(state["scale"])[positions], np.repeat(official.std_train, 10))
    normalized = fitted.transform(values, observed)
    for row in range(len(values)):
        original = values.iloc[row].loc[list(PRICE_FIELDS)].dropna()
        scaled = normalized.iloc[row].loc[original.index]
        np.testing.assert_array_equal(np.argsort(original), np.argsort(scaled))
        np.testing.assert_allclose(scaled * official.std_train[0] + official.mean_train[0], original, atol=1e-5, rtol=1e-6)


def test_n0_degenerate_mad_cannot_freeze(raw_data):
    values, observed = raw_data
    values.loc[:, "deal_number"] = 5.0
    fitted = fit_processor(values, observed)
    assert "deal_number" in fitted.training_diagnostics["degenerate_fields"]
    with pytest.raises(ContractError, match="MAD"):
        fitted.freeze(scale_review="synthetic-degenerate")


def test_n1_constant_semantics_and_validation_change_record(raw_data):
    values, observed = raw_data
    values.loc[:, "deal_number"] = 5.0
    fitted = fit_processor(values, observed, "N1").freeze(scale_review="synthetic-constant")
    assert (fitted.transform(values, observed)["deal_number"] == 5).all()
    validation = values.copy()
    validation.loc[:, "deal_number"] = 8.0
    restored = FrozenPreprocessor.from_state_dict(fitted.state_dict())
    assert (restored.transform(validation, observed)["deal_number"] == 8).all()
    assert restored.diagnostics(validation, observed)["fields"]["deal_number"]["training_constant_changed"]


def test_empty_column_and_unknown_reference_fail(raw_data):
    values, observed = raw_data
    empty = values.copy()
    empty.loc[:, "deal_number"] = np.nan
    with pytest.raises(ContractError, match="没有有效观测"):
        fit_processor(empty, empty.notna())
    missing = pd.MultiIndex.from_tuples([(pd.Timestamp("2026-09-01 15:00"), 1)], names=values.index.names)
    with pytest.raises(ContractError, match="缺少原始数据"):
        FrozenPreprocessor().fit(
            values, observed, referenced_rows=missing, fit_start="2026-09-01", fit_end="2026-09-01"
        )


def test_inference_and_loading_never_call_fit(raw_data, monkeypatch):
    values, observed = raw_data
    fitted = fit_processor(values, observed).freeze(scale_review="synthetic-lifecycle")
    before = fitted.fingerprint

    def reject_fit(*args, **kwargs):
        raise AssertionError("推理调用了 fit")

    monkeypatch.setattr(RobustZScoreNorm, "fit", reject_fit)
    restored = FrozenPreprocessor.from_state_dict(fitted.state_dict())
    restored.transform(values, observed)
    assert restored.fingerprint == before


def test_freeze_review_missing_state_and_tampering_fail(raw_data):
    values, observed = raw_data
    fitted = fit_processor(values, observed)
    with pytest.raises(ContractError, match="尚未.*冻结"):
        fitted.transform(values, observed)
    with pytest.raises(ContractError, match="审阅"):
        fitted.freeze(scale_review="")
    fitted.freeze(scale_review="synthetic-lifecycle")
    state = fitted.state_dict()
    changed = copy.deepcopy(state)
    changed["statistics"]["center"][0] += 1
    with pytest.raises(ContractError, match="指纹"):
        FrozenPreprocessor.from_state_dict(changed)
    incomplete = copy.deepcopy(state)
    del incomplete["statistics"]
    with pytest.raises(ContractError, match="字段缺失"):
        FrozenPreprocessor.from_state_dict(incomplete)
    fitted._processor.mean_train[0] += 1
    with pytest.raises(ContractError, match="外部修改"):
        fitted.transform(values, observed)


def test_float32_overflow_and_invalid_masks_fail(raw_data):
    values, observed = raw_data
    fitted = fit_processor(values, observed, "N1").freeze(scale_review="synthetic-limits")
    overflow = values.copy()
    overflow.iloc[0, 0] = 1e100
    with pytest.raises(ContractError, match="float32"):
        fitted.transform(overflow, observed)
    wrong_mask = observed.copy()
    wrong_mask.iloc[0, 0] = False
    with pytest.raises(ContractError, match="必须为 NaN"):
        fitted.transform(values, wrong_mask)


def test_quality_report_is_json_safe_and_keeps_groups(raw_data):
    values, observed = raw_data
    fitted = fit_processor(values, observed)
    report = fitted.training_diagnostics
    json.dumps(report, allow_nan=False)
    assert report["fields"]["volume"]["zero_fraction"] > 0
    assert report["by_price_magnitude"]
    assert set(report["by_intraday_time"]) == set(values.index.get_level_values("datetime").strftime("%H:%M"))
    assert report["fields"]["open"]["valid_count"] == int(observed["open"].sum())
