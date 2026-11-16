import numpy as np
import pandas as pd
import pytest

from ptop.data import concat_partitions, normalize_bars, read_feather_bars
from ptop.schema import BOOK_PRICE_FIELDS, FEATURES, OHLC_FIELDS, SCALE_FIELDS, ContractError


def make_frame(source="cloud", rows=3):
    frame = pd.DataFrame({name: np.arange(rows, dtype=float) + 10 for name in FEATURES})
    frame["date"] = pd.date_range("2024-01-02 09:31", periods=rows, freq="min")
    frame["instrument_id"] = 1
    frame["adjust_factor"] = 1.0
    if source == "local":
        frame.loc[:, list(SCALE_FIELDS)] *= 100
        frame[list(FEATURES)] = frame[list(FEATURES)].astype("int64")
    return frame


def normalize(frame, source="cloud", **kwargs):
    return normalize_bars(frame, source=source, instrument_map={1: "SH000001", 2: "SZ000002"}, **kwargs)


def test_units_observed_zero_and_source_preserved():
    local, cloud = make_frame("local"), make_frame()
    local.loc[0, list(OHLC_FIELDS)] = -1
    cloud.loc[0, list(OHLC_FIELDS)] = np.nan
    for frame in (local, cloud):
        frame.loc[0, list(BOOK_PRICE_FIELDS)] = 0
        frame.loc[0, ["volume", "bid_volume1", "bid_num_orders1"]] = 0
    original = local.copy(deep=True)
    left, right = normalize(local, "local"), normalize(cloud)
    pd.testing.assert_frame_equal(left.values, right.values)
    pd.testing.assert_frame_equal(left.observed, right.observed)
    pd.testing.assert_frame_equal(local, original)
    assert not left.observed.iloc[0]["bid_price1"]
    assert left.observed.iloc[0]["bid_volume1"]
    assert left.observed.iloc[0]["bid_num_orders1"]
    assert left.values.iloc[0]["volume"] == 0
    assert left.observed.iloc[0]["volume"]
    assert "adjust_factor" in left.metadata
    assert tuple(left.values.columns) == FEATURES


def test_equal_duplicates_counted_and_conflicts_fail():
    frame = make_frame()
    result = normalize(pd.concat([frame, frame.iloc[[0]]]))
    assert result.duplicate_rows == 1
    assert len(result.values) == 3
    conflict = frame.iloc[[0]].copy()
    conflict["amount"] += 1
    with pytest.raises(ContractError, match="冲突"):
        normalize(pd.concat([frame, conflict]))


@pytest.mark.parametrize("column,value", [("volume", -1), ("bid_volume1", -1), ("open", -1), ("amount", np.inf)])
def test_invalid_cloud_values_fail(column, value):
    frame = make_frame()
    frame.loc[0, column] = value
    with pytest.raises(ContractError):
        normalize(frame)


def test_schema_mapping_units_fail_early():
    frame = make_frame()
    with pytest.raises(ContractError, match="缺少必要"):
        normalize(frame.drop(columns="deal_number"))
    with pytest.raises(ContractError, match="未知来源"):
        normalize(frame, "unknown")
    with pytest.raises(ContractError, match="无法映射"):
        normalize_bars(frame, source="cloud", instrument_map={3: "SH3"})
    frame["instrument"] = "different"
    with pytest.raises(ContractError, match="映射冲突"):
        normalize(frame)
    frame = make_frame("local")
    frame["amount"] = 1.234
    with pytest.raises(ContractError, match="整数化"):
        normalize(frame, "local")


def test_timestamps_and_availability():
    frame = make_frame()
    frame.loc[0, "adjust_factor"] = np.nan
    frame["date"] = frame["date"].dt.tz_localize("Asia/Shanghai").dt.tz_convert("UTC")
    result = normalize(frame, bar_end_is_available=True)
    assert result.values.index[0][0] == pd.Timestamp("2024-01-02 09:31")
    assert result.metadata.iloc[0]["available_at"] == pd.Timestamp("2024-01-02 09:31")
    assert np.isnan(result.metadata.iloc[0]["adjust_factor"])
    frame["available_at"] = frame["date"] - pd.Timedelta(seconds=1)
    with pytest.raises(ContractError, match="不能早于"):
        normalize(frame)


@pytest.mark.parametrize("value", ["false", 1, None, np.bool_(True)])
def test_bar_end_availability_requires_python_bool(value):
    with pytest.raises(ContractError, match="bar_end_is_available 必须为 bool"):
        normalize(make_frame(), bar_end_is_available=value)


def test_feather_and_partition_roundtrip(tmp_path):
    frame = make_frame("local")
    path = tmp_path / "part.feather"
    frame.to_feather(path)
    actual = read_feather_bars(path, source="local", instrument_map={1: "SH000001", 2: "SZ000002"})
    expected = normalize(frame, "local")
    pd.testing.assert_frame_equal(actual.values, expected.values)
    parts = [normalize(frame.iloc[:1], "local"), normalize(frame.iloc[1:], "local")]
    joined = concat_partitions(parts)
    pd.testing.assert_frame_equal(joined.values, expected.values)
    with pytest.raises(ContractError, match="重叠"):
        concat_partitions([parts[0], parts[0]])
