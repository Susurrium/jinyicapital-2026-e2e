from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc
import pyarrow.parquet as parquet

from .schema import BOOK_PRICE_FIELDS, FEATURES, OHLC_FIELDS, SCALE_FIELDS, ContractError


class _HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        value = self.stream.read(size)
        self.digest.update(value)
        return value


def _counter_dict(counter):
    return {str(key): int(value) for key, value in sorted(counter.items())}


def _selected_rows(path: Path, indices: np.ndarray) -> pd.DataFrame:
    pieces = []
    start = 0
    with pa.memory_map(str(path), "r") as handle:
        reader = ipc.open_file(handle)
        for number in range(reader.num_record_batches):
            batch = reader.get_batch(number)
            selected = indices[(indices >= start) & (indices < start + batch.num_rows)]
            if len(selected):
                pieces.append(batch.take(pa.array(selected - start)).to_pandas())
            start += batch.num_rows
    if not pieces:
        raise ContractError("重复键定位未找到原始记录")
    return pd.concat(pieces, ignore_index=True)


def _duplicate_summary(frame: pd.DataFrame) -> dict:
    unique = frame.drop_duplicates()
    keys = ["date", "instrument_id"]
    conflicts = unique.duplicated(keys, keep=False)
    return {
        "duplicate_extra_rows": int(len(frame) - len(frame.drop_duplicates(keys))),
        "identical_extra_rows": int(len(frame) - len(unique)),
        "conflicting_keys": int(len(unique.loc[conflicts, keys].drop_duplicates())),
    }


@dataclass
class MemberAudit:
    report: dict
    keys_path: Path
    archive_name: str
    retained_path: Path | None


