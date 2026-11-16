import json
from collections import Counter
from pathlib import Path

from ptop.schema import FEATURES


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / "reports" / "local-data"
    archive = json.loads((folder / "archive-audit.json").read_text(encoding="utf-8"))
    negative = json.loads((folder / "negative-value-audit.json").read_text(encoding="utf-8"))
    preflight = json.loads((folder / "preprocessing-audit.json").read_text(encoding="utf-8"))
    windows = json.loads((folder / "window-verification.json").read_text(encoding="utf-8"))
    fields = {}
    for field in FEATURES:
        fields[field] = {key: sum(member["fields"][field][key] for member in archive["members"])
                         for key in ("null", "nan", "infinite", "unknown_negative", "zero", "sentinel_missing", "observed")}
    days, identifiers, minutes, relationships = set(), set(), Counter(), Counter()
    for member in archive["members"]:
        days.update(member["date_rows"])
        identifiers.update(member["instrument_rows"])
        minutes.update(member["minute_of_day_rows"])
        relationships.update(member["relationships"])
    comparison = {}
    for name, candidate in preflight["preprocessing"]["candidates"].items():
        comparison[name] = {
            "degenerate_fields": candidate["fit"]["degenerate_fields"],
            "zero_variance_fields": candidate["fit"]["zero_variance_fields"],
            "activation_abs_ge_0_99": {seed: measurement["overall"]["saturation_fractions"]["0.99"]
                                       for seed, measurement in candidate["activation"].items()},
            "activation_abs_ge_0_99_by_split": {
                seed: {split: group["saturation_fractions"]["0.99"]
                       for split, group in measurement["groups"]["fit_or_heldout"].items()}
                for seed, measurement in candidate["activation"].items()
            },
            "price_float32_collision_pairs": sum(field["float32_collision_pairs"]
                                                   for field in candidate["price_resolution"]["fields"].values()),
            "maximum_price_reconstruction_error": max(field["maximum_reconstruction_absolute_error"]
                                                        for field in candidate["price_resolution"]["fields"].values()),
            "state_unchanged": candidate["state_unchanged"],
            "model_checks": candidate["real_model_checks"],
        }
    summary = {
        "source": archive["source"], "source_status": archive["status"],
        "row_count": archive["totals"]["rows"], "members": archive["totals"]["feather_members"],
        "observed_date_min": min(days), "observed_date_max": max(days), "observed_date_count": len(days),
        "observed_instrument_id_count": len(identifiers), "observed_time_of_day_count": len(minutes),
        "schema_consistent": archive["schema_consistent"], "fields": fields,
        "cross_field_diagnostics": dict(relationships),
        "negative_values": {key: negative[key] for key in ("unknown_negative_values", "affected_bar_keys",
                            "affected_instruments", "affected_dates", "fields", "by_member")},
        "diagnostic_dates": {"fit": preflight["fit_dates"], "heldout": preflight["heldout_dates"]},
        "diagnostic_raw_rows": preflight["canonical_rows"], "diagnostic_fit_unique_rows": preflight["fit_referenced_unique_rows"],
        "window_scope": windows["scope"], "window_counts": windows["counts"],
        "window_reference_comparison": windows["reference_grid_comparison"],
        "normalization_comparison": comparison,
        "timing_seconds": {"full_archive": archive["elapsed_seconds"], "seven_day_preflight": preflight["elapsed_seconds"],
                           "reference_window_verification": windows["elapsed_seconds"]},
        "formal_training_eligible": False,
        "remaining_inputs": preflight["blocking_formal_inputs"],
        "interpretation": {
            "activation_denominator": "unique predictable raw rows times 64 channels; random initialization only",
            "window_denominator": "overlapping local audit window slots; not official coverage denominator",
            "price_group_comparison": "fit/heldout scale reports use their own close medians; activation groups use all seven days",
            "future_mutation_scope": "fixed transformed rows; preprocessor not refitted",
            "normalization_selection": "review scale, price resolution and actual activation diagnostics before choosing a formal candidate",
            "negative_values": "source definition or corrected source required; no deletion, zero filling, or unsigned conversion",
        },
    }
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"rows": summary["row_count"], "negative_cells": negative["unknown_negative_values"],
                      "windows": windows["counts"]["samples"], "normalization": {
                          name: values["activation_abs_ge_0_99"] for name, values in comparison.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
