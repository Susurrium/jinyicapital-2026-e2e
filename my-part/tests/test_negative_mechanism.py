import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


spec = importlib.util.spec_from_file_location("negative_mechanism", Path(__file__).parents[1] / "tools" / "analyze_negative_mechanism.py")
mechanism = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mechanism)


def make_context():
    dates = pd.to_datetime(["2024-01-02 10:00", "2024-01-02 10:01", "2024-01-02 10:02", "2024-01-02 10:03", "2024-01-02 10:05"])
    return pd.DataFrame({
        "instrument_id": [1] * 5, "date": dates,
        "ask_num_orders1": [32765, -32766, -10, 20, -32700],
        "bid_num_orders1": [10] * 5,
        "ask_price1": [100] * 5, "bid_price1": [99] * 5,
        "ask_volume1": [1000000] * 5, "bid_volume1": [1000] * 5,
    })


def make_negative(context):
    result = context.loc[context["ask_num_orders1"] < 0, ["instrument_id", "date", "ask_num_orders1"]].rename(columns={"ask_num_orders1": "raw_value"})
    result["field"] = "ask_num_orders1"
    return result


def test_modular_values_retain_full_cycle_ambiguity():
    assert mechanism.unsigned_candidate([-32768, -1, 0, 32767]).tolist() == [32768, 65535, 0, 32767]
    assert mechanism.minimum_modular_delta([-65531, 30]).tolist() == [5, 30]


def test_context_checks_all_changes_excluding_nonadjacent_minutes():
    context = make_context()
    report = mechanism.context_profile(context, make_negative(context))
    ask = report["fields"]["ask_num_orders1"]
    assert report["negative_locator_matches_context_exactly"]
    assert ask["all_adjacent_one_minute_pairs"] == 3
    assert ask["all_sign_changes"]["pairs"] == 2
    assert ask["signed_boundary_sign_changes_at_same_quote_price"]["pairs"] == 1
    assert ask["zero_boundary_sign_changes_at_same_quote_price"]["pairs"] == 1
    zero = ask["zero_boundary_same_price_witnesses"][0]
    assert zero["unsigned_candidate_delta"] == -65506
    assert zero["minimum_modular_delta"] == 30


def test_negative_evidence_mismatch_fails():
    context = make_context()
    with pytest.raises(ValueError, match="不一致"):
        mechanism.context_profile(context, make_negative(context).iloc[:-1])


def test_duplicates_and_nulls_fail():
    context = make_context()
    with pytest.raises(ValueError, match="重复"):
        mechanism.context_profile(pd.concat([context, context.iloc[:1]]), make_negative(context))
    context.loc[0, "ask_num_orders1"] = np.nan
    with pytest.raises(ValueError, match="缺失"):
        mechanism.context_profile(context, make_negative(context))
