from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

STATE_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL",
    "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY",
    "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN",
    "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY",
}
STATE_ABBRS = set(STATE_NAMES.values())
STATE_TOKEN = "|".join(sorted((*STATE_NAMES.keys(), *STATE_ABBRS), key=len, reverse=True))

SUFFIX = (
    r"STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|DRIVE|DR|LANE|LN|"
    r"HIGHWAY|HWY|PARKWAY|PKWY|COURT|CT|PLACE|PL|WAY|CIRCLE|CIR|"
    r"TRAIL|TRL|TERRACE|TER|PIKE|TURNPIKE|EXPRESSWAY|EXPY|PLAZA|PLZ"
)
NUMBER_START = re.compile(r"(?<![A-Z0-9])\d{1,6}(?:-\d{1,6})?[A-Z]?(?=\s)", re.I)
STREET_FROM_START = re.compile(
    rf"\d{{1,6}}(?:-\d{{1,6}})?[A-Z]?"
    rf"(?:\s+(?:NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST|SOUTHEAST|SOUTHWEST|"
    rf"N|S|E|W|NE|NW|SE|SW)\.?)?"
    rf"(?:\s+[A-Z0-9][A-Z0-9.'#&/\-]*){{1,8}}\s+(?:{SUFFIX})\.?"
    rf"(?:\s+(?:NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST|SOUTHEAST|SOUTHWEST|"
    rf"N|S|E|W|NE|NW|SE|SW)\.?)?"
    rf"(?:\s+(?:SUITE|STE|UNIT|BLDG|BUILDING|FLOOR|FL)\s*[A-Z0-9\-]+)?",
    re.I,
)
ROUTE_FROM_START = re.compile(
    r"\d{1,6}(?:-\d{1,6})?[A-Z]?\s+(?:(?:US|U\.S\.|STATE|COUNTY)\s+)?"
    r"(?:HIGHWAY|HWY|ROUTE|RTE)\s+\d{1,4}[A-Z]?",
    re.I,
)
SUFFIXLESS_FROM_START = re.compile(
    rf"\d{{1,6}}(?:-\d{{1,6}})?[A-Z]?"
    rf"(?:\s+[A-Z0-9][A-Z0-9.'#&/\-]*){{1,8}}"
    rf"(?=,\s*[^,;]{{2,55}},?\s+(?:{STATE_TOKEN})(?:\s+\d{{5}})?\b)",
    re.I,
)
ZIP_RE = re.compile(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)")
FALSE_ADDRESS_WORDS = re.compile(
    r"\b(EMPLOYEE|EMPLOYEES|WORKER|WORKERS|VOTER|VOTERS|DRIVER|DRIVERS|"
    r"MEMBER|MEMBERS|FULL-TIME|PART-TIME|LOCATED|FACILITY|FACILITIES)\b",
    re.I,
)

def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" ,;:-")

def normalize_state(value: str) -> str:
    upper = clean(value).upper().replace(".", "")
    return STATE_NAMES.get(upper, upper if upper in STATE_ABBRS else "")

def street_candidates(text: str):
    upper = clean(text).upper()
    if not upper or "P.O. BOX" in upper or "PO BOX" in upper:
        return
    for start in NUMBER_START.finditer(upper):
        match = STREET_FROM_START.match(upper, start.start())
        if match is None:
            match = ROUTE_FROM_START.match(upper, start.start())
        if match is None:
            match = SUFFIXLESS_FROM_START.match(upper, start.start())
        if match is None:
            continue
        candidate = clean(match.group(0))
        if FALSE_ADDRESS_WORDS.search(candidate):
            continue
        yield candidate, match.start(), match.end(), upper

