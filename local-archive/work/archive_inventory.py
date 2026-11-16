import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT / "work/repo-publication"
REPORT = ROOT / "reports/archive-20261116"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inventory():
    rows = []
    for parent in (ROOT / "work", REPOSITORY / "work"):
        for child in sorted(parent.iterdir()):
            if not child.is_dir() or child == REPOSITORY:
                continue
            count = size = 0
            links = []
            for directory, dirs, files in os.walk(child, followlinks=False):
                for name in dirs + files:
                    path = Path(directory) / name
                    metadata = path.lstat()
                    if metadata.st_file_attributes & 0x400:
                        links.append(str(path.relative_to(ROOT)))
                        if name in dirs:
                            dirs.remove(name)
                for name in files:
                    path = Path(directory) / name
                    metadata = path.lstat()
                    if not metadata.st_file_attributes & 0x400:
                        count += 1
                        size += metadata.st_size
            rows.append({"path": child.relative_to(ROOT).as_posix(), "files": count,
                         "bytes": size, "links": links})
    return rows


def manifest():
    # 只对保留资料生成指纹；依赖环境与可再生缓存不进入资料清单。
    paths = []
    for name in ("src", "tests", "tools", "validation", "docs", "reports", "handoff", "vendor", "deliverables"):
        for path in (ROOT / name).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and ".egg-info" not in str(path):
                paths.append(path)
    for path in ROOT.iterdir():
        if path.is_file():
            paths.append(path)
    paths.extend((ROOT / "data/official").rglob("*.csv"))
    paths.extend((ROOT / "data/official").rglob("*.json"))
    for parent in (ROOT / "work", REPOSITORY / "work"):
        paths.extend(path for path in parent.iterdir() if path.is_file())
    for name in ("local_archive", "local-preflight", "negative-cause", "synthetic-validation", "installed-package-models"):
        paths.extend(path for path in (ROOT / "work" / name).rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    files = {}
    for path in sorted(set(paths)):
        if path.parent == REPORT and path.name in {"manifest.json", "verification.json"}:
            continue
        files[path.relative_to(ROOT).as_posix()] = {"bytes": path.stat().st_size, "sha256": digest(path)}
    raw = [{"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "last_write_ns": path.stat().st_mtime_ns}
           for path in sorted((ROOT / "data").glob("*.tar.gz"))]
    tests = []
    for path in sorted(REPORT.rglob("*.xml")):
        for suite in ET.parse(path).getroot().iter("testsuite"):
            tests.append({"path": path.relative_to(ROOT).as_posix(), **suite.attrib})
    return {"date": "2026-11-16", "files": files, "raw_data": raw,
            "raw_data_validation": "size and modification time; original archives retained without rewriting",
            "historical_test_suites": tests}


def verify():
    state = json.loads((REPORT / "manifest.json").read_text(encoding="utf-8"))
    errors = []
    for relative, expected in state["files"].items():
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            errors.append(relative)
    for entry in state["raw_data"]:
        path = ROOT / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or path.stat().st_mtime_ns != entry["last_write_ns"]:
            errors.append(entry["path"])
    archives = {}
    for path in sorted((ROOT / "deliverables").glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            failed = archive.testzip()
            archives[path.name] = {"files": len(archive.namelist()), "crc_error": failed}
            if failed:
                errors.append(str(path))
    status = subprocess.check_output(["git", "--no-optional-locks", "status", "--porcelain=v1"], cwd=REPOSITORY, text=True)
    if status.strip():
        errors.append("repository has uncommitted changes: " + status)
    subprocess.run(["git", "fsck", "--full"], cwd=REPOSITORY, check=True, capture_output=True, text=True)
    for path in sorted((ROOT / "deliverables").glob("*.bundle")):
        subprocess.run(["git", "bundle", "verify", str(path)], cwd=REPOSITORY, check=True, capture_output=True, text=True)
    baseline = json.loads((REPORT / "preservation-before.json").read_text(encoding="utf-8"))
    for relative, entry in baseline["files"].items():
        path = ROOT / relative
        if not path.is_file() or digest(path) != entry["sha256"]:
            errors.append("preservation mismatch: " + relative)
    for entry in baseline["raw_data"]:
        path = ROOT / entry["path"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or path.stat().st_mtime_ns != entry["last_write_ns"]:
            errors.append("raw archive changed: " + entry["path"])
    result = {"verified_files": len(state["files"]), "raw_archives_retained": len(state["raw_data"]),
              "preserved_files_verified": len(baseline["files"]), "git_bundles": "passed",
              "zip_checks": archives, "git_worktree_clean": not status.strip(), "git_fsck": "passed", "errors": errors}
    (REPORT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("inventory", "baseline", "manifest", "verify"))
args = parser.parse_args()
REPORT.mkdir(exist_ok=True)
if args.action == "verify":
    verify()
else:
    result = inventory() if args.action == "inventory" else manifest()
    filename = {"inventory": "inventory-before.json", "baseline": "preservation-before.json", "manifest": "manifest.json"}[args.action]
    destination = REPORT / filename
    if destination.exists():
        raise FileExistsError(destination)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.action == "inventory":
        print(json.dumps([{**row, "links": len(row["links"])} for row in result], ensure_ascii=False))
    else:
        print(json.dumps({"manifest": str(destination), "files": len(result["files"])}))
