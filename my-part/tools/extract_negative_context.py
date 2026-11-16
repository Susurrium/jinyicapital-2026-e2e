import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as parquet

from ptop.local_archive import _HashingReader
from ptop.schema import ContractError


def negative_member_ids(records: pa.Table) -> dict[str, set[int]]:
    required = {"archive_member", "instrument_id", "date", "field", "raw_value"}
    if not required.issubset(records.column_names) or not records.num_rows:
        raise ContractError("异常记录缺少必要字段或为空")
    if any(records[name].null_count for name in required):
        raise ContractError("异常记录含缺失键或数值")
    targets = {}
    for member, instrument in zip(records["archive_member"].to_pylist(), records["instrument_id"].to_pylist()):
        targets.setdefault(member, set()).add(instrument)
    return targets


def select_context(path: Path, instrument_ids: set[int]) -> pa.Table:
    pieces = []
    with pa.memory_map(str(path), "r") as handle:
        reader = ipc.open_file(handle)
        schema = reader.schema
        values = pa.array(sorted(instrument_ids), type=schema.field("instrument_id").type)
        for index in range(reader.num_record_batches):
            batch = reader.get_batch(index)
            selected = batch.filter(pc.is_in(batch.column("instrument_id"), value_set=values))
            if selected.num_rows:
                pieces.append(selected)
        result = pa.Table.from_batches(pieces, schema=schema)
    found = set(result["instrument_id"].to_pylist())
    if found != instrument_ids:
        raise ContractError("源成员没有包含全部待检查 instrument_id")
    return result


def verify_negative_records(context: pa.Table, records: pa.Table) -> int:
    frame = context.to_pandas()
    keys = ["archive_member", "date", "instrument_id"]
    if frame.duplicated(keys).any():
        raise ContractError("提取上下文存在重复行情键")
    frame = frame.set_index(keys)
    verified = 0
    for row in records.to_pylist():
        value = frame.loc[(row["archive_member"], row["date"], row["instrument_id"]), row["field"]]
        if value != row["raw_value"]:
            raise ContractError("提取上下文与既有异常记录的原值不一致")
        verified += 1
    return verified


def extract_context(archive_path: Path, *, records_path: Path, baseline_path: Path,
                    work_dir: Path, output_path: Path, report_path: Path,
                    progress=None) -> dict:
    started = time.perf_counter()
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    records = parquet.read_table(records_path)
    targets = negative_member_ids(records)
    source_stat = archive_path.stat()
    if source_stat.st_size != baseline["source"]["bytes"]:
        raise ContractError("源归档大小与原始验收不一致")
    for path in (output_path, report_path):
        if path.exists():
            raise FileExistsError(f"目标已存在，拒绝覆盖：{path}")
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    pieces = []
    member_stats = []
    seen = set()
    with archive_path.open("rb") as raw:
        hashing = _HashingReader(raw)
        with tarfile.open(fileobj=hashing, mode="r|gz") as archive:
            for member in archive:
                if member.name not in targets:
                    continue
                if not member.isfile() or member.name in seen:
                    raise ContractError("待提取成员类型错误或重复")
                seen.add(member.name)
                temporary_path = work_dir / f"context-member-{len(seen):04d}.feather"
                if shutil.disk_usage(work_dir).free < member.size + 512 * 1024 * 1024:
                    raise ContractError("可用磁盘不足以提取当前源成员")
                with temporary_path.open("xb") as output:
                    try:
                        with archive.extractfile(member) as source:
                            shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                    except BaseException:
                        output.close()
                        temporary_path.unlink()
                        raise
                try:
                    table = select_context(temporary_path, targets[member.name])
                finally:
                    temporary_path.unlink()
                original_schema = [{"name": field.name, "type": str(field.type)} for field in table.schema]
                audited = next(item for item in baseline["members"] if item["archive_member"] == member.name)
                if original_schema != audited["schema"]:
                    raise ContractError("提取源类型与原始验收不一致")
                table = table.append_column("archive_member", pa.array([member.name] * table.num_rows))
                pieces.append(table)
                stats = {"archive_member": member.name, "source_rows": audited["rows"],
                         "context_rows": table.num_rows, "instrument_ids": sorted(targets[member.name]),
                         "date_min": str(pc.min(table["date"]).as_py()),
                         "date_max": str(pc.max(table["date"]).as_py()),
                         "source_schema": original_schema}
                member_stats.append(stats)
                if progress:
                    progress({"event": "context_member_complete", "member": member.name,
                              "rows": table.num_rows, "instruments": len(targets[member.name]),
                              "members_completed": len(seen)})
        while hashing.read(8 * 1024 * 1024):
            pass
    if seen != set(targets):
        raise ContractError("源归档缺少异常记录对应成员")
    after = archive_path.stat()
    if (after.st_size, after.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
        raise ContractError("提取期间源归档发生变化")
    source_hash = hashing.digest.hexdigest()
    if source_hash != baseline["source"]["sha256"]:
        raise ContractError("上下文源 SHA-256 与原始验收不一致")
    context = pa.concat_tables(pieces)
    verified = verify_negative_records(context, records)
    parquet.write_table(context, output_path, compression="zstd")
    reloaded = parquet.read_table(output_path)
    if not reloaded.equals(context, check_metadata=True):
        raise ContractError("上下文 Parquet 重载值或类型不一致")
    with output_path.open("rb") as stream:
        output_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"status": "source_context_extracted_and_verified",
              "scope": "异常出现月份内当月受影响 ID 的完整月行情；原始数值和字段类型保持不变。",
              "source": {"path": str(archive_path.resolve()), "bytes": source_stat.st_size,
                         "sha256": source_hash, "matches_original_audit": True},
              "records_path": str(records_path.resolve()), "verified_negative_records": verified,
              "output": {"path": str(output_path.resolve()), "sha256": output_hash,
                         "bytes": output_path.stat().st_size, "rows": context.num_rows,
                         "original_columns": len(context.column_names) - 1,
                         "dtype_and_value_roundtrip": True},
              "members": member_stats, "elapsed_seconds": round(time.perf_counter() - started, 3)}
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description="提取负委托笔数对应 ID 的完整月行情上下文")
    parser.add_argument("--archive", type=Path, default=Path("data/cpt_jyc_2026_e2e_bar1m.tar.gz"))
    parser.add_argument("--records", type=Path, default=Path("work/local_archive/unknown-negative-records.parquet"))
    parser.add_argument("--baseline", type=Path, default=Path("reports/local-data/archive-audit.json"))
    parser.add_argument("--work-dir", type=Path, default=Path("work/negative-cause"))
    parser.add_argument("--output", type=Path, default=Path("work/negative-cause/context-1m.parquet"))
    parser.add_argument("--report", type=Path, default=Path("reports/local-data/negative-cause-source.json"))
    args = parser.parse_args()
    result = extract_context(args.archive, records_path=args.records, baseline_path=args.baseline,
                             work_dir=args.work_dir, output_path=args.output, report_path=args.report,
                             progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    print(json.dumps({"status": result["status"], "output": result["output"],
                      "verified_negative_records": result["verified_negative_records"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
