import argparse
import json
from pathlib import Path
import sys


def probe(root: Path):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src"))
    import ptop
    import ptop.bundle
    import ptop.data
    import ptop.encoders
    import ptop.models
    import ptop.official
    import ptop.output
    import ptop.preprocessing
    import ptop.schema
    import ptop.targets
    import ptop.windows
    from examples import cloud_bridge
    for name, module in list(sys.modules.items()):
        if name == "ptop" or name.startswith("ptop.") or name == "examples.cloud_bridge":
            if not Path(module.__file__).resolve().is_relative_to(root):
                raise RuntimeError(f"导入未使用交接包源码：{name}")
    required = ("fetch_cloud_training", "prepare_fold", "supervised_step", "predict_cloud")
    for name in required:
        if not callable(getattr(cloud_bridge, name)):
            raise RuntimeError(f"缺少可调用接口：{name}")
    config = json.loads((root / "configs/first_run.json").read_text(encoding="utf-8"))
    if config["model_name"] != "R1" or config["normalization"] != "N1" or config["window_length"] != 120:
        raise RuntimeError("首轮配置与交接要求不一致")
    result = {"packaged_core_imports": "passed", "packaged_bridge_imports": "passed",
              "first_run_configuration": "passed", "scope": "isolated unpacked package import and integrity checks",
              "data_accessed": False, "training_executed": False}
    (root / "work").mkdir(exist_ok=True)
    (root / "work/import-probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    probe(parser.parse_args().root.resolve())
