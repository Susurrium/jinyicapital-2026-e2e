import argparse
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "work" / "deps"))


def inspect_archive(path, read_data):
    print(json.dumps({"archive": path.name, "archive_bytes": path.stat().st_size}), flush=True)
    with tarfile.open(path, mode="r|gz") as archive:
        for member in archive:
            print(json.dumps({"member": member.name, "bytes": member.size}), flush=True)
            if not member.isfile() or not member.name.endswith(".feather"):
                continue
            if not read_data:
                return

            import pyarrow as pa
            import pyarrow.compute as pc
            import pyarrow.feather as feather

            # 只读取首个月份的选定字段，保持原始压缩包不变。
            with archive.extractfile(member) as source:
                buffer = pa.BufferReader(source.read())
            schema = pa.ipc.open_file(buffer).schema
            print(json.dumps({"schema": str(schema)}, ensure_ascii=False), flush=True)
            columns = ["date", "instrument_id", "open", "high", "low", "close",
                       "volume", "amount", "deal_number", "ask_price1", "bid_price1",
                       "ask_volume1", "bid_volume1", "ask_num_orders1", "bid_num_orders1"]
            buffer.seek(0)
            table = feather.read_table(buffer, columns=columns)
            print(json.dumps({"rows": table.num_rows, "sample": table.slice(0, 3).to_pylist()},
                             default=str, ensure_ascii=False), flush=True)
            dates = pc.unique(table["date"])
            instruments = pc.unique(table["instrument_id"])
            times = sorted(set(pc.strftime(dates, format="%H:%M").to_pylist()))
            print(json.dumps({"date_range": pc.min_max(table["date"]).as_py(),
                              "instrument_count": len(instruments),
                              "time_count": len(times), "first_times": times[:12],
                              "last_times": times[-5:]},
                             default=str), flush=True)
            missing = {}
            for name in columns:
                if name in ("date", "instrument_id"):
                    continue
                values = table[name]
                missing[name] = {"null": values.null_count,
                                 "zero": pc.sum(pc.equal(values, 0)).as_py(),
                                 "minus_one": pc.sum(pc.equal(values, -1)).as_py(),
                                 "range": pc.min_max(values).as_py()}
            print(json.dumps({"field_stats": missing}), flush=True)
            counts = table.select(["instrument_id"]).group_by("instrument_id").aggregate(
                [("instrument_id", "count")])
            stock_id = counts["instrument_id"][0].as_py()
            stock = table.filter(pc.equal(table["instrument_id"], stock_id))
            first_day = pc.min(pc.cast(stock["date"], pa.date32())).as_py()
            stock_day = stock.filter(pc.equal(pc.cast(stock["date"], pa.date32()), first_day))
            print(json.dumps({"first_stock_first_day_rows": stock_day.num_rows,
                              "first_stock_first_day_sample": stock_day.slice(0, 3).to_pylist()},
                             default=str), flush=True)
            return
    raise RuntimeError(f"没有找到 Feather 数据文件：{path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-data", action="store_true")
    parser.add_argument("--frequency", choices=["30m", "15m", "5m", "1m"], default="30m")
    args = parser.parse_args()
    for frequency in ["30m", "15m", "5m", "1m"]:
        path = ROOT / f"cpt_jyc_2026_e2e_bar{frequency}.tar.gz"
        inspect_archive(path, args.read_data and frequency == args.frequency)
