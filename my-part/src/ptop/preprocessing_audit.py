from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from torch import Tensor, nn

from .encoders import ALSTMEncoder, validate_inputs
from .preprocessing import FrozenPreprocessor, _validate
from .schema import FEATURES, PRICE_FIELDS, ContractError


def audit_row_groups(values: pd.DataFrame) -> dict[str, np.ndarray]:
    """分组标签仅描述当前审计分区，不参与拟合或变换。"""
    level = values["close"].groupby(level="instrument").median().abs()
    names = pd.Series("missing", index=level.index)
    positive = level > 0
    names.loc[positive] = np.floor(np.log10(level.loc[positive])).astype(int).map(lambda n: f"1e{n}")
    names.loc[level == 0] = "zero"
    return {
        "price_magnitude": values.index.get_level_values("instrument").map(names).to_numpy(),
        "intraday_hour": values.index.get_level_values("datetime").strftime("%H:00").to_numpy(),
    }


class DiagnosticPreprocessor(FrozenPreprocessor):
    """以官方处理器拟合本地审计数据；该状态不能导出为正式冻结物。"""

    def freeze(self, *, scale_review: str) -> FrozenPreprocessor:
        raise ContractError("diagnostic_only 处理器不能冻结为正式训练状态")

    def state_dict(self) -> dict:
        raise ContractError("diagnostic_only 处理器不能导出正式冻结状态")

    def save(self, path) -> None:
        raise ContractError("diagnostic_only 处理器不能保存正式冻结文件")

    def diagnostics(self, values: pd.DataFrame, observed: pd.DataFrame) -> dict:
        normalized = self._transform(values, observed).to_numpy()
        raw, mask = values.to_numpy(), observed.to_numpy()
        quantiles = [0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0]

        def describe(selected: np.ndarray) -> dict:
            result = {}
            for column, field in enumerate(FEATURES):
                valid = selected & mask[:, column]
                x, z = raw[valid, column], normalized[valid, column]
                result[field] = {
                    "valid_count": len(x),
                    "center": float(self._processor.mean_train[column]),
                    "scale": float(self._processor.std_train[column]),
                    "zero_fraction": float(np.mean(x == 0)) if len(x) else None,
                    "raw_quantiles": np.quantile(x, quantiles).tolist() if len(x) else None,
                    "float32_quantiles": np.quantile(z, quantiles).tolist() if len(z) else None,
                    "float32_finite": bool(np.isfinite(z).all()),
                    "zero_variance_training": field in self.zero_variance_fields,
                    "mad_degenerate_training": field in self.degenerate_fields,
                    "training_constant_changed": bool(
                        len(x) and field in self.training_constants and np.any(x != self.training_constants[field])
                    ),
                }
            return result

        groups = audit_row_groups(values)
        return {
            "status": "diagnostic_only",
            "row_count": len(values),
            "quantile_probabilities": quantiles,
            "fields": describe(np.ones(len(values), dtype=bool)),
            "group_basis": "当前审计分区内各股票有效 close 中位数的十进制量级；日内小时",
            "groups": {
                name: {str(label): describe(labels == label) for label in np.unique(labels)}
                for name, labels in groups.items()
            },
            "degenerate_fields": list(self.degenerate_fields),
            "zero_variance_fields": list(self.zero_variance_fields),
        }


