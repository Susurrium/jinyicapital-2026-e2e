import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import psutil
import torch

from .data import CanonicalData, normalize_local_bars
from .models import R1Model
from .preprocessing_audit import activation_diagnostics, audit_row_groups, fit_diagnostic_candidates, scale_resolution
from .schema import FEATURES, ContractError
from .windows import LocalAuditWindowDataset, fit_row_union


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def audit_endpoints(data: CanonicalData) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    # 观察到的分钟与当日出现的 ID 仅构成本地审计参考集合。
    rows = []
    grid = pd.DatetimeIndex(data.values.index.get_level_values("datetime").unique()).sort_values()
    dates = data.values.index.get_level_values("datetime").normalize()
    for day in grid.normalize().unique():
        times = grid[grid.normalize() == day]
        identifiers = data.values.index.get_level_values("instrument")[dates == day].unique().sort_values()
        gaps = np.flatnonzero(np.diff(times.asi8) > pd.Timedelta(minutes=1).value)
        positions = sorted({0, len(times) - 1, *range(29, len(times), 30), *gaps.tolist(), *(gaps + 1).tolist()})
        for position in positions:
            endpoint = times[position]
            decision = f"audit:{endpoint.isoformat()}"
            for identifier in identifiers:
                rows.append((f"{decision}:{identifier}", decision, int(identifier), endpoint))
    return pd.DataFrame(rows, columns=["sample_id", "decision_id", "instrument_id", "decision_time"]), grid


def window_diagnostics(dataset: LocalAuditWindowDataset, *, batch_size: int = 128) -> dict:
    counts = {"samples": 0, "structural_slots": 0, "real_slots": 0, "fully_missing_real_slots": 0,
              "observed_fields": 0, "unpredictable_samples": 0, "maximum_length": dataset.length}
    sections = []
    source_times = dataset.data.values.index.get_level_values("datetime").to_numpy(dtype="datetime64[ns]")
    source_ids = dataset.data.values.index.get_level_values("instrument").to_numpy()
    source_observed = dataset.data.observed.to_numpy()
    for decision, frame in dataset.expected.groupby("decision_id", sort=False):
        positions = frame.index.to_numpy()
        predicted = 0
        endpoint = frame.iloc[0]["decision_time"]
        day_grid = dataset._grids[endpoint.normalize()]
        history = day_grid[day_grid <= endpoint][-dataset.length:].to_numpy(dtype="datetime64[ns]")
        expected_times = np.full(dataset.length, np.datetime64("NaT"), dtype="datetime64[ns]")
        expected_times[-len(history):] = history
        expected_valid = ~np.isnat(expected_times)
        for start in range(0, len(positions), batch_size):
            batch = dataset.get_batch(positions[start:start + batch_size])
            np.testing.assert_array_equal(batch.step_valid, np.broadcast_to(expected_valid, batch.step_valid.shape))
            np.testing.assert_array_equal(batch.bar_times, np.broadcast_to(expected_times, batch.bar_times.shape))
            present = batch.row_positions >= 0
            ids = np.broadcast_to(batch.metadata["instrument_id"].to_numpy()[:, None], batch.step_valid.shape)
            keys = pd.MultiIndex.from_arrays([batch.bar_times[batch.step_valid], ids[batch.step_valid]],
                                             names=["datetime", "instrument"])
            reference_rows = dataset.data.values.index.get_indexer(keys)
            found = reference_rows >= 0
            reference_rows[found & (dataset._available_at[reference_rows.clip(min=0)] > endpoint.to_datetime64())] = -1
            np.testing.assert_array_equal(batch.row_positions[batch.step_valid], reference_rows)
            np.testing.assert_array_equal(source_times[batch.row_positions[present]], batch.bar_times[present])
            np.testing.assert_array_equal(source_ids[batch.row_positions[present]], ids[present])
            np.testing.assert_array_equal(source_observed[batch.row_positions[present]], batch.observed[present])
            if batch.observed[~present].any():
                raise ContractError("没有源记录的槽位出现有效观测")
            if (batch.observed & ~batch.step_valid[..., None]).any() or not np.isfinite(batch.x).all():
                raise ContractError("真实窗口的数值或掩码不满足合同")
            decision_times = batch.metadata["decision_time"].to_numpy(dtype="datetime64[ns]")
            if ((batch.bar_times > decision_times[:, None]) & batch.step_valid).any():
                raise ContractError("真实窗口引用未来 Bar")
            if ((batch.bar_times.astype("datetime64[D]") != decision_times.astype("datetime64[D]")[:, None])
                    & batch.step_valid).any():
                raise ContractError("真实窗口跨越日界线")
            counts["samples"] += len(batch.x)
            counts["structural_slots"] += int((~batch.step_valid).sum())
            counts["real_slots"] += int(batch.step_valid.sum())
            counts["fully_missing_real_slots"] += int((batch.step_valid & ~batch.observed.any(axis=-1)).sum())
            counts["observed_fields"] += int(batch.observed.sum())
            counts["unpredictable_samples"] += int((~batch.predictable).sum())
            predicted += int(batch.predictable.sum())
        sections.append({"decision_id": decision, "decision_time": frame.iloc[0]["decision_time"].isoformat(),
                         "reference_ids": len(frame), "predictable_ids": predicted,
                         "unpredictable_fraction": 1 - predicted / len(frame)})
    return {"scope": "observed local minutes and IDs; not official coverage denominator",
            "production_visibility_verified": False, "reference_grid_comparison": "passed",
            "source_key_and_observed_comparison": "passed", "counts": counts, "sections": sections}


