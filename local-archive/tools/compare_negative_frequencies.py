import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import time

import pandas as pd
import pyarrow.feather as feather

from ptop.local_archive import _HashingReader


def compare(archive_path: Path, anomalies: pd.DataFrame) -> dict:
    started = time.perf_counter()
    target_months = set(anomalies["date"].dt.strftime("%Y%m"))
    matches = []
    source_types = {}
    source_members = []
    with archive_path.open("rb") as source:
        hashed = _HashingReader(source)
        with tarfile.open(fileobj=hashed, mode="r|gz") as archive:
            for member in archive:
                filename = PurePosixPath(member.name).name
                if not member.isfile() or not filename.endswith(".feather") or filename.split(".")[0] not in target_months:
                    continue
                with archive.extractfile(member) as contents:
                    buffer = io.BytesIO(contents.read())
                table = feather.read_table(buffer, columns=["date", "instrument_id", "bid_num_orders1", "ask_num_orders1",
                                                            "bid_price1", "ask_price1", "bid_volume1", "ask_volume1"])
                source_types[member.name] = {name: str(table.schema.field(name).type)
                                              for name in ("bid_num_orders1", "ask_num_orders1")}
                values = table.to_pandas()
                if values.duplicated(["date", "instrument_id"]).any():
                    raise ValueError(f"跨频率核对遇到重复源键：{member.name}")
                month_anomalies = anomalies[anomalies["date"].dt.strftime("%Y%m").eq(filename.split(".")[0])]
                joined = month_anomalies.merge(values, on=["date", "instrument_id"], how="inner", validate="one_to_one")
                joined["comparison_value"] = [row[row["field"]] for _, row in joined.iterrows()]
                joined["comparison_member"] = member.name
                matches.append(joined)
                source_members.append(member.name)
                print(json.dumps({"archive": archive_path.name, "member": member.name, "matched": len(joined)}), flush=True)
        while hashed.read(8 * 1024 * 1024):
            pass
    result = pd.concat(matches, ignore_index=True)
    equal = result["raw_value"].eq(result["comparison_value"])
    if result.duplicated(["date", "instrument_id", "field"]).any():
        raise ValueError("跨频率匹配出现重复键")
    result.to_parquet(Path("work/negative-cause") / f"matches-{archive_path.stem}.parquet", index=False)
    return {"source_path": str(archive_path), "sha256": hashed.digest.hexdigest(),
            "source_members": source_members, "source_types": source_types,
            "matched_anomaly_keys": len(result), "same_raw_value": int(equal.sum()),
            "different_raw_value": int((~equal).sum()),
            "by_field": {field: {"matched": len(group),
                                    "same": int(group["raw_value"].eq(group["comparison_value"]).sum())}
                         for field, group in result.groupby("field")},
            "elapsed_seconds": time.perf_counter() - started,
            "scope": "only identical date/instrument keys among previously identified 1m negative cells"}


def main():
    root = Path(__file__).resolve().parents[1]
    anomalies = pd.read_parquet(root / "work/local_archive/unknown-negative-records.parquet")
    output = root / "reports/local-data/negative-cross-frequency.json"
    result = {"scope": "local exported data only; not cloud int32 ground truth", "frequencies": {}}
    (root / "work/negative-cause").mkdir(parents=True, exist_ok=True)
    for frequency in ("30m", "15m", "5m"):
        result["frequencies"][frequency] = compare(root / f"data/cpt_jyc_2026_e2e_bar{frequency}.tar.gz", anomalies)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: {key: value[key] for key in ("matched_anomaly_keys", "same_raw_value", "different_raw_value")}
                      for name, value in result["frequencies"].items()}))


if __name__ == "__main__":
    main()
