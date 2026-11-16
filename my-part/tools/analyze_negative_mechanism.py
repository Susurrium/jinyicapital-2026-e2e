import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ORDER_FIELDS = ("ask_num_orders1", "bid_num_orders1")
MODULUS = 65536
SIGNED_LIMIT = 32768
BOUNDARY_DISTANCE = 4096


def quantiles(values):
    values = np.asarray(values, dtype=np.float64)
    if not len(values):
        return None
    return {str(p): float(np.quantile(values, p)) for p in (0, 0.25, 0.5, 0.75, 0.95, 1)}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unsigned_candidate(values):
    values = np.asarray(values, dtype=np.int64)
    return np.where(values < 0, values + MODULUS, values)


def minimum_modular_delta(deltas):
    return (np.asarray(deltas, dtype=np.int64) + SIGNED_LIMIT) % MODULUS - SIGNED_LIMIT


def pair_summary(frame):
    if frame.empty:
        return {"pairs": 0}
    raw = frame["raw_delta"].abs()
    unsigned = frame["unsigned_candidate_delta"].abs()
    modular = frame["minimum_modular_delta"].abs()
    positive_volumes = frame["both_queue_volumes_positive"]
    volume_change = ((frame["volume"] - frame["previous_volume"]).abs() / frame["previous_volume"])[positive_volumes]
    return {
        "pairs": len(frame),
        "raw_absolute_delta": quantiles(raw),
        "unsigned_candidate_absolute_delta": quantiles(unsigned),
        "minimum_modular_absolute_delta": quantiles(modular),
        "unsigned_candidate_smaller_step_pairs": int((unsigned < raw).sum()),
        "unsigned_candidate_larger_step_pairs": int((unsigned > raw).sum()),
        "unsigned_candidate_step_over_32768_pairs": int((unsigned > SIGNED_LIMIT).sum()),
        "minimum_modular_step_at_most_4096_pairs": int((modular <= BOUNDARY_DISTANCE).sum()),
        "same_quote_price_pairs": int(frame["same_quote_price"].sum()),
        "both_queue_volumes_positive_pairs": int(positive_volumes.sum()),
        "absolute_queue_volume_relative_change_for_positive_volumes": quantiles(volume_change),
        "queue_volume_relative_change_at_most_five_percent_pairs": int((volume_change <= 0.05).sum()),
    }


def witnesses(frame, maximum=4):
    if frame.empty:
        return []
    selected = frame.assign(abs_modular=frame["minimum_modular_delta"].abs()).sort_values(
        ["abs_modular", "instrument_id", "date"]
    ).head(maximum)
    columns = [
        "instrument_id", "field", "previous_date", "date", "previous_value", "value",
        "raw_delta", "previous_unsigned_candidate", "unsigned_candidate",
        "unsigned_candidate_delta", "minimum_modular_delta", "previous_price", "price",
        "previous_volume", "volume", "same_quote_price",
    ]
    return json.loads(selected[columns].to_json(orient="records", date_format="iso"))


def negative_profile(negative):
    fields = {}
    for field, group in negative.groupby("field", sort=True):
        values = group["raw_value"].astype(np.int64)
        counts = values.value_counts()
        hist, edges = np.histogram(values, bins=np.arange(-32768, 1, 2048))
        fields[field] = {
            "cells": len(group), "unique_values": values.nunique(),
            "minimum": int(values.min()), "maximum": int(values.max()),
            "raw_quantiles": quantiles(values),
            "unsigned_candidate_quantiles": quantiles(unsigned_candidate(values)),
            "all_fit_signed_int16_range": bool(values.between(-32768, -1).all()),
            "most_frequent_values": [{"value": int(value), "count": int(count)} for value, count in counts.head(10).items()],
            "histogram": [{"lower_inclusive": int(lo), "upper_exclusive": int(hi), "cells": int(count)}
                          for lo, hi, count in zip(edges[:-1], edges[1:], hist)],
            "by_instrument": {str(key): int(value) for key, value in group.groupby("instrument_id").size().items()},
        }
    months = negative["date"].dt.strftime("%Y-%m").value_counts().sort_index()
    return {
        "cells": len(negative), "instruments": negative["instrument_id"].nunique(),
        "dates": negative["date"].dt.normalize().nunique(),
        "months": {str(key): int(value) for key, value in months.items()},
        "fields": fields,
    }


