import argparse
import importlib
import json
import platform
import sys
from importlib.metadata import distributions, version
from pathlib import Path

import numpy
import pandas
import psutil
import pyarrow
import torch
from qlib.data.dataset import TSDataSampler


QLIB_VERSION = "0.0.0+git.54355232463878d2eebb91fe0ee5fa7fa1f5976c"
EXPECTED_VERSIONS = {
    "numpy": "2.2.6",
    "pandas": "2.2.3",
    "pyarrow": "20.0.0",
    "psutil": "7.2.2",
    "pyqlib": QLIB_VERSION,
}
TORCH_VERSIONS = {
    "2.8.0", "2.8.0+cpu", "2.8.0+cu126", "2.8.0+cu128", "2.8.0+cu129",
}


def main():
    parser = argparse.ArgumentParser(description="检查指定设备和依赖，记录当前环境；不安装依赖、不查询数据。")
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-platform", action="store_true", help="同时检查官方模板的 dai、bigmodule、structlog 导入")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"交接包要求 Python 3.12，当前是 {sys.version}")
    if args.output.exists():
        raise FileExistsError(f"环境记录已存在，请指定新路径：{args.output}")
    current = {name: version(name) for name in (*EXPECTED_VERSIONS, "torch")}
    for name, expected in EXPECTED_VERSIONS.items():
        if current[name] != expected:
            raise RuntimeError(f"{name} 版本不匹配：要求 {expected}，当前 {current[name]}")
    if current["torch"] not in TORCH_VERSIONS:
        raise RuntimeError(f"要求 PyTorch 2.8.0 的已列明构建，当前是 {current['torch']}")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("本次明确指定 CUDA，但 torch.cuda.is_available() 为 False")
    device = torch.device(args.device)
    # 在实际指定设备分配并计算，保留数值结果与运行时版本供交接核对。
    tensor = torch.arange(4, dtype=torch.float32, device=device)
    result = tensor.square().sum().item()
    if result != 14.0:
        raise RuntimeError(f"设备基础计算结果异常：{result}")
    modules = {}
    if args.require_platform:
        for name in ("dai", "bigmodule", "structlog"):
            module = importlib.import_module(name)
            modules[name] = {"file": getattr(module, "__file__", None)}
    report = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "dependencies": current,
        "requested_device": args.device,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu_names": [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
        "device_calculation": result,
        "memory_available_bytes": psutil.virtual_memory().available,
        "platform_imports": modules,
        "qlib_sampler": f"{TSDataSampler.__module__}.{TSDataSampler.__name__}",
        "installed_distributions": sorted(
            ({"name": dist.metadata["Name"], "version": dist.version} for dist in distributions()),
            key=lambda item: (item["name"].lower(), item["version"]),
        ),
        "scope": "依赖导入与设备基础计算；未查询 DAI 数据，未执行联合训练",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"环境检查通过，记录已保存：{args.output}")


if __name__ == "__main__":
    main()
