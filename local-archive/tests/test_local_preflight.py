import json

import numpy as np
import pandas as pd
import pyarrow.feather as feather
import pytest

from ptop.data import normalize_local_bars
from ptop.local_preflight import audit_endpoints, run_local_preflight, verify_local_reference_windows
from ptop.schema import FEATURES
from ptop.windows import LocalAuditWindowDataset, fit_row_union


def raw_fixture():
    times = pd.DatetimeIndex(["2023-08-01 09:31", "2023-08-01 09:32", "2023-08-01 11:30",
                              "2023-08-01 13:01", "2023-08-02 09:31", "2023-08-02 09:32",
                              "2023-08-02 11:30", "2023-08-02 13:01"])
    frame = pd.MultiIndex.from_product([times, [7, 19]], names=["date", "instrument_id"]).to_frame(index=False)
    for position, field in enumerate(FEATURES):
        frame[field] = np.arange(len(frame)) * (position + 1) + 1000
    return frame


def test_audit_endpoints_preserve_gaps_and_cover_unique_raw_rows():
    data = normalize_local_bars(raw_fixture())
    expected, grid = audit_endpoints(data)
    assert not any(grid.hour == 12)
    assert expected["sample_id"].is_unique
    assert "instrument" not in expected
    windows = LocalAuditWindowDataset(data, expected, grid, bar_end_is_available=True)
    reference = fit_row_union(windows, fit_start="2023-08-01", fit_end="2023-08-02")
    assert reference.equals(data.values.index)


def test_preflight_integrates_real_file_interfaces_and_separates_diagnostic_state(tmp_path):
    path = tmp_path / "fixture.feather"
    feather.write_feather(raw_fixture(), path)
    report_path = tmp_path / "audit.json"
    result = run_local_preflight(path, report_path=report_path, cache_directory=tmp_path / "cache",
                                 fit_days=1, heldout_days=1, length=5, seeds=(17,))
    assert result["formal_training_eligible"] is False
    assert result["canonical_rows"] == 16
    assert result["fit_referenced_unique_rows"] == 8
    assert result["preprocessing"]["candidates"]["N1"]["real_model_checks"]["future_bar_mutation"] == "passed"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "completed_local_diagnostic"
    verification = verify_local_reference_windows(report_path, output_path=tmp_path / "windows.json")
    assert verification["reference_grid_comparison"] == "passed"