def build_pairs(context, field):
    side = field.split("_", 1)[0]
    ordered = context.sort_values(["instrument_id", "date"])
    current = ordered[["instrument_id", "date", field, f"{side}_price1", f"{side}_volume1"]].copy()
    current = current.rename(columns={field: "value", f"{side}_price1": "price", f"{side}_volume1": "volume"})
    current["value"] = current["value"].astype(np.int64)
    shifted = current.groupby("instrument_id", sort=False)[["date", "value", "price", "volume"]].shift()
    pairs = pd.concat([current, shifted.add_prefix("previous_")], axis=1)
    pairs = pairs[((pairs["date"] - pairs["previous_date"]) == pd.Timedelta(minutes=1)) &
                  (pairs["date"].dt.normalize() == pairs["previous_date"].dt.normalize())].copy()
    pairs["previous_value"] = pairs["previous_value"].astype(np.int64)
    pairs["field"] = field
    pairs["raw_delta"] = pairs["value"] - pairs["previous_value"]
    pairs["unsigned_candidate"] = unsigned_candidate(pairs["value"])
    pairs["previous_unsigned_candidate"] = unsigned_candidate(pairs["previous_value"])
    pairs["unsigned_candidate_delta"] = pairs["unsigned_candidate"] - pairs["previous_unsigned_candidate"]
    pairs["minimum_modular_delta"] = minimum_modular_delta(pairs["raw_delta"])
    pairs["same_quote_price"] = (pairs["price"] == pairs["previous_price"]) & (pairs["price"] > 0)
    pairs["both_queue_volumes_positive"] = (pairs["volume"] > 0) & (pairs["previous_volume"] > 0)
    return pairs


