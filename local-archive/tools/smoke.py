import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from ptop.bundle import MODEL_NAMES, REQUIRED_CONTRACTS, create_model, save_bundle
from ptop.data import CanonicalData, normalize_bars
from ptop.models import count_parameters
from ptop.output import audit_output
from ptop.preprocessing import FrozenPreprocessor
from ptop.schema import FEATURES
from ptop.windows import WindowDataset, fit_row_union


def run(destination: Path):
    started = time.perf_counter()
    destination.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(17)
    generator = np.random.default_rng(17)
    grid = pd.date_range("2024-01-02 09:31", periods=12, freq="min")
    mapping = {1: "SYNTHETIC_A", 2: "SYNTHETIC_B", 3: "SYNTHETIC_C"}
    rows = pd.MultiIndex.from_product([grid, mapping], names=["date", "instrument_id"]).to_frame(index=False)
    for name in FEATURES:
        rows[name] = generator.integers(1, 10000, size=len(rows))
    # 同一真实时间槽全市场缺少数据，另一个槽位保留真实零值和字段缺失。
    rows = rows.loc[rows["date"] != grid[4]].copy()
    rows.loc[rows.index[1], "volume"] = 0
    rows.loc[rows.index[2], "open"] = -1
    data = normalize_bars(rows, source="local", instrument_map=mapping, bar_end_is_available=True)
    expected = pd.MultiIndex.from_product([grid[[2, 7, 11]], mapping],
                                         names=["decision_time", "instrument_id"]).to_frame(index=False)
    expected["sample_id"] = np.arange(len(expected))
    expected["decision_id"] = np.repeat(np.arange(3), 3)
    raw_windows = WindowDataset(data, expected, grid, length=10)
    referenced = fit_row_union(raw_windows, fit_start="2024-01-02", fit_end="2024-01-02")
    preprocessor = FrozenPreprocessor("N1").fit(
        data.values, data.observed, referenced_rows=referenced, fit_start="2024-01-02", fit_end="2024-01-02"
    )
    diagnostics = preprocessor.diagnostics(data.values, data.observed)
    preprocessor.freeze(scale_review="synthetic fixture only; finite scale and float32 diagnostics checked")
    transformed = preprocessor.transform(data.values, data.observed)
    processed = CanonicalData(transformed, data.observed.copy(), data.metadata.copy(), mapping)
    batch = WindowDataset(processed, expected, grid, length=10).get_batch(np.arange(len(expected)))
    inputs = tuple(torch.from_numpy(value) for value in (batch.x, batch.observed, batch.step_valid))
    model = create_model("R1")
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    # 合成目标仅验证 A/B 联合反向传播，不代表比赛目标或预测成绩。
    synthetic_target = torch.linspace(-0.02, 0.02, len(expected))
    loss = torch.nn.functional.mse_loss(model(*inputs), synthetic_target)
    optimizer.zero_grad()
    loss.backward()
    for name, parameter in model.named_parameters():
        if parameter.grad is None or not torch.isfinite(parameter.grad).all():
            raise RuntimeError(f"合成验证的参数梯度异常：{name}")
    torch.nn.utils.clip_grad_value_(model.parameters(), 3.0)
    optimizer.step()
    model.eval()
    with torch.no_grad():
        scores = model(*inputs).numpy()
        encoded_input = model.encoder.prepare(*inputs)
        activation_before = model.encoder.net[0](encoded_input)[inputs[2]]
        activation_after = model.encoder.net[1](activation_before)
    before = preprocessor.fingerprint
    save_bundle(destination / "bundle", model, preprocessor, model_name="R1", window_length=10,
                contracts={name: "synthetic-fixture-v1" for name in REQUIRED_CONTRACTS}, seed=17,
                training_record={"kind": "synthetic integration verification", "optimizer_steps": 1},
                instrument_map=mapping)
    data.values.to_parquet(destination / "raw_values.parquet")
    data.observed.to_parquet(destination / "observed.parquet")
    transformed.to_parquet(destination / "transformed.parquet")
    np.savez(destination / "inputs.npz", x=batch.x, observed=batch.observed, step_valid=batch.step_valid, scores=scores)
    subprocess.run([sys.executable, str(Path(__file__).with_name("verify_reload.py")), str(destination)],
                   check=True)
    if preprocessor.fingerprint != before:
        raise RuntimeError("保存期间处理器状态改变")
    output = pd.DataFrame({"date": batch.metadata["decision_time"], "instrument": batch.metadata["instrument"], "score": scores})
    coverage = audit_output(output, expected.assign(instrument=expected["instrument_id"].map(mapping)).rename(
        columns={"decision_time": "date"}), start_date=grid[0], end_date=grid[-1])
    report = {"data_kind": "synthetic only", "samples": len(batch.x), "raw_rows": len(data.values),
              "fit_unique_rows": len(referenced), "joint_gradient_check": "passed",
              "independent_process_reload": json.loads((destination / "reload_report.json").read_text(encoding="utf-8")),
              "alstm_activation": {"linear_abs_max": float(activation_before.abs().max()),
                                   "tanh_abs_ge_0_99_fraction": float((activation_after.abs() >= 0.99).float().mean())},
              "processor_fingerprint": before,
              "maximum_missing_rate": float(coverage["missing_rate"].max()),
              "parameters": {name: count_parameters(create_model(name)) for name in MODEL_NAMES},
              "elapsed_seconds": time.perf_counter() - started}
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "scale_diagnostics.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2,
                                                                   allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用独立合成数据验证规范化、窗口、联合梯度和模型包重载")
    parser.add_argument("--output", type=Path, required=True, help="新的验证输出目录，推荐 work/ 下")
    run(parser.parse_args().output.resolve())
