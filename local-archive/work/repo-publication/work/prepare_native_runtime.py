from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1]).resolve(strict=True)
assert (root / "src/ptop/_vendor/qlib/models.py").is_file()
assert (root / ".git").is_file()
work = root / "work"
work.mkdir(exist_ok=True)
if sys.argv[2] == "python":
    shutil.copytree(Path(sys.base_prefix), work / "python", symlinks=True)
    print(work / "python/bin/python3.12", flush=True)
elif sys.argv[2] == "packages":
    source = Path(sys.prefix) / "lib/python3.12/site-packages"
    target = work / "venv/lib/python3.12/site-packages"
    assert target.is_dir()
    shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
    print(target, flush=True)
else:
    raise ValueError("stage must be python or packages")