def _real_model_checks(data: CanonicalData, endpoints: pd.DataFrame, grid: pd.DatetimeIndex, length: int) -> dict:
    windows = LocalAuditWindowDataset(data, endpoints, grid, length=length, bar_end_is_available=True)
    # 按全局均匀位置取真实样本，仅用于计算图和序列边界检查。
    indices = np.linspace(0, len(windows) - 1, min(64, len(windows)), dtype=np.int64)
    batch = windows.get_batch(indices)
    indices = indices[batch.predictable]
    if len(indices) < 2:
        raise ContractError("真实模型检查缺少至少两个可用审计窗口")
    batch = windows.get_batch(indices)
    tensors = tuple(torch.from_numpy(value) for value in (batch.x, batch.observed, batch.step_valid))
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(17)
        model = R1Model().eval()
    with torch.no_grad():
        combined, attention = model.forward_with_attention(*tensors)
        separate = torch.cat([model(*(value[i:i + 1] for value in tensors)) for i in range(len(indices))])
    torch.testing.assert_close(combined, separate, atol=1e-6, rtol=1e-5)
    if not torch.isfinite(combined).all() or attention[~tensors[2]].ne(0).any():
        raise ContractError("真实窗口预测有限性或注意力填充检查失败")
    torch.testing.assert_close(attention.sum(dim=1), torch.ones(len(indices)), atol=1e-6, rtol=1e-5)
    model.zero_grad(set_to_none=True)
    # 检查计算图，无目标标签、优化器或权重更新。
    model(*(value[:8] for value in tensors)).mean().backward()
    gradient_norms = {}
    for name, parameter in model.named_parameters():
        if parameter.grad is None or not torch.isfinite(parameter.grad).all():
            raise ContractError(f"真实输入的计算图梯度异常：{name}")
        gradient_norms[name] = float(parameter.grad.norm())
    earliest = batch.metadata["decision_time"].min()
    check_positions = indices[batch.metadata["decision_time"].eq(earliest).to_numpy()]
    modified_values = data.values.copy()
    future = modified_values.index.get_level_values("datetime") > earliest
    if not future.any():
        raise ContractError("真实未来扰动检查没有可改变的未来源行")
    modified_values.loc[future] *= -13
    modified = CanonicalData(modified_values, data.observed, data.metadata)
    changed = LocalAuditWindowDataset(modified, endpoints, grid, length=length, bar_end_is_available=True)
    before, after = windows.get_batch(check_positions), changed.get_batch(check_positions)
    np.testing.assert_array_equal(before.x, after.x)
    with torch.no_grad():
        before_scores = model(*(torch.from_numpy(value) for value in (before.x, before.observed, before.step_valid)))
        after_scores = model(*(torch.from_numpy(value) for value in (after.x, after.observed, after.step_valid)))
    torch.testing.assert_close(before_scores, after_scores, atol=0, rtol=0)
    return {"scope": "randomly initialized R1; no labels and no optimizer update", "samples": len(indices),
            "batch_invariance": "passed", "attention_mask": "passed", "gradient_finiteness": "passed",
            "future_bar_mutation": "passed", "future_rows_changed": int(future.sum()),
            "future_mutation_scope": "fixed transformed rows; preprocessor is not refitted",
            "gradient_norms": gradient_norms}


