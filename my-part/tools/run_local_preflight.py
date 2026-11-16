import argparse
from pathlib import Path

from ptop.local_preflight import run_local_preflight


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="本地真实 1 分钟数据的独立诊断；不产生正式训练状态")
    parser.add_argument("--feather", required=True, type=Path)
    parser.add_argument("--report", type=Path, default=Path("reports/local-data/preprocessing-audit.json"))
    parser.add_argument("--cache", type=Path, default=Path("work/local-preflight"))
    parser.add_argument("--fit-days", type=int, default=5)
    parser.add_argument("--heldout-days", type=int, default=2)
    args = parser.parse_args()
    run_local_preflight(args.feather, report_path=args.report, cache_directory=args.cache,
                        fit_days=args.fit_days, heldout_days=args.heldout_days)