def _date_range(start, end, name: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if (
        pd.isna(start) or pd.isna(end) or start.tz is not None or end.tz is not None
        or start != start.normalize() or end != end.normalize() or start > end
    ):
        raise ContractError(f"{name}必须是按先后顺序排列的完整无时区日期")
    return start, end


def fit_diagnostic_candidates(
    values: pd.DataFrame,
    observed: pd.DataFrame,
    *,
    referenced_rows: pd.MultiIndex,
    fit_start,
    fit_end,
    heldout_start,
    heldout_end,
    modes: Sequence[str] = ("N0", "N1"),
    n2_base: str = "N1",
) -> tuple[dict[str, DiagnosticPreprocessor], dict]:
    """日期和引用行由调用方明确提供；后段数据只执行变换与诊断。"""
    _validate(values, observed)
    fit_start, fit_end = _date_range(fit_start, fit_end, "拟合范围")
    heldout_start, heldout_end = _date_range(heldout_start, heldout_end, "后段检查范围")
    if heldout_start <= fit_end:
        raise ContractError("后段检查日期必须晚于全部拟合日期")
    if not modes or len(set(modes)) != len(modes) or not set(modes).issubset({"N0", "N1", "N2"}):
        raise ContractError("诊断候选必须是 N0/N1/N2 的非空、无重复序列")
    times = values.index.get_level_values("datetime").normalize()
    heldout = (times >= heldout_start) & (times <= heldout_end)
    if not heldout.any():
        raise ContractError("后段检查日期内没有原始行")
    report = {
        "status": "diagnostic_only",
        "formal_training_eligible": False,
        "fit_start": fit_start.date().isoformat(),
        "fit_end": fit_end.date().isoformat(),
        "heldout_start": heldout_start.date().isoformat(),
        "heldout_end": heldout_end.date().isoformat(),
        "heldout_rows": int(heldout.sum()),
        "candidates": {},
    }
    processors = {}
    for mode in modes:
        processor = DiagnosticPreprocessor(mode, n2_base=n2_base).fit(
            values, observed, referenced_rows=referenced_rows, fit_start=fit_start, fit_end=fit_end,
        )
        before = processor._numeric_fingerprint()
        heldout_report = processor.diagnostics(values.loc[heldout], observed.loc[heldout])
        if processor._numeric_fingerprint() != before:
            raise ContractError("后段诊断改变了拟合状态")
        processors[mode] = processor
        report["candidates"][mode] = {
            "mode": mode,
            "base": processor.base,
            "fit_row_count": processor.fit_row_count,
            "fit_rows_fingerprint": processor.fit_rows_fingerprint,
            "numeric_fingerprint": before,
            "diagnostic_statistics": processor._numeric_state(),
            "fit": processor.training_diagnostics,
            "heldout": heldout_report,
            "numerically_nondegenerate": not bool(processor.degenerate_fields),
            "formal_training_eligible": False,
        }
    return processors, report


def scale_resolution(
    processor: FrozenPreprocessor, values: pd.DataFrame, observed: pd.DataFrame,
) -> dict:
    """检查已出现的同股相邻一分钟价格变化；未知交易 tick 不作推断。"""
    _validate(values, observed)
    ordered = values.sort_index(level=["instrument", "datetime"])
    flags = observed.reindex(ordered.index)
    output = processor._transform(ordered, flags)
    times = ordered.index.get_level_values("datetime")
    instruments = ordered.index.get_level_values("instrument").to_numpy()
    adjacent = np.zeros(len(ordered), dtype=bool)
    adjacent[1:] = (
        (instruments[1:] == instruments[:-1])
        & ((times[1:] - times[:-1]) == pd.Timedelta(minutes=1))
        & (times[1:].normalize() == times[:-1].normalize())
    )
    result = {}
    for field in PRICE_FIELDS:
        column = FEATURES.index(field)
        x, z, mask = ordered[field].to_numpy(), output[field].to_numpy(), flags[field].to_numpy()
        scale, center = processor._processor.std_train[column], processor._processor.mean_train[column]
        valid_pairs = adjacent.copy()
        valid_pairs[1:] &= mask[1:] & mask[:-1]
        delta = np.zeros(len(x), dtype=np.float64)
        delta[1:] = x[1:] - x[:-1]
        changed = valid_pairs & (delta != 0)
        dz = np.zeros(len(x), dtype=np.float64)
        dz[1:] = z[1:].astype(np.float64) - z[:-1].astype(np.float64)
        collisions = changed & (dz == 0)
        error = np.abs(z[mask].astype(np.float64) * scale + center - x[mask])
        steps = np.abs(delta[changed])
        reconstructed_step = dz[changed] * scale
        result[field] = {
            "observed_count": int(mask.sum()),
            "adjacent_observed_pairs": int(valid_pairs.sum()),
            "nonzero_raw_step_pairs": int(changed.sum()),
            "float32_collision_pairs": int(collisions.sum()),
            "float32_collision_fraction": float(collisions.sum() / changed.sum()) if changed.any() else None,
            "minimum_observed_nonzero_step": float(steps.min()) if len(steps) else None,
            "maximum_reconstruction_absolute_error": float(error.max()) if len(error) else None,
            "maximum_step_relative_error": float(np.max(np.abs(reconstructed_step - delta[changed]) / steps))
            if len(steps) else None,
            "collision_examples": [
                {"datetime": str(times[i]), "instrument": str(instruments[i]),
                 "previous_raw": float(x[i - 1]), "raw": float(x[i]), "float32": float(z[i])}
                for i in np.flatnonzero(collisions)[:5]
            ],
        }
    return {"scope": "同股、同日、时间差恰好一分钟，且两端均有效的已出现价格变化", "fields": result}


class _ActivationSummary:
    def __init__(self):
        self.rows = self.count = self.missing_rows = 0
        self.pre_sum = self.pre_square = self.post_sum = self.post_square = 0.0
        self.pre_min = self.post_min = None
        self.pre_max = self.post_max = None
        self.thresholds = (0.95, 0.99, 0.999)
        self.saturated = np.zeros(3, dtype=np.int64)
        self.pre_edges = np.array([-10, -5, -3, -1, 0, 1, 3, 5, 10], dtype=np.float64)
        self.post_edges = np.array([-0.999, -0.99, -0.95, -0.5, 0, 0.5, 0.95, 0.99, 0.999])
        self.pre_bins = np.zeros(10, dtype=np.int64)
        self.post_bins = np.zeros(10, dtype=np.int64)
        self.channel_saturation = None

    def add(self, pre: np.ndarray, post: np.ndarray, missing: np.ndarray) -> None:
        if not len(pre):
            return
        self.rows += len(pre)
        self.count += pre.size
        self.missing_rows += int(missing.sum())
        for prefix, array in (("pre", pre), ("post", post)):
            setattr(self, f"{prefix}_sum", getattr(self, f"{prefix}_sum") + float(array.sum(dtype=np.float64)))
            setattr(self, f"{prefix}_square", getattr(self, f"{prefix}_square") + float(np.square(array, dtype=np.float64).sum()))
            minimum, maximum = float(array.min()), float(array.max())
            previous_min, previous_max = getattr(self, f"{prefix}_min"), getattr(self, f"{prefix}_max")
            setattr(self, f"{prefix}_min", minimum if previous_min is None else min(previous_min, minimum))
            setattr(self, f"{prefix}_max", maximum if previous_max is None else max(previous_max, maximum))
        absolute = np.abs(post)
        self.saturated += [int((absolute >= threshold).sum()) for threshold in self.thresholds]
        channels = (absolute >= 0.99).sum(axis=0)
        self.channel_saturation = channels if self.channel_saturation is None else self.channel_saturation + channels
        self.pre_bins += np.bincount(np.searchsorted(self.pre_edges, pre, side="right").ravel(), minlength=10)
        self.post_bins += np.bincount(np.searchsorted(self.post_edges, post, side="right").ravel(), minlength=10)

    def report(self) -> dict:
        result = {"valid_step_count": self.rows, "fully_missing_valid_steps": self.missing_rows,
                  "activation_element_count": self.count}
        for prefix in ("pre", "post"):
            mean = getattr(self, f"{prefix}_sum") / self.count if self.count else None
            variance = max(0.0, getattr(self, f"{prefix}_square") / self.count - mean * mean) if self.count else None
            result[prefix] = {"mean": mean, "std": float(np.sqrt(variance)) if variance is not None else None,
                              "minimum": getattr(self, f"{prefix}_min"), "maximum": getattr(self, f"{prefix}_max"),
                              "histogram_boundaries": getattr(self, f"{prefix}_edges").tolist(),
                              "histogram_counts": getattr(self, f"{prefix}_bins").tolist()}
        result["saturation_fractions"] = {
            str(threshold): float(count / self.count) if self.count else None
            for threshold, count in zip(self.thresholds, self.saturated, strict=True)
        }
        result["saturated_counts"] = {
            str(threshold): int(count) for threshold, count in zip(self.thresholds, self.saturated, strict=True)
        }
        result["linear_abs_max"] = max(abs(self.pre_min), abs(self.pre_max)) if self.count else None
        result["per_channel_abs_ge_0_99_fraction"] = (
            (self.channel_saturation / self.rows).tolist() if self.rows else []
        )
        return result


def activation_diagnostics(
    model_or_encoder: nn.Module,
    x: Tensor,
    observed: Tensor,
    step_valid: Tensor,
    *,
    row_groups: Mapping[str, np.ndarray] | None = None,
    batch_size: int = 512,
) -> dict:
    """运行实际 ALSTM 输入投影；只统计有效槽，不运行后续时序主干。"""
    validate_inputs(x, observed, step_valid)
    if type(batch_size) is not int or batch_size <= 0:
        raise ContractError("激活诊断 batch_size 必须为正整数")
    encoder = model_or_encoder if isinstance(model_or_encoder, ALSTMEncoder) else getattr(model_or_encoder, "encoder", None)
    if not isinstance(encoder, ALSTMEncoder):
        raise ContractError("激活诊断需要 ALSTMEncoder 或具有该 encoder 的模型")
    layers = list(encoder.net.children())
    if len(layers) != 2 or not isinstance(layers[0], nn.Linear) or not isinstance(layers[1], nn.Tanh):
        raise ContractError("ALSTM 输入投影必须保持 Linear → Tanh 结构")
    labels = {}
    for name, group in (row_groups or {}).items():
        group = np.asarray(group)
        if not isinstance(name, str) or not name or group.shape != tuple(step_valid.shape) or pd.isna(group).any():
            raise ContractError("激活分组必须使用非空名称、完整标签和 [B,L] 形状")
        labels[name] = group.astype(str)
    overall, grouped = _ActivationSummary(), {name: {} for name in labels}
    captured = {}

    def capture(_module, inputs, output):
        captured["pre"], captured["post"] = inputs[0].detach(), output.detach()

    handle = layers[1].register_forward_hook(capture)
    modes = [(module, module.training) for module in encoder.modules()]
    try:
        encoder.eval()
        with torch.no_grad():
            for start in range(0, len(x), batch_size):
                stop = start + batch_size
                current_valid = step_valid[start:stop]
                encoder(x[start:stop], observed[start:stop], current_valid)
                pre = captured["pre"][current_valid].cpu().numpy()
                post = captured["post"][current_valid].cpu().numpy()
                if not np.isfinite(pre).all() or not np.isfinite(post).all():
                    raise ContractError("实际 ALSTM Linear/Tanh 激活包含非有限值")
                selected = current_valid.cpu().numpy()
                missing = (~observed[start:stop].any(dim=-1))[current_valid].cpu().numpy()
                overall.add(pre, post, missing)
                for name, group in labels.items():
                    current = group[start:stop][selected]
                    for label in np.unique(current):
                        keep = current == label
                        grouped[name].setdefault(str(label), _ActivationSummary()).add(pre[keep], post[keep], missing[keep])
    finally:
        handle.remove()
        for module, was_training in modes:
            module.training = was_training
    return {
        "scope": "实际 ALSTMEncoder Linear 输出与 Tanh 输出；排除结构填充，包含真实全缺失分钟",
        "weights_fitted_by_this_function": False,
        "histogram_semantics": "左闭右开；首尾桶分别包括边界之外的全部有限值",
        "overall": overall.report(),
        "groups": {name: {label: summary.report() for label, summary in groups.items()} for name, groups in grouped.items()},
    }