def parsed_city_state_zip(text: str, street_end: int, default_city: str, default_state: str):
    tail = text[street_end : street_end + 180]
    state_pattern = re.compile(
        rf",?\s*([^,;]{{2,55}}?),?\s+({STATE_TOKEN})"
        rf"(?:\s*,?\s+(\d{{5}})(?:-\d{{4}})?)?"
        rf"(?=\s*(?:[,;.]|LOCATION\b|FACILIT(?:Y|IES)\b|WORK\s*SITE\b|"
        rf"WORKSITE\b|PREMISES\b|PLANT\b|OFFICE\b|$))",
        re.I,
    )
    city = clean(default_city)
    state = normalize_state(default_state)
    zipcode = ""
    match = state_pattern.search(tail)
    if match:
        parsed_city = clean(match.group(1))
        parsed_state = normalize_state(match.group(2))

        
        if not state or parsed_state == state:
            if parsed_city and not re.search(r"\b(INCLUDED|EXCLUDED|EMPLOYEE|WORKER)\b", parsed_city, re.I):
                city = parsed_city
            if parsed_state:
                state = parsed_state
            if match.group(3):
                zipcode = match.group(3)[:5]
    return city, state, zipcode

def parse_source(text: str, default_city: str, default_state: str):
    for street, _start, end, normalized in street_candidates(text):
        city, state, zipcode = parsed_city_state_zip(
            normalized, end, default_city, default_state
        )
        return {
            "street": street.title(),
            "geocode_city": city.title(),
            "geocode_state": state,
            "geocode_zip": zipcode,
        }
    return None

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()

    source_fields = [
        ("voting_unit_a", 1), ("voting_unit_b", 2),
        ("voting_unit_c", 3), ("voting_unit_d", 4),
        ("unit_sought_raw", 5),
    ]
    cases: dict[str, dict] = {}

    with args.input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            case_number = clean(row.get("case_number")).upper()
            if not case_number:
                continue
            case = cases.setdefault(
                case_number,
                {
                    "case_number": case_number,
                    "case_city": clean(row.get("city")),
                    "case_state": normalize_state(row.get("state", "")),
                    "main_geo": row.get("main_geo", "0"),
                    "candidates": [],
                    "fallback_sources": [],
                },
            )
            for field, priority in source_fields:
                text = clean(row.get(field))
                if not text:
                    continue
                case["fallback_sources"].append(
                    (priority, clean(row.get("unit_id")), field, text)
                )
                parsed = parse_source(text, case["case_city"], case["case_state"])
                if parsed:
                    parsed.update(
                        {
                            "address_source": field,
                            "source_priority": priority,
                            "source_unit_id": clean(row.get("unit_id")),
                            "source_text": text,
                        }
                    )
                    case["candidates"].append(parsed)

    output_fields = [
        "case_number", "case_city", "case_state", "main_geo", "street",
        "geocode_city", "geocode_state", "geocode_zip", "address_source",
        "source_priority", "source_unit_id", "has_street_address", "has_zip",
        "address_candidate_count", "source_text",
    ]
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        for case_number in sorted(cases):
            case = cases[case_number]
            candidates = case["candidates"]
            candidates.sort(
                key=lambda item: (
                    item["source_priority"],
                    0 if item["geocode_zip"] else 1,
                    item["source_unit_id"],
                    item["street"],
                )
            )
            if candidates:
                best = candidates[0]
                output = {
                    **{k: case[k] for k in ("case_number", "case_city", "case_state", "main_geo")},
                    **best,
                    "has_street_address": 1,
                    "has_zip": int(bool(best["geocode_zip"])),
                    "address_candidate_count": len(candidates),
                }
            else:
                fallback_sources = sorted(set(case["fallback_sources"]))
                fallback = fallback_sources[0] if fallback_sources else (9, "", "city_state_fallback", "")
                output = {
                    **{k: case[k] for k in ("case_number", "case_city", "case_state", "main_geo")},
                    "street": "",
                    "geocode_city": case["case_city"],
                    "geocode_state": case["case_state"],
                    "geocode_zip": "",
                    "address_source": fallback[2],
                    "source_priority": fallback[0],
                    "source_unit_id": fallback[1],
                    "has_street_address": 0,
                    "has_zip": 0,
                    "address_candidate_count": 0,
                    "source_text": fallback[3],
                }
            writer.writerow({field: output.get(field, "") for field in output_fields})

if __name__ == "__main__":
    main()
