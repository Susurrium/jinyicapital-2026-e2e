import numpy as np
import pandas as pd
import pytest

from ptop.official import LABEL_TABLE, SECTION_TABLE, expected_from_sections, fetch_inference_inputs, fetch_label_values, official_targets
from ptop.schema import FEATURES, ContractError
from ptop.targets import LabelSpec


def sections():
    return pd.DataFrame({"date": pd.to_datetime(["2024-01-02 10:00", "2024-01-02 09:30", "2024-01-02 10:00"]),
                         "instrument": ["SH1", "SZ2", "SZ2"]})


def test_sections_define_full_stable_set_independent_of_order_or_partition():
    source = sections()
    expected = expected_from_sections(source, {1: "SH1", 2: "SZ2"})
    reordered = expected_from_sections(source.iloc[::-1], {1: "SH1", 2: "SZ2"})
    pd.testing.assert_frame_equal(expected, reordered)
    partition = expected_from_sections(source.iloc[[0]], {1: "SH1", 2: "SZ2"})
    assert partition.sample_id.iloc[0] in expected.sample_id.tolist()
    assert expected.groupby("decision_time").decision_id.nunique().eq(1).all()
    assert expected.sample_id.is_unique
    duplicated = expected_from_sections(pd.concat([source, source.iloc[[0]]]), {1: "SH1", 2: "SZ2"})
    assert duplicated.attrs["duplicate_rows"] == 1
    assert len(duplicated) == 3


def test_section_mapping_and_duplicate_conflict_fail():
    with pytest.raises(ContractError, match="无法映射"):
        expected_from_sections(sections(), {1: "SH1"})
    extra = sections().iloc[[0]].copy()
    extra["instrument_id"] = 2
    original = sections().assign(instrument_id=[1, 2, 2])
    with pytest.raises(ContractError, match="冲突"):
        expected_from_sections(pd.concat([original, extra]), {1: "SH1", 2: "SZ2"})


def target_inputs():
    expected = expected_from_sections(sections(), {1: "SH1", 2: "SZ2"})
    labels = expected[["decision_time", "instrument"]].rename(columns={"decision_time": "date"})
    labels["vwap_return"] = [0.012345678901, np.nan, -0.02]
    support = pd.DataFrame({"sample_id": expected.sample_id, "target_valid": True,
                            "target_start": expected.decision_time,
                            "target_end": expected.decision_time + pd.Timedelta(minutes=30),
                            "label_spec_version": "synthetic-explicit-support-v1"})
    spec = LabelSpec("synthetic-explicit-support-v1", LABEL_TABLE, "官方列 vwap_return", "明确声明的合成测试合同", "明确提供的合成支持区间")
    return expected, labels, support, spec


def test_official_labels_are_direct_values_and_missing_stays_invalid():
    expected, labels, support, spec = target_inputs()
    result = official_targets(expected, labels, support, spec)
    assert result.target_valid.tolist() == [True, False, True]
    assert result.target.iloc[0] == labels.vwap_return.iloc[0]
    assert result.target.iloc[2] == -0.02
    assert np.isnan(result.target.iloc[1])
    pd.testing.assert_series_equal(result.sample_id, expected.sample_id)


@pytest.mark.parametrize("value", [np.inf, -np.inf])
def test_matched_infinite_official_targets_fail(value):
    expected, labels, support, spec = target_inputs()
    labels.loc[0, "vwap_return"] = value
    with pytest.raises(ContractError, match="vwap_return 存在无穷值"):
        official_targets(expected, labels, support, spec)


def test_target_support_is_required_and_conflicting_labels_fail():
    expected, labels, support, spec = target_inputs()
    with pytest.raises(ContractError, match="支持区间"):
        official_targets(expected, labels, support.iloc[1:], spec)
    with pytest.raises(ContractError, match="支持区间"):
        official_targets(expected, labels, None, spec)
    changed = labels.iloc[[0]].copy()
    changed["vwap_return"] = 123
    with pytest.raises(ContractError, match="冲突"):
        official_targets(expected, pd.concat([labels, changed]), support, spec)
    support.loc[0, "target_end"] = pd.Timestamp("2024-01-03 10:00")
    with pytest.raises(ContractError, match="跨夜"):
        official_targets(expected, labels, support, spec)


