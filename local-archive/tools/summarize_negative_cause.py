import json
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    root = Path(__file__).resolve().parents[1]
    report_dir = root / "reports/local-data"
    context = pd.read_parquet(root / "work/negative-cause/context-1m.parquet")
    mechanism = json.loads((report_dir / "negative-mechanism.json").read_text(encoding="utf-8"))
    frequencies = json.loads((report_dir / "negative-cross-frequency.json").read_text(encoding="utf-8"))
    source = json.loads((report_dir / "negative-cause-source.json").read_text(encoding="utf-8"))
    if source["output"]["sha256"] != mechanism["input_files"]["context"]["sha256"]:
        raise ValueError("上下文来源指纹不一致")
    fields = {}
    for side, opposite in (("bid", "ask"), ("ask", "bid")):
        field = f"{side}_num_orders1"
        rows = context.loc[context[field] < 0]
        profile = mechanism["context_profile"]["fields"][field]
        fields[field] = {
            "negative_rows": len(rows),
            "same_side_price_positive": int(rows[f"{side}_price1"].gt(0).sum()),
            "same_side_volume_positive": int(rows[f"{side}_volume1"].gt(0).sum()),
            "opposite_price_missing": int(rows[f"{opposite}_price1"].eq(0).sum()),
            "same_side_raw_volume_quantiles": {
                str(q): float(rows[f"{side}_volume1"].quantile(q)) for q in (0, 0.25, 0.5, 0.75, 1)
            },
            "signed_boundary_pairs": profile["signed_boundary_sign_changes"]["pairs"],
            "signed_boundary_same_price_pairs": profile["signed_boundary_sign_changes_at_same_quote_price"]["pairs"],
            "signed_boundary_stable_volume_pairs": profile["signed_boundary_sign_changes_at_same_quote_price"][
                "queue_volume_relative_change_at_most_five_percent_pairs"],
            "zero_boundary_pairs": profile["zero_boundary_sign_changes"]["pairs"],
            "zero_boundary_same_price_stable_volume_pairs": profile[
                "zero_boundary_sign_changes_at_same_quote_price_and_at_most_five_percent_volume_change"]["pairs"],
        }
    # 用当前 NumPy 执行小整数边界示例；示例与真实原值分别保存。
    wide = np.array([32765, 32767, 32768, 32787, 32793, 65503, 65535, 65536, 65547], dtype=np.int32)
    narrow = wide.astype(np.int16)
    demonstration = [{"synthetic_int32": int(original), "numpy_int16_cast": int(converted)}
                     for original, converted in zip(wide, narrow, strict=True)]
    output = {
        "scope": "read-only cause investigation; no production correction",
        "original_archive_sha256": source["source"]["sha256"],
        "context_rows": source["output"]["rows"],
        "verified_negative_records": source["verified_negative_records"],
        "fields": fields,
        "cross_frequency": {name: {key: values[key] for key in ("matched_anomaly_keys", "same_raw_value", "different_raw_value")}
                            for name, values in frequencies["frequencies"].items()},
        "numpy_version": np.__version__, "synthetic_narrowing_demonstration": demonstration,
        "interpretation_limits": ["cloud int32 original values not obtained", "export transformation code not obtained",
                                  "multiple nonnegative counts have the same int16 representation", "book volume unit not inferred"],
    }
    (report_dir / "negative-cause-summary.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(json.dumps({"fields": fields, "cross_frequency": output["cross_frequency"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
