import argparse
import json
from pathlib import Path

from ptop.local_archive import audit_archive, locate_negative_values


def main():
    parser = argparse.ArgumentParser(description="流式审计本地 1 分钟 Feather 归档")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=Path("work/local_archive"))
    parser.add_argument("--report", type=Path, default=Path("reports/local-data/archive-audit.json"))
    parser.add_argument("--first-member", type=Path, default=Path("work/local-data/first-month.feather"))
    parser.add_argument("--locate-negatives", action="store_true")
    parser.add_argument("--negative-report", type=Path, default=Path("reports/local-data/negative-value-audit.json"))
    args = parser.parse_args()
    if args.locate_negatives:
        result = locate_negative_values(args.archive, audit_report_path=args.report, work_dir=args.work_dir,
                                         report_path=args.negative_report,
                                         records_path=args.work_dir / "unknown-negative-records.parquet")
        print(json.dumps({"status": result["status"], "unknown_negative_values": result["unknown_negative_values"],
                          "affected_bar_keys": result["affected_bar_keys"], "report": str(args.negative_report.resolve())}, ensure_ascii=False), flush=True)
        return
    result = audit_archive(args.archive, work_dir=args.work_dir, report_path=args.report,
                           first_member_path=args.first_member,
                           progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    print(json.dumps({"status": result["status"], "totals": result["totals"], "violations": result["violations"],
                      "report": str(args.report.resolve())}, ensure_ascii=False), flush=True)
    if result["status"] != "local_storage_checks_passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
