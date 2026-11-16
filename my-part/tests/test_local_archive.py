import hashlib
import json
from pathlib import Path
import tarfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather
import pytest

from ptop.local_archive import audit_archive, audit_feather, locate_negative_values
from ptop.schema import FEATURES, ContractError


def make_frame():
    frame = pd.DataFrame({name: [100, 100, 100] for name in FEATURES})
    frame["date"] = pd.date_range("2023-08-01 09:31", periods=3, freq="min")
    frame["instrument_id"] = np.int16(1)
    frame["adjust_factor"] = np.float32(1)
    return frame


def save_frame(path, frame):
    feather.write_feather(pa.Table.from_pandas(frame, preserve_index=False), path, chunksize=2)


def make_archive(directory, frames):
    archive_path = directory / "synthetic.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for index, frame in enumerate(frames):
            path = directory / f"input-{index}.feather"
            save_frame(path, frame)
            archive.add(path, arcname=f"bars/{index}.feather")
    return archive_path


def run_archive(directory, frames):
    archive_path = make_archive(directory, frames)
    report = audit_archive(archive_path, work_dir=directory / "audit-work",
                           report_path=directory / "report.json", first_member_path=directory / "first.feather")
    assert report["source"]["sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert json.loads((directory / "report.json").read_text(encoding="utf-8")) == report
    return report


def test_real_zeros_sentinels_and_invalid_values_are_distinct(tmp_path):
    frame = make_frame()
    frame.loc[0, "open"] = -1
    frame.loc[0, "bid_price1"] = 0
    frame.loc[0, "volume"] = 0
    frame.loc[1, "bid_volume1"] = -2
    frame["amount"] = [np.inf, np.nan, 1.25]
    path = tmp_path / "bars.feather"
    save_frame(path, frame)
    report = audit_feather(path, keys_path=tmp_path / "keys.feather")
    assert report["record_batches"] == 2
    assert report["rows"] == 3
    assert report["fields"]["open"]["unknown_negative"] == 0
    assert report["fields"]["open"]["sentinel_missing"] == 1
    assert report["fields"]["bid_price1"]["sentinel_missing"] == 1
    assert report["fields"]["bid_volume1"]["unknown_negative"] == 1
    assert report["fields"]["bid_volume1"]["observed"] == 2
    assert report["fields"]["volume"]["zero"] == 1
    assert report["fields"]["volume"]["observed"] == 3
    assert report["fields"]["amount"]["infinite"] == 1
    assert report["fields"]["amount"]["fractional"] == 1
    assert report["fields"]["amount"]["observed"] == 0
    assert report["fields"]["amount"]["null"] + report["fields"]["amount"]["nan"] == 1
    assert report["relationships"]["bid1_missing_price_volume_positive"] == 1


def test_within_member_duplicates_compared_across_record_batches(tmp_path):
    frame = make_frame()
    same = frame.iloc[[0]].copy()
    conflict = frame.iloc[[1]].copy()
    conflict["amount"] += 1
    report = run_archive(tmp_path, [pd.concat([frame, same, conflict], ignore_index=True)])
    assert report["members"][0]["duplicates"] == {"duplicate_extra_rows": 2, "identical_extra_rows": 1, "conflicting_keys": 1}
    assert report["status"] == "source_contract_violations"


def test_cross_member_duplicates_are_checked_by_actual_values(tmp_path):
    frame = make_frame()
    other = frame.copy()
    other.loc[1, "volume"] += 1
    report = run_archive(tmp_path, [frame, other])
    assert len(report["cross_member_duplicates"]) == 1
    summary = report["cross_member_duplicates"][0]
    assert summary["identical_extra_rows"] == 2
    assert summary["conflicting_keys"] == 1
    assert report["violations"]["cross_member_conflicting_key_pairs"] == 1


def test_disjoint_members_all_rows_and_original_hash_preserved(tmp_path):
    frame = make_frame()
    later = frame.copy()
    later["date"] += pd.Timedelta(days=31)
    report = run_archive(tmp_path, [frame, later])
    assert report["status"] == "local_storage_checks_passed"
    assert report["schema_consistent"]
    assert report["totals"] == {"rows": 6, "feather_members": 2}
    assert report["cross_member_duplicates"] == []
    assert Path(report["retained_first_member"]).is_file()
    assert not (tmp_path / "audit-work/member-0001.feather").exists()
    assert report["members"][0]["date_rows"] == {"2023-08-01": 3}
    assert report["members"][0]["instrument_rows"] == {"1": 3}


def test_later_nonretained_duplicate_member_is_rechecked(tmp_path):
    earlier = make_frame()
    later = earlier.copy()
    later["date"] += pd.Timedelta(days=31)
    report = run_archive(tmp_path, [earlier, later, later])
    assert report["cross_member_duplicates"][0]["identical_extra_rows"] == 3
    assert not (tmp_path / "audit-work/duplicate-review.feather").exists()


@pytest.mark.parametrize("problem", ["missing_field", "invalid_time", "null_key"])
def test_invalid_schema_and_missing_keys_fail_early(tmp_path, problem):
    frame = make_frame()
    if problem == "missing_field":
        frame = frame.drop(columns="volume")
    elif problem == "invalid_time":
        frame["date"] = 1
    else:
        frame.loc[0, "date"] = pd.NaT
    path = tmp_path / "bad.feather"
    save_frame(path, frame)
    with pytest.raises(ContractError):
        audit_feather(path, keys_path=tmp_path / "keys.feather")


def test_diagnostic_price_relations_and_minute_alignment(tmp_path):
    frame = make_frame()
    frame.loc[0, "high"] = 90
    frame.loc[1, "ask_price1"] = 90
    frame.loc[2, "bid_price2"] = 110
    frame.loc[2, "date"] += pd.Timedelta(seconds=1)
    report = run_archive(tmp_path, [frame])
    member = report["members"][0]
    assert member["relationships"]["high_below_low"] == 1
    assert member["relationships"]["crossed_top_book"] == 1
    assert member["relationships"]["bid_levels_1_2_inverted"] == 1
    assert member["non_minute_timestamps"] == 1
    assert report["status"] == "source_contract_violations"


def test_negative_locator_preserves_values_and_groups_actual_keys(tmp_path):
    frame = make_frame()
    frame.loc[0, "bid_num_orders1"] = -32760
    frame.loc[0, "ask_num_orders1"] = -2
    frame.loc[1, "ask_num_orders1"] = -1
    frame.loc[2, "open"] = -1
    run_archive(tmp_path, [frame])
    result = locate_negative_values(tmp_path / "synthetic.tar.gz", audit_report_path=tmp_path / "report.json",
                                     work_dir=tmp_path / "locate", report_path=tmp_path / "negative.json",
                                     records_path=tmp_path / "negative.parquet")
    records = pd.read_parquet(tmp_path / "negative.parquet")
    assert result["status"] == "blocked_unknown_negative_values"
    assert result["unknown_negative_values"] == 3
    assert result["affected_bar_keys"] == 2
    assert result["affected_instruments"] == 1
    assert result["fields"]["ask_num_orders1"]["negative_max"] == -1
    assert result["by_date"] == {"2023-08-01": 3}
    assert result["by_instrument"] == {"1": 3}
    assert sorted(records["raw_value"]) == [-32760, -2, -1]
    assert "open" not in set(records["field"])


def test_negative_locator_requires_matching_source_fingerprint(tmp_path):
    frame = make_frame()
    frame.loc[0, "bid_num_orders1"] = -5
    run_archive(tmp_path, [frame])
    baseline_path = tmp_path / "report.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["source"]["sha256"] = "incorrect"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(ContractError, match="SHA-256"):
        locate_negative_values(tmp_path / "synthetic.tar.gz", audit_report_path=baseline_path,
                               work_dir=tmp_path / "locate", report_path=tmp_path / "negative.json",
                               records_path=tmp_path / "negative.parquet")
    assert not (tmp_path / "negative.parquet").exists()


def test_negative_locator_handles_archive_without_unknown_negatives(tmp_path):
    run_archive(tmp_path, [make_frame()])
    result = locate_negative_values(tmp_path / "synthetic.tar.gz", audit_report_path=tmp_path / "report.json",
                                     work_dir=tmp_path / "locate", report_path=tmp_path / "negative.json",
                                     records_path=tmp_path / "negative.parquet")
    assert result["status"] == "no_unknown_negative_values"
    assert result["unknown_negative_values"] == 0
    assert pd.read_parquet(tmp_path / "negative.parquet").empty
