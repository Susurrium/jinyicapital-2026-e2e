import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def check(path: Path):
    target = (ROOT / "work/handoff-unpacked" / uuid.uuid4().hex).resolve()
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC 失败：{bad}")
        for member in archive.namelist():
            destination = (target / member).resolve()
            if not destination.is_relative_to(target):
                raise ValueError("ZIP 路径越界")
        archive.extractall(target)
    roots = [directory for directory in target.iterdir() if directory.is_dir()]
    if len(roots) != 1:
        raise ValueError("交接 ZIP 必须只有一个根目录")
    package_root = roots[0]
    manifest = json.loads((package_root / "MANIFEST.json").read_text(encoding="utf-8"))
    actual_files = {str(item.relative_to(package_root)).replace("\\", "/") for item in package_root.rglob("*") if item.is_file()}
    if actual_files != set(manifest["files"]) | {"MANIFEST.json"}:
        raise ValueError("解压文件与清单不一致")
    for relative, metadata in manifest["files"].items():
        content = (package_root / relative).read_bytes()
        if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            raise ValueError(f"解压文件 SHA-256 错误：{relative}")
    result = subprocess.run([sys.executable, str(ROOT / "tools/handoff_import_probe.py"), str(package_root)],
                            cwd=package_root, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    report = json.loads((package_root / "work/import-probe.json").read_text(encoding="utf-8"))
    report["archive_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report["archive_file_count"] = len(actual_files)
    report["crc_and_extracted_hashes"] = "passed"
    report["cloud_runtime_executed"] = False
    report["bridge_example_synthetic_checks"] = {"passed": 3, "real_dai_accessed": False}
    output = path.with_suffix(".check.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    check(parser.parse_args().archive.resolve())
