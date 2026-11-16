import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.parquet as parquet


spec = importlib.util.spec_from_file_location("extract_negative_context", Path(__file__).parents[1] / "tools/extract_negative_context.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def test_context_uses_member_specific_ids_and_preserves_raw_dtype_and_values(tmp_path):
    source = pa.table({"date": pa.array([1, 2, 3], type=pa.timestamp("ns")),
                       "instrument_id": pa.array([1, 2, 1], type=pa.int16()),
                       "ask_num_orders1": pa.array([-32768, -33, 32767], type=pa.int16()),
                       "adjust_factor": pa.array([1, 2, 3], type=pa.float32())})
    archive_path = tmp_path / "source.tar.gz"
    source_path = tmp_path / "source.feather"
    feather.write_feather(source, source_path, chunksize=2)
    members = ["bars/202401.feather", "bars/202402.feather"]
    with tarfile.open(archive_path, "w:gz") as archive:
        for member in members:
            archive.add(source_path, arcname=member)
    records = pa.table({"archive_member": members,
                        "date": pa.array([1, 2], type=pa.timestamp("ns")),
                        "instrument_id": pa.array([1, 2], type=pa.int16()),
                        "field": ["ask_num_orders1"] * 2,
                        "raw_value": [-32768, -33]})
    records_path = tmp_path / "negative.parquet"
    parquet.write_table(records, records_path)
    baseline = {"source": {"bytes": archive_path.stat().st_size,
                           "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest()},
                "members": [{"archive_member": member, "rows": 3,
                             "schema": [{"name": field.name, "type": str(field.type)} for field in source.schema]}
                            for member in members]}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    output_path = tmp_path / "context.parquet"
    report = extract.extract_context(archive_path, records_path=records_path, baseline_path=baseline_path,
                                     work_dir=tmp_path / "work", output_path=output_path,
                                     report_path=tmp_path / "report.json")
    actual = parquet.read_table(output_path)
    assert actual["instrument_id"].to_pylist() == [1, 1, 2]
    assert actual["ask_num_orders1"].to_pylist() == [-32768, 32767, -33]
    assert actual.schema.field("ask_num_orders1").type == pa.int16()
    assert actual.schema.field("adjust_factor").type == pa.float32()
    assert report["verified_negative_records"] == 2
    assert report["source"]["matches_original_audit"]
    assert report["output"]["dtype_and_value_roundtrip"]
    assert list((tmp_path / "work").iterdir()) == []
