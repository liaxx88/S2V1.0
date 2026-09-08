from __future__ import annotations

import argparse
import csv
from pathlib import Path

RESULT_FIELDS = [
    "case_number", "input_address", "match_status", "match_type",
    "matched_address", "coordinates", "tiger_line_id", "side",
    "state_fips", "county_code", "tract", "block",
]

def read_results(raw_dir: Path):
    results = {}
    for path in sorted(raw_dir.glob("nlrb_census_batch_*_results_raw.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for values in csv.reader(handle):
                if not values:
                    continue

                
                if len(values) < 3:
                    raise ValueError(f"Malformed Census row in {path}: {values}")
                case_number = values[0].strip().upper()
                padded = values[:12] + [""] * max(0, 12 - len(values))
                row = dict(zip(RESULT_FIELDS, padded))
                row["source_file"] = path.name
                state_fips = row["state_fips"].strip()
                county_code = row["county_code"].strip()
                row["county_fips_exact"] = (
                    state_fips.zfill(2) + county_code.zfill(3)
                    if row["match_status"].strip().upper() == "MATCH"
                    and state_fips and county_code else ""
                )
                longitude = latitude = ""
                if "," in row["coordinates"]:
                    longitude, latitude = [part.strip() for part in row["coordinates"].split(",", 1)]
                row["longitude"] = longitude
                row["latitude"] = latitude
                if case_number in results:
                    raise ValueError(f"Duplicate Census result ID: {case_number}")
                results[case_number] = row
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_results_dir", type=Path)
    parser.add_argument("batch_input_dir", type=Path)
    parser.add_argument("preliminary_csv", type=Path)
    parser.add_argument("exact_output_csv", type=Path)
    parser.add_argument("final_output_csv", type=Path)
    args = parser.parse_args()

    exact = read_results(args.raw_results_dir)
    input_ids = set()
    for path in sorted(args.batch_input_dir.glob("nlrb_census_batch_*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for values in csv.reader(handle):
                if values:
                    input_ids.add(values[0].strip().upper())
    if input_ids != set(exact):
        missing = sorted(input_ids - set(exact))[:10]
        extra = sorted(set(exact) - input_ids)[:10]
        raise ValueError(
            f"Census raw results do not match current batch inputs; "
            f"missing examples={missing}, extra examples={extra}"
        )
    exact_fields = [
        "case_number", "match_status", "match_type", "input_address",
        "matched_address", "longitude", "latitude", "state_fips",
        "county_code", "county_fips_exact", "tract", "block", "tiger_line_id",
        "side", "source_file",
    ]
    with args.exact_output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=exact_fields)
        writer.writeheader()
        for case_number in sorted(exact):
            writer.writerow({field: exact[case_number].get(field, "") for field in exact_fields})

    final_fields = [
        "case_number", "county_fips", "county_name", "geocode_quality",
        "geocode_quality_label", "county_source", "latitude", "longitude",
        "match_status", "match_type", "matched_address", "tract", "block",
        "preliminary_county_fips", "county_disagreement", "city_name_norm",
        "has_street_address", "has_zip", "address_source", "street",
        "geocode_city", "geocode_state", "geocode_zip", "main_geo",
    ]
    args.final_output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.preliminary_csv.open("r", encoding="utf-8-sig", newline="") as src, \
            args.final_output_csv.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=final_fields)
        writer.writeheader()
        for row in reader:
            case_number = row["case_number"].strip().upper()
            geocode = exact.get(case_number)
            prelim = row.get("county_fips", "")
            exact_county = geocode.get("county_fips_exact", "") if geocode else ""
            if exact_county:
                county_fips = exact_county
                county_name = row.get("county_name", "") if exact_county == prelim else ""
                quality = 1
                label = "exact_address"
                source = "census_batch_geocoder"
            else:
                county_fips = prelim
                county_name = row.get("county_name", "")
                quality = int(row.get("geocode_quality") or 5)
                label = row.get("geocode_quality_label", "unmatched")
                source = row.get("county_source", "")
            output = {
                **row,
                "case_number": case_number,
                "county_fips": county_fips,
                "county_name": county_name,
                "geocode_quality": quality,
                "geocode_quality_label": label,
                "county_source": source,
                "latitude": geocode.get("latitude", "") if geocode else "",
                "longitude": geocode.get("longitude", "") if geocode else "",
                "match_status": geocode.get("match_status", "") if geocode else "",
                "match_type": geocode.get("match_type", "") if geocode else "",
                "matched_address": geocode.get("matched_address", "") if geocode else "",
                "tract": geocode.get("tract", "") if geocode else "",
                "block": geocode.get("block", "") if geocode else "",
                "preliminary_county_fips": prelim,
                "county_disagreement": int(bool(exact_county and prelim and exact_county != prelim)),
            }
            writer.writerow({field: output.get(field, "") for field in final_fields})

    print(f"Validated {len(exact)} official Census batch results against current inputs")

if __name__ == "__main__":
    main()
