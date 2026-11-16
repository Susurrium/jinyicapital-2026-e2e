import argparse
from pathlib import Path

from ptop.local_preflight import verify_local_reference_windows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立核对真实本地窗口与同日观察网格、源键及掩码")
    parser.add_argument("--report", type=Path, default=Path("reports/local-data/preprocessing-audit.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/local-data/window-verification.json"))
    args = parser.parse_args()
    result = verify_local_reference_windows(args.report, output_path=args.output)
    print(result["reference_grid_comparison"], result["counts"]["samples"])
