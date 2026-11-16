import json

import numpy as np
import pandas as pd
import pytest
import torch

from ptop.encoders import ALSTMEncoder, RawEncoder
from ptop.models import R1Model
from ptop.preprocessing import FrozenPreprocessor
from ptop.preprocessing_audit import (
    DiagnosticPreprocessor,
    activation_diagnostics,
    audit_row_groups,
    fit_diagnostic_candidates,
    scale_resolution,
)
from ptop.schema import FEATURES, PRICE_FIELDS, ContractError


@pytest.fixture
def audit_values():
    minutes = pd.date_range("2026-09-01 09:31", periods=8, freq="min").append(
        pd.date_range("2026-09-02 09:31", periods=8, freq="min")
    )
    index = pd.MultiIndex.from_product([minutes, [1, 2]], names=["datetime", "instrument"])
    values = pd.DataFrame(
        np.random.default_rng(101).uniform(10, 100, (len(index), len(FEATURES))),
        index=index, columns=FEATURES,
    )
    values.iloc[3, 0] = np.nan
    values.iloc[16:] += 200.0
    return values, values.notna()


def fit_candidates(values, observed, **kwargs):
    return fit_diagnostic_candidates(
        values, observed, referenced_rows=values.index[:12].append(values.index[:6]),
        fit_start="2026-09-01", fit_end="2026-09-01",
        heldout_start="2026-09-02", heldout_end="2026-09-02", **kwargs,
    )


def test_diagnostic_fit_uses_official_statistics_and_unique_references(audit_values):
    values, observed = audit_values
    before = values.copy(deep=True)
    processors, report = fit_candidates(values, observed, modes=("N0", "N1", "N2"))
    for name, processor in processors.items():
        official = FrozenPreprocessor(name, n2_base="N1").fit(
            values, observed, referenced_rows=values.index[:12], fit_start="2026-09-01", fit_end="2026-09-01",
        )
        assert processor._numeric_state() == official._numeric_state()
        pd.testing.assert_frame_equal(processor._transform(values, observed), official._transform(values, observed))
        assert report["candidates"][name]["fit_row_count"] == 12
        assert report["candidates"][name]["heldout"]["row_count"] == 16
        assert report["candidates"][name]["fit"]["fields"]["open"]["valid_count"] == 11
        assert not report["candidates"][name]["formal_training_eligible"]
    pd.testing.assert_frame_equal(values, before)
    assert report["status"] == "diagnostic_only"
    json.dumps(report, allow_nan=False)


def test_diagnostic_state_cannot_be_formal_frozen_artifact(audit_values, tmp_path):
    processors, report = fit_candidates(*audit_values)
    for processor in processors.values():
        with pytest.raises(ContractError, match="diagnostic_only"):
            processor.freeze(scale_review="local-real-data-audit")
        with pytest.raises(ContractError, match="diagnostic_only"):
            processor.state_dict()
        with pytest.raises(ContractError, match="diagnostic_only"):
            processor.save(tmp_path / "preprocessor.json")
    with pytest.raises(ContractError):
        FrozenPreprocessor.from_state_dict(report)


def test_degenerate_mad_and_constant_drift_remain_visible(audit_values):
    values, observed = audit_values
    values.loc[:, "deal_number"] = 5.0
    values.iloc[16:, FEATURES.index("deal_number")] = 8.0
    processors, report = fit_candidates(values, observed)
    assert "deal_number" in processors["N0"].degenerate_fields
    assert not report["candidates"]["N0"]["numerically_nondegenerate"]
    n1 = report["candidates"]["N1"]
    assert n1["fit"]["fields"]["deal_number"]["zero_variance_training"]
    assert n1["heldout"]["fields"]["deal_number"]["training_constant_changed"]
    assert (processors["N1"]._transform(values, observed).iloc[16:]["deal_number"] == 8).all()


def test_dates_and_required_data_fail_fast(audit_values):
    values, observed = audit_values
    with pytest.raises(ContractError, match="晚于"):
        fit_diagnostic_candidates(
            values, observed, referenced_rows=values.index,
            fit_start="2026-09-01", fit_end="2026-09-02", heldout_start="2026-09-02", heldout_end="2026-09-02",
        )
    with pytest.raises(ContractError, match="没有原始行"):
        fit_diagnostic_candidates(
            values, observed, referenced_rows=values.index,
            fit_start="2026-09-01", fit_end="2026-09-01", heldout_start="2026-09-03", heldout_end="2026-09-03",
        )
    empty = values.copy()
    empty.iloc[:16, 0] = np.nan
    with pytest.raises(ContractError, match="没有有效观测"):
        fit_candidates(empty, empty.notna())


