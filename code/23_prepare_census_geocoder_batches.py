from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("address_csv", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("manifest_json", type=Path)
    args = parser.parse_args()

    rows = []
    with args.address_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("main_geo") == "1" and row.get("has_street_address") == "1":
                rows.append([
                    row["case_number"], row["street"], row["geocode_city"],
                    row["geocode_state"], row["geocode_zip"],
                ])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for start in range(0, len(rows), 10_000):
        number = start // 10_000 + 1
        path = args.output_dir / f"nlrb_census_batch_{number:03d}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows[start : start + 10_000])
        payload = path.read_bytes()
        manifest.append({
            "file": path.name,
            "rows": len(rows[start : start + 10_000]),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })

    args.manifest_json.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_json.write_text(
        json.dumps({"total_rows": len(rows), "batches": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"total_rows": len(rows), "batches": manifest}, indent=2))

if __name__ == "__main__":
    main()