class QuerySpy:
    # 只隔离查询路由和返回合同；不模拟或声称连接了真实 DAI 服务。
    def __init__(self, source_sections, bars, labels):
        self.sections, self.bars, self.labels = source_sections, bars, labels
        self.calls = []

    def __call__(self, sql, *, filters):
        self.calls.append((sql, filters))
        if SECTION_TABLE in sql:
            frame = self.sections
        elif LABEL_TABLE in sql:
            frame = self.labels
        else:
            frame = self.bars

        class Result:
            def df(self):
                return frame.copy(deep=True)

        return Result()


def query_spy():
    bars = pd.DataFrame({name: [10.] for name in FEATURES})
    bars["date"] = pd.to_datetime(["2024-01-02 09:30"])
    bars["instrument_id"] = 1
    bars["instrument"] = "SH1"
    bars["adjust_factor"] = 1.
    labels = sections().assign(vwap_return=0.01)
    return QuerySpy(sections(), bars, labels)


def test_inference_query_routing_uses_dynamic_table_and_never_reads_labels():
    spy = query_spy()
    data, expected = fetch_inference_inputs(spy, {"bar1m": "platform_current_bar"},
                                            start_date="2024-01-02", end_date="2024-01-02 15:00",
                                            history_start="2024-01-01", instrument_map={1: "SH1", 2: "SZ2"},
                                            bar_end_is_available=True)
    assert len(expected) == 3
    assert len(data.values) == 1
    assert len(spy.calls) == 2
    assert "platform_current_bar" in spy.calls[1][0]
    assert all(LABEL_TABLE not in sql for sql, _ in spy.calls)
    assert spy.calls[1][1]["instrument"] == ["SH1", "SZ2"]
    assert spy.calls[1][1]["date"][0] == "2024-01-01 00:00:00"
    assert "available_at" in data.metadata


def test_label_query_is_separate_and_invalid_routes_fail_before_query():
    spy = query_spy()
    result = fetch_label_values(spy, start_date="2024-01-02", end_date="2024-01-02 15:00")
    pd.testing.assert_frame_equal(result, spy.labels)
    assert len(spy.calls) == 1 and LABEL_TABLE in spy.calls[0][0]
    with pytest.raises(ContractError, match="表名"):
        fetch_inference_inputs(spy, {"bar1m": "table; DROP TABLE x"},
                               start_date="2024-01-02", end_date="2024-01-02 15:00", history_start="2024-01-01",
                               instrument_map={1: "SH1", 2: "SZ2"})
    assert len(spy.calls) == 1


def test_date_only_end_includes_full_day_and_keeps_start_time():
    spy = query_spy()
    data, expected = fetch_inference_inputs(spy, {"bar1m": "platform_current_bar"},
                                            start_date="2024-01-02 09:30", end_date="2024-01-02",
                                            history_start="2024-01-02", instrument_map={1: "SH1", 2: "SZ2"})
    assert len(data.values) == 1 and len(expected) == 3
    assert spy.calls[0][1]["date"] == ["2024-01-02 09:30:00", "2024-01-02 23:59:59.999999999"]
    assert spy.calls[1][1]["date"][1] == "2024-01-02 23:59:59.999999999"
    result = fetch_label_values(spy, start_date="2024-01-02", end_date="2024-01-02")
    pd.testing.assert_frame_equal(result, spy.labels)
    assert spy.calls[-1][1]["date"][1] == "2024-01-02 23:59:59.999999999"


def test_non_midnight_end_stays_exact():
    spy = query_spy()
    fetch_label_values(spy, start_date="2024-01-02", end_date="2024-01-02 10:00")
    assert spy.calls[0][1]["date"][1] == "2024-01-02 10:00:00"
    with pytest.raises(ContractError, match="时间过滤范围"):
        fetch_label_values(spy, start_date="2024-01-02", end_date="2024-01-02 09:59")


@pytest.mark.parametrize("value", ["false", 1, None, np.bool_(True)])
def test_inference_availability_requires_python_bool_before_query(value):
    spy = query_spy()
    with pytest.raises(ContractError, match="bar_end_is_available 必须为 bool"):
        fetch_inference_inputs(spy, {"bar1m": "platform_current_bar"},
                               start_date="2024-01-02", end_date="2024-01-02", history_start="2024-01-02",
                               instrument_map={1: "SH1", 2: "SZ2"}, bar_end_is_available=value)
    assert spy.calls == []
