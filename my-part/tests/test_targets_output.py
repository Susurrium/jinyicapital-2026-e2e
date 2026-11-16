import numpy as np
import pandas as pd
import pytest

from ptop.output import audit_output
from ptop.schema import ContractError
from ptop.targets import LabelSpec, TimeFold, attach_targets, make_time_folds


def test_targets_missing_support_and_no_overnight():
    samples = pd.DataFrame({"sample_id": [1, 2], "decision_time": pd.to_datetime(["2024-01-02 10:00"] * 2),
                            "instrument_id": [1, 2]})
    spec = LabelSpec("synthetic-v1", "test fixture", "fixture target", "none", "explicit support")
    targets = pd.DataFrame({"sample_id": [1], "target": [0.2], "target_valid": [True],
                            "target_start": ["2024-01-02 10:00"], "target_end": ["2024-01-02 10:30"],
                            "label_spec_version": ["synthetic-v1"]})
    attached = attach_targets(samples, targets, spec)
    assert attached["target_valid"].tolist() == [True, False]
    assert np.isnan(attached.loc[1, "target"])
    targets.loc[0, "target_end"] = "2024-01-03 10:30"
    with pytest.raises(ContractError, match="跨夜"):
        attach_targets(samples, targets, spec)


def test_fold_purges_by_real_target_support():
    folds = make_time_folds(pd.date_range("2024-01-01", periods=20, freq="D"))
    assert [fold.validation_start.day for fold in folds] == [13, 16, 19]
    samples = pd.DataFrame({"decision_time": pd.to_datetime(["2024-01-12 14:00", "2024-01-12 14:00", "2024-01-13 10:00"]),
                            "target_end": pd.to_datetime(["2024-01-12 14:30", "2024-01-13 00:00", "2024-01-13 10:30"]),
                            "target_valid": [True] * 3, "predictable": [True] * 3})
    train, validation = folds[0].split(samples)
    assert train.index.tolist() == [0]
    assert validation.index.tolist() == [2]


def test_coverage_uses_complete_expected_set():
    expected = pd.DataFrame({"date": [pd.Timestamp("2024-01-02 10:00")] * 5,
                             "instrument": list("abcde")})
    output = expected.iloc[:3].assign(score=[0.1, 0.2, 0.3])
    report = audit_output(output, expected, start_date="2024-01-02", end_date="2024-01-03")
    assert report.iloc[0]["missing_rate"] == pytest.approx(0.4)
    with pytest.raises(ContractError, match="覆盖"):
        audit_output(output.iloc[:2], expected, start_date="2024-01-02", end_date="2024-01-03")
    with pytest.raises(ContractError, match="覆盖"):
        audit_output(output.iloc[:0], expected, start_date="2024-01-02", end_date="2024-01-03")


def test_output_rejects_unknown_key_and_infinity():
    expected = pd.DataFrame({"date": [pd.Timestamp("2024-01-02 10:00")], "instrument": ["a"]})
    with pytest.raises(ContractError, match="有限"):
        audit_output(expected.assign(score=np.inf), expected, start_date="2024-01-02", end_date="2024-01-03")
    with pytest.raises(ContractError, match="以外"):
        audit_output(expected.assign(instrument="b", score=0.0), expected,
                     start_date="2024-01-02", end_date="2024-01-03")


def test_date_only_end_includes_intraday_output():
    expected = pd.DataFrame({"date": [pd.Timestamp("2024-01-02 14:30")], "instrument": ["a"]})
    report = audit_output(expected.assign(score=0.0), expected,
                          start_date="2024-01-02 10:00", end_date="2024-01-02")
    assert report.iloc[0]["predicted"] == 1


def test_time_fold_rejects_reversed_boundaries():
    with pytest.raises(ContractError, match="严格递增"):
        TimeFold("invalid", "2024-01-02", "2024-01-01", "2024-01-03")
