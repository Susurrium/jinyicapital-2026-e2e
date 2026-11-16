import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import ptop._vendor.qlib as embedded_qlib

from ptop.schema import QLIB_COMMIT


def checksum(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(source: Path | None, destination: Path):
    root = Path(__file__).resolve().parents[1]
    installed = Path(embedded_qlib.__file__).parent
    paths = ["data/dataset/__init__.py", "data/dataset/loader.py", "data/dataset/handler.py",
             "data/dataset/processor.py", "contrib/model/pytorch_alstm.py",
             "contrib/model/pytorch_gru.py", "contrib/model/pytorch_nn.py"]
    hashes = {path.name: checksum(path) for path in sorted(installed.iterdir()) if path.is_file()}
    upstream_hashes = {relative: checksum(source / "qlib" / relative) for relative in paths} if source else None
    payload = {
        "qlib_commit": QLIB_COMMIT,
        "source_url": f"https://github.com/microsoft/qlib/archive/{QLIB_COMMIT}.zip",
        "qlib_components_version": embedded_qlib.COMPONENTS_VERSION,
        "embedded_files_sha256": hashes,
        "upstream_source_files_sha256": upstream_hashes,
        "python": platform.python_version(), "platform": platform.system(),
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("torch", "numpy", "pandas", "pyarrow", "pytest")},
        "official_templates_sha256": {name: checksum(root / name) for name in
                                      ("Transformer_modelsave_train.py", "Transformer_modelsave_predict.py")},
    }
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="可选：额外记录原始 Qlib 源码目录哈希，不执行源码等价验证")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record(args.source, args.output)
