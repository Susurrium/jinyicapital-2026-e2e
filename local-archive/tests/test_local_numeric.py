import numpy as np
import pandas as pd
import pytest

from ptop.data import concat_partitions, normalize_bars, normalize_local_bars, read_local_feather_bars
from ptop.schema import BOOK_PRICE_FIELDS, FEATURES, OHLC_FIELDS, SCALE_FIELDS, ContractError


def local_frame():
    frame = pd.DataFrame({name: np.arange(3, dtype=np.int64) + 101 for name in FEATURES})
    frame.loc[:, list(SCALE_FIELDS)] *= 100
    frame["date"] = pd.date_range("2024-01-02 09:31", periods=3, freq="min")
    frame["instrument_id"] = np.array([17, 23, 17], dtype=np.int32)
    frame["adjust_factor"] = [1.0, np.nan, 1.1]
    return frame


def test_local_numeric_matches_mapped_values_and_masks_without_inventing_names():
    frame = local_frame()
    frame.loc[0, list(OHLC_FIELDS)] = -1
    frame.loc[0, list(BOOK_PRICE_FIELDS)] = 0
    frame.loc[0, ["volume", "amount", "deal_number", "bid_volume1", "bid_num_orders1"]] = 0
    frame["available_at"] = frame["date"] + pd.Timedelta(seconds=5)
    original = frame.copy(deep=True)
    numeric = normalize_local_bars(frame)
    mapped = normalize_bars(frame, source="local", instrument_map={17: "SH000017", 23: "SZ000023"})
    pd.testing.assert_frame_equal(numeric.values, mapped.values)
    pd.testing.assert_frame_equal(numeric.observed, mapped.observed)
    pd.testing.assert_frame_equal(numeric.metadata, mapped.metadata.drop(columns="instrument"))
    pd.testing.assert_frame_equal(frame, original)
    assert numeric.instrument_map == {}
    assert "instrument" not in numeric.metadata
    assert numeric.values.index.get_level_values("instrument").dtype == np.dtype("int32")
    assert not numeric.observed.iloc[0][list(OHLC_FIELDS) + list(BOOK_PRICE_FIELDS)].any()
    assert numeric.observed.iloc[0][["volume", "amount", "deal_number", "bid_volume1", "bid_num_orders1"]].all()


def test_local_numeric_preserves_ids_without_accepting_unverified_names():
    frame = local_frame()
    frame["instrument"] = ["unverified", None, "different"]
    result = normalize_local_bars(frame)
    assert result.instrument_map == {}
    assert result.values.index.get_level_values("instrument").tolist() == [17, 23, 17]
    assert result.metadata.columns.tolist() == ["adjust_factor"]


@pytest.mark.parametrize("mapping", [{}, None])
def test_formal_normalization_still_requires_a_mapping(mapping):
    with pytest.raises(ContractError, match="必须提供明确"):
        normalize_bars(local_frame(), source="local", instrument_map=mapping)


def test_local_numeric_counts_identical_duplicates_and_rejects_conflicts():
    frame = local_frame()
    result = normalize_local_bars(pd.concat([frame, frame.iloc[[0]]]))
    assert result.duplicate_rows == 1
    assert len(result.values) == 3
    for field in ("amount", "adjust_factor"):
        conflict = frame.iloc[[0]].copy()
        conflict[field] += 1
        with pytest.raises(ContractError, match="同一 Bar 键出现冲突"):
            normalize_local_bars(pd.concat([frame, conflict]))


@pytest.mark.parametrize("field,value", [("open", -2), ("amount", -1), ("volume", -1), ("bid_price1", -1), ("bid_num_orders1", -1)])
def test_local_numeric_rejects_unknown_negative_values(field, value):
    frame = local_frame()
    frame.loc[0, field] = value
    with pytest.raises(ContractError, match="未知负值"):
        normalize_local_bars(frame)


@pytest.mark.parametrize("value", [np.inf, 100.5])
def test_local_numeric_rejects_nonfinite_and_noninteger_units(value):
    frame = local_frame()
    frame["amount"] = value
    with pytest.raises(ContractError, match="无穷值|整数化"):
        normalize_local_bars(frame)


def test_local_numeric_keeps_float64_for_cent_and_count_resolution():
    frame = local_frame()
    frame["open"] = np.array([16777216, 16777217, 16777218], dtype=np.int64)
    frame["amount"] = np.array([123456789012, 123456789013, 123456789014], dtype=np.int64)
    frame["volume"] = np.array([16777216, 16777217, 16777218], dtype=np.int64)
    result = normalize_local_bars(frame)
    assert all(dtype == np.dtype("float64") for dtype in result.values.dtypes)
    np.testing.assert_array_equal(result.values["open"].to_numpy(), frame["open"].to_numpy(dtype=np.float64) / 100)
    np.testing.assert_array_equal(result.values["amount"].to_numpy(), frame["amount"].to_numpy(dtype=np.float64) / 100)
    np.testing.assert_array_equal(result.values["volume"].to_numpy(), frame["volume"].to_numpy(dtype=np.float64))
    assert np.all(np.diff(result.values["open"].to_numpy()) > 0)
    assert np.all(np.diff(result.values["amount"].to_numpy()) > 0)


def test_local_numeric_availability_requires_explicit_evidence():
    frame = local_frame()
    result = normalize_local_bars(frame)
    assert "available_at" not in result.metadata
    assumed = normalize_local_bars(frame, bar_end_is_available=True)
    assert assumed.metadata["available_at"].tolist() == frame["date"].tolist()
    frame["available_at"] = frame["date"] - pd.Timedelta(seconds=1)
    with pytest.raises(ContractError, match="不能早于"):
        normalize_local_bars(frame)


def test_local_numeric_feather_roundtrip_and_concat(tmp_path):
    frame = local_frame()
    path = tmp_path / "bars.feather"
    frame.to_feather(path)
    expected = normalize_local_bars(frame)
    result = read_local_feather_bars(path)
    pd.testing.assert_frame_equal(result.values, expected.values)
    pd.testing.assert_frame_equal(result.observed, expected.observed)
    pd.testing.assert_frame_equal(result.metadata, expected.metadata)
    assert result.instrument_map == {}
    joined = concat_partitions([normalize_local_bars(frame.iloc[:1]), normalize_local_bars(frame.iloc[1:])])
    pd.testing.assert_frame_equal(joined.values, expected.values)
    assert joined.instrument_map == {}