def run_local_preflight(feather_path, *, report_path, cache_directory, fit_days=5, heldout_days=2,
                        length=120, seeds=(17, 43, 101)) -> dict:
    for name, value in (("fit_days", fit_days), ("heldout_days", heldout_days), ("length", length)):
        if type(value) is not int or value <= 0:
            raise ContractError(f"{name} 必须为正整数")
    started = time.perf_counter()
    report_path, cache = Path(report_path), Path(cache_directory)
    cache.mkdir(parents=True, exist_ok=True)
    report = {"scope": "local_real_data_diagnostic_only", "formal_training_eligible": False,
              "source_file": str(Path(feather_path).resolve()), "fit_days_requested": fit_days,
              "heldout_days_requested": heldout_days, "window_length": length, "seeds": list(seeds),
              "fit_selection": "first observed data days in this member; next days held out; no label filtering",
              "blocking_formal_inputs": ["official_sampling_grid", "instrument_code_mapping", "target_support",
                                         "authorized_formal_training_dates"], "stages": {}}

    def checkpoint(name, **extra):
        report["stages"][name] = {"elapsed_seconds": time.perf_counter() - started,
                                  "resident_memory_bytes": psutil.Process().memory_info().rss, **extra}
        _write_json(cache / "progress.json", report)
        print(json.dumps({"stage": name, **report["stages"][name]}, ensure_ascii=False), flush=True)

    torch.set_num_threads(2)
    dataset = ds.dataset(str(feather_path), format="ipc")
    dates = pd.DatetimeIndex(dataset.to_table(columns=["date"]).column("date").to_pandas()).normalize().unique().sort_values()
    if len(dates) < fit_days + heldout_days:
        raise ContractError("源分区中的实际数据日不足以执行预登记的时间检查")
    selected_days = dates[:fit_days + heldout_days]
    with Path(feather_path).open("rb") as stream:
        report["source_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    report["fit_dates"] = [day.date().isoformat() for day in selected_days[:fit_days]]
    report["heldout_dates"] = [day.date().isoformat() for day in selected_days[fit_days:]]
    limit = selected_days[-1] + pd.Timedelta(days=1)
    table = dataset.to_table(filter=(ds.field("date") >= selected_days[0].to_pydatetime())
                            & (ds.field("date") < limit.to_pydatetime()))
    raw = table.to_pandas()
    del table
    canonical = normalize_local_bars(raw)
    report["raw_selected_rows"] = len(raw)
    del raw
    report["canonical_rows"] = len(canonical.values)
    report["duplicate_rows_removed"] = canonical.duplicate_rows
    report["instrument_ids"] = len(canonical.values.index.get_level_values("instrument").unique())
    checkpoint("normalized")
    endpoints, grid = audit_endpoints(canonical)
    windows = LocalAuditWindowDataset(canonical, endpoints, grid, length=length, bar_end_is_available=True)
    report["windows"] = window_diagnostics(windows)
    references = fit_row_union(windows, fit_start=selected_days[0], fit_end=selected_days[fit_days - 1])
    report["fit_referenced_unique_rows"] = len(references)
    endpoints.to_parquet(cache / "audit-endpoints.parquet", index=False)
    checkpoint("window_checks", samples=len(windows), fit_unique_rows=len(references))
    del windows
    processors, preprocessing = fit_diagnostic_candidates(
        canonical.values, canonical.observed, referenced_rows=references, fit_start=selected_days[0],
        fit_end=selected_days[fit_days - 1], heldout_start=selected_days[fit_days], heldout_end=selected_days[-1],
    )
    report["preprocessing"] = preprocessing
    checkpoint("preprocessing_fitted")
    groups = {name: labels[:, None] for name, labels in audit_row_groups(canonical.values).items()}
    days = canonical.values.index.get_level_values("datetime").normalize()
    groups["fit_or_heldout"] = np.where(days <= selected_days[fit_days - 1], "fit", "heldout")[:, None]
    groups["date"] = np.asarray(days.strftime("%Y-%m-%d"))[:, None]
    predictable_rows = canonical.observed.any(axis=1).to_numpy()
    flags = torch.from_numpy(canonical.observed.to_numpy()[predictable_rows, None, :].copy())
    valid = torch.ones((int(predictable_rows.sum()), 1), dtype=torch.bool)
    selected_groups = {name: labels[predictable_rows] for name, labels in groups.items()}
    for name, processor in processors.items():
        candidate = report["preprocessing"]["candidates"][name]
        before = processor._numeric_fingerprint()
        transformed = processor._transform(canonical.values, canonical.observed)
        candidate["price_resolution"] = scale_resolution(processor, canonical.values, canonical.observed)
        candidate["activation"] = {}
        numeric = torch.from_numpy(transformed.to_numpy()[predictable_rows, None, :].copy())
        for seed in seeds:
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(seed)
                model = R1Model().eval()
            candidate["activation"][str(seed)] = activation_diagnostics(
                model, numeric, flags, valid, row_groups=selected_groups, batch_size=8192,
            )
            checkpoint(f"{name}_activation_{seed}")
        del numeric
        if not processor.degenerate_fields:
            processed = CanonicalData(transformed, canonical.observed, canonical.metadata)
            candidate["real_model_checks"] = _real_model_checks(processed, endpoints, grid, length)
        else:
            candidate["real_model_checks"] = {"status": "not_run", "reason": "degenerate_MAD_rejects_candidate"}
        if processor._numeric_fingerprint() != before:
            raise ContractError("真实后段检查改变了预处理状态")
        candidate["state_unchanged"] = True
        _write_json(cache / f"{name}-diagnostic-statistics.json", {
            "purpose": "diagnostic_only_not_formal_training", "fields": list(FEATURES),
            "statistics": processor._numeric_state(), "fingerprint": before,
            "fit_dates": report["fit_dates"], "source_sha256": report["source_sha256"],
        })
        checkpoint(f"{name}_completed")
        del transformed
    report["unpredictable_raw_rows"] = int((~predictable_rows).sum())
    report["status"] = "completed_local_diagnostic"
    report["elapsed_seconds"] = time.perf_counter() - started
    _write_json(report_path, report)
    checkpoint("completed")
    return report


def verify_local_reference_windows(preflight_report, *, output_path) -> dict:
    report = json.loads(Path(preflight_report).read_text(encoding="utf-8"))
    source = Path(report["source_file"])
    started = time.perf_counter()
    with source.open("rb") as stream:
        actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual_hash != report["source_sha256"]:
        raise ContractError("真实窗口复查的源文件已经改变")
    start = pd.Timestamp(report["fit_dates"][0])
    end = pd.Timestamp(report["heldout_dates"][-1]) + pd.Timedelta(days=1)
    dataset = ds.dataset(str(source), format="ipc")
    raw = dataset.to_table(filter=(ds.field("date") >= start.to_pydatetime())
                           & (ds.field("date") < end.to_pydatetime())).to_pandas()
    canonical = normalize_local_bars(raw)
    del raw
    endpoints, grid = audit_endpoints(canonical)
    windows = LocalAuditWindowDataset(canonical, endpoints, grid, length=report["window_length"],
                                      bar_end_is_available=True)
    result = window_diagnostics(windows)
    if result["counts"] != report["windows"]["counts"]:
        raise ContractError("独立复查的真实窗口数量与原报告不一致")
    result["source_sha256"] = actual_hash
    result["fit_dates"] = report["fit_dates"]
    result["heldout_dates"] = report["heldout_dates"]
    result["elapsed_seconds"] = time.perf_counter() - started
    _write_json(Path(output_path), result)
    return result
