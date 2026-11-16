import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

directory = Path(__file__).resolve().parent / "linux-tools"
directory.mkdir(exist_ok=True)
with urllib.request.urlopen("https://pypi.org/pypi/uv/0.12.17/json", timeout=30) as response:
    metadata = json.load(response)
wheels = [item for item in metadata["urls"] if item["filename"].endswith(".whl")
          and "manylinux" in item["filename"] and "x86_64" in item["filename"]]
assert len(wheels) == 1, [item["filename"] for item in wheels]
asset = wheels[0]
archive_path = directory / asset["filename"]
with urllib.request.urlopen(asset["url"], timeout=60) as response:
    content = response.read()
assert hashlib.sha256(content).hexdigest() == asset["digests"]["sha256"]
archive_path.write_bytes(content)
with zipfile.ZipFile(archive_path) as archive:
    candidates = [name for name in archive.namelist() if Path(name).name == "uv"]
    assert len(candidates) == 1, candidates
    binary = directory / "uv"
    binary.write_bytes(archive.read(candidates[0]))
binary.chmod(0o755)
print(binary)
