from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path

BOROUGH_COUNTIES = {
    ("NY", "BRONX"): ("36005", "Bronx County"),
    ("NY", "BROOKLYN"): ("36047", "Kings County"),
    ("NY", "MANHATTAN"): ("36061", "New York County"),
    ("NY", "QUEENS"): ("36081", "Queens County"),
    ("NY", "STATEN ISLAND"): ("36085", "Richmond County"),
}

def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"\bST[.]?\b", "SAINT", value)
    value = re.sub(r"\bFT[.]?\b", "FORT", value)
    value = re.sub(r"\bMT[.]?\b", "MOUNT", value)
    value = re.sub(r"^CITY OF\s+", "", value)
    return re.sub(r"[^A-Z0-9]+", " ", value).strip()

def load_unique(path: Path, key_fields):
    output = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("county_fips"):
                continue
            key = tuple(row[field] for field in key_fields)
            output[key] = (row["county_fips"], row.get("county_name", ""))
    return output

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("address_csv", type=Path)
    parser.add_argument("place_crosswalk_csv", type=Path)
    parser.add_argument("zip_crosswalk_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()

    places = load_unique(args.place_crosswalk_csv, ("state", "place_name_norm"))
    zips = load_unique(args.zip_crosswalk_csv, ("zip",))
    fields = [
        "case_number", "county_fips", "county_name", "geocode_quality",
        "geocode_quality_label", "county_source", "city_name_norm",
        "has_street_address", "has_zip", "address_source", "street",
        "geocode_city", "geocode_state", "geocode_zip", "main_geo",
    ]
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.address_csv.open("r", encoding="utf-8-sig", newline="") as src, \
            args.output_csv.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            state = (row.get("geocode_state") or row.get("case_state") or "").upper()
            city = row.get("geocode_city") or row.get("case_city") or ""
            city_key = norm(city)
            zipcode = (row.get("geocode_zip") or "")[:5]
            county_fips = ""
            county_name = ""
            quality = 5
            label = "unmatched"
            source = ""

            if zipcode and (zipcode,) in zips:
                county_fips, county_name = zips[(zipcode,)]
                quality, label, source = 2, "zip_unique_county", "census_zcta_county"
            elif (state, city_key) in BOROUGH_COUNTIES:
                county_fips, county_name = BOROUGH_COUNTIES[(state, city_key)]
                quality, label, source = 3, "city_only_unique_county", "nyc_borough_crosswalk"
            elif (state, city_key) in places:
                county_fips, county_name = places[(state, city_key)]
                quality, label, source = 3, "city_only_unique_county", "census_place_county"
            elif city_key and state:
                quality, label, source = 4, "ambiguous", "city_state_unresolved"

            writer.writerow({
                "case_number": row["case_number"],
                "county_fips": county_fips,
                "county_name": county_name,
                "geocode_quality": quality,
                "geocode_quality_label": label,
                "county_source": source,
                "city_name_norm": city_key,
                "has_street_address": row.get("has_street_address", "0"),
                "has_zip": row.get("has_zip", "0"),
                "address_source": row.get("address_source", ""),
                "street": row.get("street", ""),
                "geocode_city": city,
                "geocode_state": state,
                "geocode_zip": zipcode,
                "main_geo": row.get("main_geo", "0"),
            })

if __name__ == "__main__":
    main()
