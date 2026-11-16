import json
import os
import subprocess
import sys
from pathlib import Path


def test_complete_synthetic_flow_and_independent_reload(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    output = tmp_path / "integration"
    result = subprocess.run([sys.executable, str(root / "tools" / "smoke.py"), "--output", str(output)],
                            env=environment, capture_output=True, text=True, cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["data_kind"] == "synthetic only"
    assert report["parameters"]["R0"] == 47297
    assert report["parameters"]["R1"] == 55425
    assert report["independent_process_reload"]["status"] == "passed"
    assert report["maximum_missing_rate"] == 0.0