def audit_feather(path: Path, *, keys_path: Path) -> dict:
    fields = {
        name: {"null": 0, "nan": 0, "infinite": 0, "negative": 0, "unknown_negative": 0,
               "zero": 0, "sentinel_missing": 0, "observed": 0, "fractional": 0,
               "raw_min": None, "raw_max": None}
        for name in FEATURES
    }
    days, minutes, instruments, relationships = Counter(), Counter(), Counter(), Counter()
    daily_ids = {}
    key_parts = []
    rows = 0
    time_invalid = 0
    time_null = 0
    id_null = 0
    date_min = date_max = None
    metadata_stats = {"adjust_factor_null": 0, "adjust_factor_nonfinite": 0, "adjust_factor_nonpositive": 0}
    with pa.memory_map(str(path), "r") as handle:
        reader = ipc.open_file(handle)
        schema = reader.schema
        missing = sorted(set(("date", "instrument_id") + FEATURES).difference(schema.names))
        if missing:
            raise ContractError(f"归档成员缺少必要字段：{missing}")
        if len(set(schema.names)) != len(schema.names):
            raise ContractError("归档成员字段名存在重复")
        if not pa.types.is_timestamp(schema.field("date").type):
            raise ContractError("归档 date 必须为明确单位的 Arrow timestamp")
        if not pa.types.is_integer(schema.field("instrument_id").type):
            raise ContractError("归档 instrument_id 必须为整数")
        for name in FEATURES:
            kind = schema.field(name).type
            if not (pa.types.is_integer(kind) or pa.types.is_floating(kind)):
                raise ContractError(f"归档数值字段类型不合法：{name}")
        for index in range(reader.num_record_batches):
            batch = reader.get_batch(index)
            frame = batch.to_pandas()
            rows += len(frame)
            dates = pd.DatetimeIndex(frame["date"])
            if dates.tz is not None:
                dates = dates.tz_convert("Asia/Shanghai").tz_localize(None)
            valid_dates = dates[~dates.isna()]
            time_null += int(dates.isna().sum())
            id_null += int(frame["instrument_id"].isna().sum())
            time_invalid += int((valid_dates != valid_dates.floor("min")).sum())
            if len(valid_dates):
                batch_min, batch_max = valid_dates.min(), valid_dates.max()
                date_min = batch_min if date_min is None else min(date_min, batch_min)
                date_max = batch_max if date_max is None else max(date_max, batch_max)
                day_counts = pd.Series(valid_dates.normalize()).value_counts()
                days.update({day.strftime("%Y-%m-%d"): int(count) for day, count in day_counts.items()})
                second_counts = pd.Series(valid_dates.hour * 3600 + valid_dates.minute * 60 + valid_dates.second).value_counts()
                minutes.update({f"{second // 3600:02d}:{second // 60 % 60:02d}:{second % 60:02d}": int(count) for second, count in second_counts.items()})
            instruments.update(frame["instrument_id"].dropna().value_counts().to_dict())
            for day, group in frame.assign(_day=dates.normalize()).groupby("_day"):
                daily_ids.setdefault(day.strftime("%Y-%m-%d"), set()).update(group["instrument_id"].dropna().unique().astype(int))
            if dates.isna().any() or frame["instrument_id"].isna().any():
                raise ContractError("归档键有缺失；无法继续执行唯一性审计")
            key_parts.append(pa.table({"date": pa.array(dates), "instrument_id": batch.column("instrument_id")}))
            values = {}
            valid = {}
            for name in FEATURES:
                array = frame[name].to_numpy(dtype=np.float64, na_value=np.nan)
                values[name] = array
                stats = fields[name]
                finite = np.isfinite(array)
                null_count = batch.column(name).null_count
                missing_sentinel = (array == -1) if name in OHLC_FIELDS else ((array == 0) if name in BOOK_PRICE_FIELDS else np.zeros(len(array), bool))
                integer_value = np.zeros(len(array), dtype=bool)
                integer_value[finite] = array[finite] == np.floor(array[finite])
                observed = finite & ~missing_sentinel & (array >= 0) & integer_value
                valid[name] = observed
                stats["null"] += int(null_count)
                stats["nan"] += int(np.isnan(array).sum()) - int(null_count)
                stats["infinite"] += int(np.isinf(array).sum())
                stats["negative"] += int((array < 0).sum())
                stats["unknown_negative"] += int(((array < 0) & ~missing_sentinel).sum())
                stats["zero"] += int((array == 0).sum())
                stats["sentinel_missing"] += int(missing_sentinel.sum())
                stats["observed"] += int(observed.sum())
                stats["fractional"] += int((array[finite] != np.floor(array[finite])).sum())
                if finite.any():
                    minimum, maximum = float(array[finite].min()), float(array[finite].max())
                    stats["raw_min"] = minimum if stats["raw_min"] is None else min(stats["raw_min"], minimum)
                    stats["raw_max"] = maximum if stats["raw_max"] is None else max(stats["raw_max"], maximum)
            ohlc_ok = np.logical_and.reduce([valid[name] for name in OHLC_FIELDS])
            relationships["ohlc_comparable_rows"] += int(ohlc_ok.sum())
            relationships["high_below_low"] += int((ohlc_ok & (values["high"] < values["low"])).sum())
            relationships["open_outside_low_high"] += int((ohlc_ok & ((values["open"] < values["low"]) | (values["open"] > values["high"]))).sum())
            relationships["close_outside_low_high"] += int((ohlc_ok & ((values["close"] < values["low"]) | (values["close"] > values["high"]))).sum())
            top_ok = valid["bid_price1"] & valid["ask_price1"]
            relationships["top_book_comparable_rows"] += int(top_ok.sum())
            relationships["crossed_top_book"] += int((top_ok & (values["bid_price1"] > values["ask_price1"])).sum())
            relationships["locked_top_book"] += int((top_ok & (values["bid_price1"] == values["ask_price1"])).sum())
            for side in ("bid", "ask"):
                for level in (1, 2, 3):
                    missing_price = values[f"{side}_price{level}"] == 0
                    for suffix in ("volume", "num_orders"):
                        quantity = values[f"{side}_{suffix}{level}"]
                        relationships[f"{side}{level}_missing_price_{suffix}_positive"] += int((missing_price & (quantity > 0)).sum())
                        relationships[f"{side}{level}_missing_price_{suffix}_zero"] += int((missing_price & (quantity == 0)).sum())
                    if level < 3:
                        left, right = f"{side}_price{level}", f"{side}_price{level + 1}"
                        compare = valid[left] & valid[right]
                        violation = values[left] < values[right] if side == "bid" else values[left] > values[right]
                        relationships[f"{side}_levels_{level}_{level + 1}_comparable"] += int(compare.sum())
                        relationships[f"{side}_levels_{level}_{level + 1}_inverted"] += int((compare & violation).sum())
            if "adjust_factor" in frame:
                factors = frame["adjust_factor"].to_numpy(dtype=float)
                metadata_stats["adjust_factor_null"] += int(batch.column("adjust_factor").null_count)
                metadata_stats["adjust_factor_nonfinite"] += int((~np.isfinite(factors)).sum())
                metadata_stats["adjust_factor_nonpositive"] += int((factors <= 0).sum())
        keys = pa.concat_tables(key_parts) if key_parts else pa.table({"date": pa.array([], type=pa.timestamp("ns")), "instrument_id": pa.array([], type=schema.field("instrument_id").type)})
        keys_path.parent.mkdir(parents=True, exist_ok=True)
        feather.write_feather(keys, keys_path, compression="lz4")
        key_frame = keys.to_pandas()
        duplicates = np.flatnonzero(key_frame.duplicated(["date", "instrument_id"], keep=False).to_numpy())
        duplicate_info = _duplicate_summary(_selected_rows(path, duplicates)) if len(duplicates) else {"duplicate_extra_rows": 0, "identical_extra_rows": 0, "conflicting_keys": 0}
        report = {
            "schema": [{"name": field.name, "type": str(field.type)} for field in schema],
            "rows": rows, "record_batches": reader.num_record_batches,
            "date_min": str(date_min) if date_min is not None else None,
            "date_max": str(date_max) if date_max is not None else None,
            "instrument_count": len(instruments), "date_count": len(days),
            "null_dates": time_null, "null_instrument_ids": id_null, "non_minute_timestamps": time_invalid,
            "duplicates": duplicate_info, "fields": fields, "relationships": _counter_dict(relationships),
            "date_rows": _counter_dict(days), "minute_of_day_rows": _counter_dict(minutes),
            "instrument_rows": _counter_dict(instruments),
            "date_instrument_counts": {day: len(ids) for day, ids in sorted(daily_ids.items())},
            "metadata": metadata_stats,
        }
    return report