def context_profile(context, negative):
    if context.duplicated(["instrument_id", "date"]).any():
        raise ValueError("上下文存在重复 instrument_id/date，无法确定唯一相邻记录")
    if context[["instrument_id", "date", *ORDER_FIELDS]].isna().any().any():
        raise ValueError("上下文主键或委托笔数存在缺失值")
    observed_negative = []
    fields = {}
    for field in ORDER_FIELDS:
        subset = context.loc[context[field] < 0, ["instrument_id", "date", field]].rename(columns={field: "raw_value"})
        subset["field"] = field
        observed_negative.append(subset)
        pairs = build_pairs(context, field)
        touching = pairs[(pairs["value"] < 0) | (pairs["previous_value"] < 0)]
        sign_changes = touching[(touching["value"] < 0) != (touching["previous_value"] < 0)]
        same_price = sign_changes[sign_changes["same_quote_price"]]
        # 此分类只定位表示范围边界；不能据此将假设候选值作为正式数据。
        signed_boundary = sign_changes[
            ((sign_changes["value"] <= -SIGNED_LIMIT + BOUNDARY_DISTANCE) &
             (sign_changes["previous_value"] >= SIGNED_LIMIT - BOUNDARY_DISTANCE)) |
            ((sign_changes["previous_value"] <= -SIGNED_LIMIT + BOUNDARY_DISTANCE) &
             (sign_changes["value"] >= SIGNED_LIMIT - BOUNDARY_DISTANCE))
        ]
        zero_boundary = sign_changes[
            (sign_changes["value"].abs() <= BOUNDARY_DISTANCE) &
            (sign_changes["previous_value"].abs() <= BOUNDARY_DISTANCE)
        ]
        same_signed = signed_boundary[signed_boundary["same_quote_price"]]
        same_zero = zero_boundary[zero_boundary["same_quote_price"]]
        near_volume_zero = same_zero[same_zero["both_queue_volumes_positive"] &
                                    (((same_zero["volume"] - same_zero["previous_volume"]).abs() /
                                      same_zero["previous_volume"]) <= 0.05)]
        values = context[field]
        side = field.split("_", 1)[0]
        negative_rows = context[values < 0]
        candidate = unsigned_candidate(negative_rows[field])
        volume = negative_rows[f"{side}_volume1"].to_numpy(dtype=np.int64)
        fields[field] = {
            "context_minimum": int(values.min()), "context_maximum": int(values.max()),
            "all_values_within_signed_int16_range": bool(values.between(-32768, 32767).all()),
            "all_adjacent_one_minute_pairs": len(pairs),
            "pairs_touching_negative": pair_summary(touching),
            "all_sign_changes": pair_summary(sign_changes),
            "sign_changes_at_same_quote_price": pair_summary(same_price),
            "signed_boundary_sign_changes": pair_summary(signed_boundary),
            "signed_boundary_sign_changes_at_same_quote_price": pair_summary(same_signed),
            "zero_boundary_sign_changes": pair_summary(zero_boundary),
            "zero_boundary_sign_changes_at_same_quote_price": pair_summary(same_zero),
            "zero_boundary_sign_changes_at_same_quote_price_and_at_most_five_percent_volume_change": pair_summary(near_volume_zero),
            "witness_selection": "各类别按绝对最小模 65536 变化量、instrument_id、date 排序取前四条；类别统计包含全部相邻一分钟记录",
            "signed_boundary_same_price_witnesses": witnesses(same_signed),
            "zero_boundary_same_price_witnesses": witnesses(same_zero),
            "zero_boundary_same_price_and_stable_volume_witnesses": witnesses(near_volume_zero),
            "negative_row_volume_checks": {
                "rows": len(negative_rows), "strictly_positive_queue_volume_rows": int((volume > 0).sum()),
                "unsigned_candidate_at_most_raw_queue_volume_rows": int((candidate <= volume).sum()),
                "raw_queue_volume_divided_by_unsigned_candidate": quantiles(volume / candidate),
                "units_caveat": "只比较源文件原始数值；委托量字段单位和每笔数量约束必须依据正式字段定义确认",
            },
        }
    observed = pd.concat(observed_negative, ignore_index=True)
    columns = ["instrument_id", "date", "field", "raw_value"]
    left = negative[columns].sort_values(columns).reset_index(drop=True)
    right = observed[columns].sort_values(columns).reset_index(drop=True)
    if len(left) != len(right) or not (left == right).all().all():
        raise ValueError("上下文中的全部负值与原始负值定位记录不一致")
    return {
        "rows": len(context), "instruments": context["instrument_id"].nunique(),
        "dates": context["date"].dt.normalize().nunique(),
        "negative_locator_matches_context_exactly": True, "fields": fields,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative", type=Path, default=Path("work/local_archive/unknown-negative-records.parquet"))
    parser.add_argument("--context", type=Path, default=Path("work/negative-cause/context-1m.parquet"))
    parser.add_argument("--output", type=Path, default=Path("reports/local-data/negative-mechanism.json"))
    args = parser.parse_args()
    negative = pd.read_parquet(args.negative)
    context = pd.read_parquet(args.context)
    report = {
        "status": "diagnostic_evidence_only",
        "scope": "全部已定位负值及全部受影响 instrument-month 的同日连续一分钟变化；保留原始值",
        "input_files": {
            "negative": {"path": str(args.negative), "sha256": file_hash(args.negative)},
            "context": {"path": str(args.context), "sha256": file_hash(args.context)},
        },
        "hypothesis": {
            "unsigned_candidate": "仅对负值计算 raw + 65536，用于检验 int16 表示假设",
            "minimum_modular_delta": "((current - previous + 32768) % 65536) - 32768",
            "boundary_distance": BOUNDARY_DISTANCE,
            "minimum_modular_delta_assumption": "真实每分钟净变化绝对值小于 32768 时，最小模差才等于真实变化；当前缺少该保证",
            "ambiguity": "多个非负整数可映射到同一 int16 值；该诊断不能确认转换发生位置或保证 raw + 65536 可还原真实笔数",
        },
        "negative_profile": negative_profile(negative),
        "context_profile": context_profile(context, negative),
        "production_data_changed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "negative_cells": report["negative_profile"]["cells"],
                      "context_rows": report["context_profile"]["rows"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
