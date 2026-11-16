import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import torch
import ptop

from ptop.bundle import MODEL_NAMES, REQUIRED_CONTRACTS, create_model, load_bundle, save_bundle
from ptop.preprocessing import FrozenPreprocessor
from ptop.schema import FEATURES


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "work/repo-publication"
INSTALLED = REPO / "work/package-installed"
assert Path(ptop.__file__).resolve().is_relative_to(INSTALLED), ptop.__file__
assert importlib.util.find_spec("qlib") is None
assert not any(dist.metadata["Name"].lower() == "pyqlib" for dist in importlib.metadata.distributions())
torch.set_num_threads(1)
index = pd.MultiIndex.from_product([pd.date_range("2024-01-02 09:31", periods=8, freq="min"), [1]],
                                  names=["datetime", "instrument"])
values = pd.DataFrame(np.arange(200, dtype=np.float64).reshape(8, 25), index=index, columns=FEATURES)
processor = FrozenPreprocessor("N1").fit(values, values.notna(), referenced_rows=index,
                                         fit_start="2024-01-02", fit_end="2024-01-02").freeze(
                                             scale_review="synthetic installed wheel check")
x = torch.as_tensor(np.stack([processor.transform(values, values.notna()).to_numpy()] * 2))
observed = torch.ones_like(x, dtype=torch.bool)
valid = torch.ones(2, 8, dtype=torch.bool)
output = ROOT / "work/installed-package-models"
output.mkdir(exist_ok=False)
for name in MODEL_NAMES:
    model = create_model(name).eval()
    expected = model(x, observed, valid)
    assert torch.isfinite(expected).all()
    save_bundle(output / name, model, processor, model_name=name, window_length=8,
                contracts={key: "synthetic" for key in REQUIRED_CONTRACTS}, seed=17,
                training_record={"scope": "installed wheel verification"}, instrument_map={1: "SYNTHETIC"})
    restored, recovered, _ = load_bundle(output / name)
    torch.testing.assert_close(expected, restored(x, observed, valid), atol=0, rtol=0)
    assert recovered.fingerprint == processor.fingerprint

paths = [REPO / name for name in ("README.md", "THIRD_PARTY.md", "requirements-a.txt", "pyproject.toml")]
for directory in ("src/ptop", "examples", "tests", "validation"):
    paths.extend(path for path in (REPO / directory).rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts
                 and (path.suffix in {".py", ".md"} or path.name == "LICENSE"))
assert all(path.is_file() for path in paths)
assert any(path.name == "LICENSE" for path in paths)
deliverable = ROOT / "deliverables/ptop-source-20261014.zip"
deliverable.parent.mkdir(exist_ok=True)
prefix = "ptop-source-20261014"
with zipfile.ZipFile(deliverable, "x", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        archive.write(path, str(Path(prefix) / path.relative_to(REPO)))
with zipfile.ZipFile(deliverable) as archive:
    assert archive.testzip() is None
    assert len(archive.namelist()) == len(paths)
    for path in paths:
        relative = str(Path(prefix) / path.relative_to(REPO)).replace("\\", "/")
        assert archive.read(relative) == path.read_bytes()
report = {"package_import": str(ptop.__file__), "qlib_installed": False, "installed_model_roundtrips": list(MODEL_NAMES),
          "source_zip": str(deliverable), "zip_files": len(paths), "zip_bytes": deliverable.stat().st_size,
          "zip_sha256": hashlib.sha256(deliverable.read_bytes()).hexdigest(), "crc_and_content_match": True}
(ROOT / "work/embedded-package-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
