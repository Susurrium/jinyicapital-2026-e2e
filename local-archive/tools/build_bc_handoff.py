import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "54355232463878d2eebb91fe0ee5fa7fa1f5976c"
SOURCE_SHA256 = "9d6b630fbd6d17dce919067d21497093c7ab41ba5d743fa4e9066815d5cc42a4"
CORE = ("__init__", "schema", "data", "windows", "preprocessing", "encoders", "models",
        "targets", "official", "output", "bundle")
TESTS = ("test_data", "test_windows", "test_preprocessing", "test_encoders", "test_models",
         "test_targets_output", "test_official", "test_bundle")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def obtain_source():
    path = ROOT / "work/handoff-dependencies" / f"qlib-{COMMIT}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/microsoft/qlib/archive/{COMMIT}.zip"
    if not path.exists():
        with urllib.request.urlopen(url, timeout=90) as response, path.open("xb") as output:
            shutil.copyfileobj(response, output, 1024 * 1024)
    if digest(path) != SOURCE_SHA256:
        raise ValueError("Qlib 官方源码归档与已锁定 SHA-256 不一致")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Qlib 源码 ZIP 校验失败")
    return path, url


def package_build_source(upstream: Path, destination: Path) -> dict:
    prefix = f"qlib-{COMMIT}/"
    build_files = {"setup.py", "pyproject.toml", "MANIFEST.in", "README.md", "LICENSE"}
    source_files = {}
    with zipfile.ZipFile(upstream) as original, zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as output:
        for entry in original.infolist():
            if entry.is_dir() or not entry.filename.startswith(prefix):
                continue
            relative = entry.filename[len(prefix):]
            if not relative.startswith("qlib/") and relative not in build_files:
                continue
            if Path(relative).suffix.lower() in {".pkl", ".pt", ".pth", ".ckpt", ".h5", ".onnx", ".parquet", ".feather"}:
                raise ValueError(f"构建源码中发现非源码模型或行情资产：{relative}")
            content = original.read(entry.filename)
            output.writestr(entry, content)
            source_files[relative] = hashlib.sha256(content).hexdigest()
    if not build_files.issubset(source_files):
        raise ValueError("Qlib 构建元数据不完整")
    for necessary in ("qlib/data/_libs/rolling.pyx", "qlib/data/_libs/expanding.pyx",
                      "qlib/data/dataset/processor.py", "qlib/contrib/model/pytorch_alstm.py"):
        if necessary not in source_files:
            raise ValueError(f"Qlib 必要源码缺失：{necessary}")
    with zipfile.ZipFile(destination) as packed:
        if packed.testzip() is not None:
            raise ValueError("Qlib 构建源码 ZIP 校验失败")
        for relative, expected_hash in source_files.items():
            if hashlib.sha256(packed.read(prefix + relative)).hexdigest() != expected_hash:
                raise ValueError(f"Qlib 源文件字节校验失败：{relative}")
    return source_files


def build(name: str):
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("交接包名称必须是单一目录名")
    destination = ROOT / "deliverables" / f"{name}.zip"
    if destination.exists():
        raise FileExistsError(destination)
    source_zip, source_url = obtain_source()
    staging = ROOT / "work/handoff-staging" / uuid.uuid4().hex / name
    staging.mkdir(parents=True, exist_ok=False)
    for path in sorted((ROOT / "handoff").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".md", ".txt", ".json", ".toml"} and path.name != ".gitignore":
            raise ValueError(f"交接源目录包含未列入的文件：{path.name}")
        relative = path.relative_to(ROOT / "handoff")
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    for collection, source_dir, destination_dir in ((CORE, "src/ptop", "src/ptop"), (TESTS, "tests", "tests")):
        for stem in collection:
            target = staging / destination_dir / f"{stem}.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source_dir / f"{stem}.py", target)
    references = staging / "references/official_templates"
    references.mkdir(parents=True, exist_ok=True)
    for filename in ("Transformer_modelsave_train.py", "Transformer_modelsave_predict.py"):
        shutil.copyfile(ROOT / filename, references / filename)
    third_party = staging / "third_party"
    third_party.mkdir(exist_ok=True)
    packaged_source = third_party / source_zip.name
    source_files = package_build_source(source_zip, packaged_source)
    shutil.copyfile(ROOT / "vendor/licenses/QLIB-LICENSE", third_party / "QLIB-LICENSE")
    (third_party / "source-provenance.json").write_text(json.dumps({
        "qlib_commit": COMMIT, "source_url": source_url, "source_archive": source_zip.name,
        "upstream_archive_sha256": SOURCE_SHA256, "packaged_source_sha256": digest(packaged_source),
        "source_file_hashes": source_files, "build_version": f"0.0.0+git.{COMMIT}",
        "included_upstream_paths": ["qlib/", "setup.py", "pyproject.toml", "MANIFEST.in", "README.md", "LICENSE"],
        "linux_wheel_included": False, "cuda_wheelhouse_included": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    required = ("README.md", "docs/云端依赖.md", "docs/B_C职责与接口.md", "examples/cloud_bridge.py",
                "requirements-core.txt", "requirements-test.txt", "scripts/prepare_environment.py", "pyproject.toml")
    for name_required in required:
        if not (staging / name_required).is_file():
            raise FileNotFoundError(f"交接文件尚未准备完成：{name_required}")
    for path in staging.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path.relative_to(staging)))
    files = {str(path.relative_to(staging)).replace("\\", "/"): {"sha256": digest(path), "bytes": path.stat().st_size}
             for path in sorted(staging.rglob("*")) if path.is_file()}
    manifest = {"package": name, "purpose": "A to B/C cloud joint training handoff", "qlib_commit": COMMIT,
                "core_modules": list(CORE), "market_data_included": False, "trained_weights_included": False,
                "cloud_runtime_executed": False, "files": files}
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(name) / path.relative_to(staging)))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("交接 ZIP CRC 校验失败")
        expected = {f"{name}/{path}" for path in files} | {f"{name}/MANIFEST.json"}
        if set(archive.namelist()) != expected:
            raise ValueError("ZIP 文件清单与 manifest 不一致")
        for relative, info in files.items():
            if hashlib.sha256(archive.read(f"{name}/{relative}")).hexdigest() != info["sha256"]:
                raise ValueError(f"包内文件哈希不一致：{relative}")
    receipt = {"archive": str(destination.resolve()), "sha256": digest(destination), "bytes": destination.stat().st_size,
               "files": len(files) + 1, "crc_and_manifest": "passed", "python_syntax": "passed",
               "staging": str(staging.resolve())}
    (ROOT / "work/bc-handoff-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    destination.with_suffix(".sha256").write_text(f"{receipt['sha256']}  {destination.name}\n", encoding="ascii")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="以明确文件清单构建 B/C 云端交接 ZIP")
    parser.add_argument("--name", default="ptop-A-to-BC-20261011")
    parser.add_argument("--fetch-source-only", action="store_true")
    args = parser.parse_args()
    if args.fetch_source_only:
        path, url = obtain_source()
        print(json.dumps({"archive": str(path), "sha256": digest(path), "url": url}))
    else:
        build(args.name)