def test_scale_resolution_counts_only_observed_consecutive_minutes(audit_values):
    values, observed = audit_values
    processors, _ = fit_candidates(values, observed)
    report = scale_resolution(processors["N1"], values.iloc[::-1], observed.iloc[::-1])
    assert report["fields"]["close"]["adjacent_observed_pairs"] == 28
    assert report["fields"]["open"]["adjacent_observed_pairs"] == 26
    assert report["fields"]["close"]["float32_collision_pairs"] == 0
    assert report["fields"]["close"]["maximum_step_relative_error"] < 1e-3
    json.dumps(report, allow_nan=False)


def test_scale_resolution_detects_float32_price_collisions(audit_values):
    values, observed = audit_values
    values.loc[:, list(PRICE_FIELDS)] *= 1e12
    processor = DiagnosticPreprocessor("N1").fit(
        values, observed, referenced_rows=values.index[:16], fit_start="2026-09-01", fit_end="2026-09-01",
    )
    tiny = values.iloc[16:20].copy()
    for field in PRICE_FIELDS:
        tiny.loc[:, field] = np.array([100.0, 100.0, 100.000001, 100.000001])
    report = scale_resolution(processor, tiny, tiny.notna())
    for field in PRICE_FIELDS:
        assert report["fields"][field]["nonzero_raw_step_pairs"] == 2
        assert report["fields"][field]["float32_collision_pairs"] == 2
        assert report["fields"][field]["float32_collision_fraction"] == 1.0


def test_activation_measures_actual_projection_excludes_padding_and_restores_modes():
    encoder = ALSTMEncoder()
    encoder.train()
    encoder.net[1].eval()
    with torch.no_grad():
        encoder.net[0].weight.zero_()
        encoder.net[0].bias.fill_(5.0)
    x = torch.zeros(2, 3, len(FEATURES))
    step_valid = torch.tensor([[False, True, True], [True, True, True]])
    observed = step_valid.unsqueeze(-1).expand_as(x).clone()
    observed[1, 1] = False
    report = activation_diagnostics(
        encoder, x, observed, step_valid,
        row_groups={"sample": np.array([["a"] * 3, ["b"] * 3])}, batch_size=1,
    )
    assert report["overall"]["valid_step_count"] == 5
    assert report["overall"]["activation_element_count"] == 5 * 64
    assert report["overall"]["fully_missing_valid_steps"] == 1
    assert report["overall"]["pre"]["mean"] == 5.0
    assert report["overall"]["saturation_fractions"]["0.99"] == 1.0
    assert report["groups"]["sample"]["a"]["valid_step_count"] == 2
    assert encoder.training and not encoder.net[1].training
    assert not encoder.net[1]._forward_hooks
    json.dumps(report, allow_nan=False)


def test_activation_full_model_and_chunked_summaries_match_actual_torch():
    torch.manual_seed(17)
    model = R1Model()
    x = torch.randn(9, 4, len(FEATURES)) * 4
    observed = torch.ones_like(x, dtype=torch.bool)
    valid = torch.ones(x.shape[:2], dtype=torch.bool)
    report = activation_diagnostics(model, x, observed, valid, batch_size=2)
    prepared = model.encoder.prepare(x, observed, valid)
    pre = model.encoder.net[0](prepared)
    post = model.encoder.net[1](pre)
    expected = float((post.abs() >= 0.99).sum()) / post.numel()
    assert report["overall"]["saturation_fractions"]["0.99"] == expected
    assert report["overall"]["pre"]["mean"] == pytest.approx(float(pre.detach().double().mean()), abs=1e-7)
    assert sum(report["overall"]["pre"]["histogram_counts"]) == pre.numel()
    assert sum(report["overall"]["post"]["histogram_counts"]) == post.numel()


def test_activation_errors_restore_hooks_and_reject_invalid_structure():
    x = torch.ones(1, 2, len(FEATURES))
    observed = torch.ones_like(x, dtype=torch.bool)
    valid = torch.ones(x.shape[:2], dtype=torch.bool)
    with pytest.raises(ContractError, match="ALSTMEncoder"):
        activation_diagnostics(RawEncoder(), x, observed, valid)
    encoder = ALSTMEncoder()
    with torch.no_grad():
        encoder.net[0].weight.fill_(torch.inf)
    with pytest.raises(ContractError, match="非有限"):
        activation_diagnostics(encoder, x, observed, valid)
    assert not encoder.net[1]._forward_hooks
    assert encoder.training


def test_audit_groups_preserve_all_rows(audit_values):
    values, _ = audit_values
    groups = audit_row_groups(values)
    assert all(len(group) == len(values) for group in groups.values())
    assert set(groups["intraday_hour"]) == {"09:00"}