def _extract_named(archive_path: Path, name: str, target: Path) -> Path:
    # 仅发现跨成员重复键时重新定位原始行，避免用哈希相同代替逐字段比较。
    with tarfile.open(archive_path, mode="r|gz") as archive:
        for member in archive:
            if member.name == name:
                with archive.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                return target
    raise ContractError("重复键复核无法找到此前归档成员")


def audit_archive(archive_path: Path, *, work_dir: Path, report_path: Path,
                  first_member_path: Path, progress: Callable[[dict], None] | None = None) -> dict:
    archive_path = archive_path.resolve()
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    first_member_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    audits = []
    inventory = []
    cross_duplicates = []
    key_cache = work_dir / "keys"
    key_cache.mkdir(exist_ok=True)
    source_stat = archive_path.stat()
    with archive_path.open("rb") as raw:
        hashing = _HashingReader(raw)
        with tarfile.open(fileobj=hashing, mode="r|gz") as archive:
            for member in archive:
                inventory.append({"name": member.name, "size": member.size, "kind": "file" if member.isfile() else "directory" if member.isdir() else "other"})
                if not member.isfile() or not member.name.endswith(".feather"):
                    continue
                number = len(audits)
                target = first_member_path if not audits else work_dir / f"member-{number:04d}.feather"
                if shutil.disk_usage(work_dir).free < member.size + 512 * 1024 * 1024:
                    raise ContractError("本地可用磁盘不足以容纳下一成员及审计余量")
                with archive.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                report = audit_feather(target, keys_path=key_cache / f"{number:04d}.feather")
                report["archive_member"] = member.name
                report["file_bytes"] = member.size
                current = MemberAudit(report, key_cache / f"{number:04d}.feather", member.name, target if not audits else None)
                for previous in audits:
                    left, right = previous.report, report
                    if not left["rows"] or not right["rows"]:
                        continue
                    if left["date_max"] < right["date_min"] or right["date_max"] < left["date_min"]:
                        continue
                    if set(left["instrument_rows"]).isdisjoint(right["instrument_rows"]):
                        continue
                    left_keys = feather.read_table(previous.keys_path).to_pandas().reset_index(names="_left_row")
                    right_keys = feather.read_table(current.keys_path).to_pandas().reset_index(names="_right_row")
                    overlap = left_keys.merge(right_keys, on=["date", "instrument_id"], how="inner")
                    if overlap.empty:
                        continue
                    previous_path = previous.retained_path or _extract_named(archive_path, previous.archive_name, work_dir / "duplicate-review.feather")
                    previous_rows = _selected_rows(previous_path, overlap["_left_row"].unique())
                    current_rows = _selected_rows(target, overlap["_right_row"].unique())
                    summary = _duplicate_summary(pd.concat([previous_rows, current_rows], ignore_index=True))
                    cross_duplicates.append({"left_member": previous.archive_name, "right_member": member.name, **summary})
                    if previous.retained_path is None:
                        previous_path.unlink()
                audits.append(current)
                if number:
                    target.unlink()
                if progress:
                    progress({"event": "member_complete", "member": member.name, "rows": report["rows"], "date_min": report["date_min"], "date_max": report["date_max"], "members_completed": len(audits), "elapsed_seconds": round(time.perf_counter() - started, 2)})
        while hashing.read(8 * 1024 * 1024):
            pass
    if archive_path.stat().st_size != source_stat.st_size or archive_path.stat().st_mtime_ns != source_stat.st_mtime_ns:
        raise ContractError("审计期间原始归档发生变化")
    if not audits:
        raise ContractError("归档没有 Feather 数据成员")
    totals = {"rows": sum(item.report["rows"] for item in audits), "feather_members": len(audits)}
    violations = {
        "unknown_negative_values": sum(value["unknown_negative"] for item in audits for value in item.report["fields"].values()),
        "infinite_values": sum(value["infinite"] for item in audits for value in item.report["fields"].values()),
        "fractional_local_values": sum(value["fractional"] for item in audits for value in item.report["fields"].values()),
        "non_minute_timestamps": sum(item.report["non_minute_timestamps"] for item in audits),
        "within_member_conflicting_keys": sum(item.report["duplicates"]["conflicting_keys"] for item in audits),
        "cross_member_conflicting_key_pairs": sum(item["conflicting_keys"] for item in cross_duplicates),
    }
    result = {
        "status": "source_contract_violations" if any(violations.values()) else "local_storage_checks_passed",
        "scope": "完整本地归档的存储及数值合同审计；不声明官方应预测覆盖率、授权训练区间或历史可见性已确认。",
        "source": {"path": str(archive_path), "bytes": source_stat.st_size, "sha256": hashing.digest.hexdigest()},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "totals": totals, "violations": violations, "inventory": inventory,
        "schema_consistent": all(item.report["schema"] == audits[0].report["schema"] for item in audits),
        "observed_definition": "符合本地数值合同的非缺失观测：有限、非负、整数，且不是字段规定的缺失哨兵。未知负值和小数仍单独记录为合同失败，不修改原始数值。",
        "members": [item.report for item in audits], "cross_member_duplicates": cross_duplicates,
        "retained_first_member": str(first_member_path.resolve()),
        "retained_first_member_scope": "首个归档成员；日期及同月分片关系以完整 inventory 为准。",
        "unit_contract": {"price_and_amount_divisor": 100, "scaled_fields": list(SCALE_FIELDS), "quantity_divisor": 1},
        "unverified": ["官方 instrument 映射", "正式采样网格及历史股票池", "历史修订和可见时间", "训练日期和标签区间", "来源量化与云端重叠样本一致性"],
    }
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def locate_negative_values(archive_path: Path, *, audit_report_path: Path, work_dir: Path,
                           report_path: Path, records_path: Path) -> dict:
    baseline = json.loads(audit_report_path.read_text(encoding="utf-8"))
    targets = {
        member["archive_member"]: [name for name, stats in member["fields"].items() if stats["unknown_negative"]]
        for member in baseline["members"]
        if any(stats["unknown_negative"] for stats in member["fields"].values())
    }
    work_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.parent.mkdir(parents=True, exist_ok=True)
    pieces = []
    started = time.perf_counter()
    with archive_path.open("rb") as raw:
        hashing = _HashingReader(raw)
        with tarfile.open(fileobj=hashing, mode="r|gz") as archive:
            for member in archive:
                if member.name not in targets:
                    continue
                target = work_dir / "negative-review.feather"
                if shutil.disk_usage(work_dir).free < member.size + 512 * 1024 * 1024:
                    raise ContractError("本地磁盘不足以定位异常成员")
                with archive.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
                with pa.memory_map(str(target), "r") as handle:
                    reader = ipc.open_file(handle)
                    for number in range(reader.num_record_batches):
                        batch = reader.get_batch(number)
                        for name in targets[member.name]:
                            values = batch.column(name).to_numpy(zero_copy_only=False)
                            selected = (values < 0) & (values != -1 if name in OHLC_FIELDS else True)
                            indices = np.flatnonzero(selected)
                            if len(indices):
                                pieces.append(pa.table({
                                    "archive_member": pa.array([member.name] * len(indices)),
                                    "date": batch.column("date").take(pa.array(indices)),
                                    "instrument_id": batch.column("instrument_id").take(pa.array(indices)),
                                    "field": pa.array([name] * len(indices)),
                                    "raw_value": pa.array(values[indices].astype(np.int64)),
                                }))
                target.unlink()
        while hashing.read(8 * 1024 * 1024):
            pass
    if hashing.digest.hexdigest() != baseline["source"]["sha256"]:
        raise ContractError("异常定位与完整审计的来源 SHA-256 不一致")
    records = pa.concat_tables(pieces) if pieces else pa.table({
        "archive_member": pa.array([], type=pa.string()), "date": pa.array([], type=pa.timestamp("ns")),
        "instrument_id": pa.array([], type=pa.int16()), "field": pa.array([], type=pa.string()),
        "raw_value": pa.array([], type=pa.int64()),
    })
    if records.num_rows != baseline["violations"]["unknown_negative_values"]:
        raise ContractError("异常定位数量与全量审计不一致")
    parquet.write_table(records, records_path, compression="zstd")
    frame = records.to_pandas()
    fields = {}
    for name, group in frame.groupby("field"):
        fields[name] = {
            "count": len(group), "negative_min": int(group["raw_value"].min()), "negative_max": int(group["raw_value"].max()),
            "instrument_count": int(group["instrument_id"].nunique()),
            "date_min": str(group["date"].min()), "date_max": str(group["date"].max()),
            "source_arrow_types": sorted({field["type"] for member in baseline["members"] for field in member["schema"] if field["name"] == name}),
        }
    result = {
        "status": "blocked_unknown_negative_values" if records.num_rows else "no_unknown_negative_values",
        "source_sha256": baseline["source"]["sha256"], "unknown_negative_values": records.num_rows,
        "affected_bar_keys": int(len(frame.drop_duplicates(["date", "instrument_id"]))),
        "affected_instruments": int(frame["instrument_id"].nunique()),
        "affected_dates": int(frame["date"].dt.normalize().nunique()),
        "fields": fields,
        "by_member": _counter_dict(Counter(frame["archive_member"].value_counts().to_dict())),
        "by_date": _counter_dict(Counter(frame["date"].dt.strftime("%Y-%m-%d").value_counts().to_dict())),
        "by_minute": _counter_dict(Counter(frame["date"].dt.strftime("%H:%M:%S").value_counts().to_dict())),
        "by_instrument": _counter_dict(Counter(frame["instrument_id"].value_counts().to_dict())),
        "records_path": str(records_path.resolve()), "elapsed_seconds": round(time.perf_counter() - started, 3),
        "interpretation": "负委托笔数违反当前本地数据合同；数值保持原样。官方含义或修复规则未确认，不能直接用于规范化或正式训练。盘口交叉、锁价与缺价但数量大于零分别保留为诊断统计，不据此更改行情。",
    }
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result
