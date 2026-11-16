import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from ptop.bundle import load_bundle


def verify(path: Path):
    torch.set_num_threads(1)
    model, processor, manifest = load_bundle(path / "bundle")
    fingerprint = processor.fingerprint
    values = pd.read_parquet(path / "raw_values.parquet")
    observed = pd.read_parquet(path / "observed.parquet")
    expected_values = pd.read_parquet(path / "transformed.parquet")
    pd.testing.assert_frame_equal(processor.transform(values, observed), expected_values)
    with np.load(path / "inputs.npz", allow_pickle=False) as fixture:
        inputs = tuple(torch.from_numpy(fixture[key]) for key in ("x", "observed", "step_valid"))
        with torch.no_grad():
            scores = model(*inputs).numpy()
        if not np.isfinite(scores).all() or not np.isfinite(fixture["scores"]).all():
            raise RuntimeError("重载验证分数必须为有限数值")
        np.testing.assert_allclose(scores, fixture["scores"], atol=1e-6, rtol=1e-5, equal_nan=False)
    if processor.fingerprint != fingerprint:
        raise RuntimeError("推理改变了处理器状态")
    report = {"status": "passed", "model": manifest["model_name"], "samples": len(scores)}
    (path / "reload_report.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
