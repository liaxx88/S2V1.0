from __future__ import annotations

import argparse
import csv
import math
import re
import struct
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

FIPS_TO_STATE = {
    "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO",
    "09":"CT","10":"DE","11":"DC","12":"FL","13":"GA","15":"HI",
    "16":"ID","17":"IL","18":"IN","19":"IA","20":"KS","21":"KY",
    "22":"LA","23":"ME","24":"MD","25":"MA","26":"MI","27":"MN",
    "28":"MS","29":"MO","30":"MT","31":"NE","32":"NV","33":"NH",
    "34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND","39":"OH",
    "40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
    "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA",
    "54":"WV","55":"WI","56":"WY","60":"AS","66":"GU","69":"MP",
    "72":"PR","78":"VI",
}

def name_norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"\bST[.]?\b", "SAINT", value)
    value = re.sub(r"\bFT[.]?\b", "FORT", value)
    value = re.sub(r"\bMT[.]?\b", "MOUNT", value)
    value = re.sub(r"^CITY OF\s+", "", value)
    return re.sub(r"[^A-Z0-9]+", " ", value).strip()

def read_dbf(data: bytes):
    n_records = struct.unpack_from("<I", data, 4)[0]
    header_length = struct.unpack_from("<H", data, 8)[0]
    record_length = struct.unpack_from("<H", data, 10)[0]
    fields = []
    offset = 32
    while offset + 32 <= header_length and data[offset] != 0x0D:
        descriptor = data[offset : offset + 32]
        field_name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii", "ignore")
        fields.append((field_name, descriptor[16]))
        offset += 32

    rows = []
    for index in range(n_records):
        start = header_length + index * record_length
        record = data[start : start + record_length]
        if len(record) < record_length:
            break
        position = 1
        row = {}
        for field_name, length in fields:
            raw = record[position : position + length]
            row[field_name] = raw.decode("latin-1", "ignore").strip()
            position += length
        rows.append(row)
    return rows

def read_shp(data: bytes):
    shapes = []
    offset = 100
    while offset + 8 <= len(data):
        _record_number, content_words = struct.unpack_from(">II", data, offset)
        content_length = content_words * 2
        content = data[offset + 8 : offset + 8 + content_length]
        if len(content) < 4:
            break
        shape_type = struct.unpack_from("<I", content, 0)[0]
        if shape_type == 0:
            shapes.append({"bbox": (math.nan,) * 4, "rings": [], "ring_bboxes": []})
        elif shape_type in (5, 15, 25):
            bbox = struct.unpack_from("<4d", content, 4)
            n_parts, n_points = struct.unpack_from("<2I", content, 36)
            part_starts = list(struct.unpack_from(f"<{n_parts}I", content, 44))
            points_offset = 44 + 4 * n_parts
            points = [
                struct.unpack_from("<2d", content, points_offset + 16 * i)
                for i in range(n_points)
            ]
            part_starts.append(n_points)
            rings = [points[part_starts[i] : part_starts[i + 1]] for i in range(n_parts)]
            ring_bboxes = [
                (
                    min(point[0] for point in ring), min(point[1] for point in ring),
                    max(point[0] for point in ring), max(point[1] for point in ring),
                )
                for ring in rings if ring
            ]
            rings = [ring for ring in rings if ring]
            shapes.append({"bbox": bbox, "rings": rings, "ring_bboxes": ring_bboxes})
        else:
            raise ValueError(f"Unsupported shapefile shape type: {shape_type}")
        offset += 8 + content_length
    return shapes

def load_zipped_shapefile(path: Path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shp_name = next(name for name in names if name.lower().endswith(".shp"))
        dbf_name = next(name for name in names if name.lower().endswith(".dbf"))
        shapes = read_shp(archive.read(shp_name))
        rows = read_dbf(archive.read(dbf_name))
    if len(shapes) != len(rows):
        raise ValueError(f"Shape/attribute count mismatch in {path}: {len(shapes)} vs {len(rows)}")
    return [{**row, **shape} for row, shape in zip(rows, shapes)]

def bbox_overlaps(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])

def point_in_shape(point, shape):
    x, y = point
    if not (shape["bbox"][0] <= x <= shape["bbox"][2] and shape["bbox"][1] <= y <= shape["bbox"][3]):
        return False
    inside = False
    for ring, bbox in zip(shape["rings"], shape["ring_bboxes"]):
        if not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
            continue
        if len(ring) < 3:
            continue
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            crosses = (yi > y) != (yj > y)
            if crosses:
                x_at_y = (xj - xi) * (y - yi) / (yj - yi) + xi
                if x < x_at_y:
                    inside = not inside
            j = i
    return inside

def sampled_points(shape, limit=80, anchor=None):
    points = [point for ring in shape["rings"] for point in ring]
    if not points:
        return []
    step = max(1, len(points) // limit)
    sampled = points[::step]

    for ring in shape["rings"][:8]:
        if len(ring) >= 2:
            step_ring = max(1, len(ring) // 24)
            for i in range(0, len(ring) - 1, step_ring):
                sampled.append(((ring[i][0] + ring[i + 1][0]) / 2, (ring[i][1] + ring[i + 1][1]) / 2))
    if anchor is not None:

        

        weight = 0.002
        sampled = [
            (point[0] * (1 - weight) + anchor[0] * weight,
             point[1] * (1 - weight) + anchor[1] * weight)
            for point in sampled
        ]
    return sampled

def interior_grid_points(shape, grid_size=16):
    xmin, ymin, xmax, ymax = shape["bbox"]
    if not all(math.isfinite(value) for value in (xmin, ymin, xmax, ymax)):
        return []
    points = []
    for ix in range(grid_size):
        x = xmin + (ix + 0.5) * (xmax - xmin) / grid_size
        for iy in range(grid_size):
            y = ymin + (iy + 0.5) * (ymax - ymin) / grid_size
            point = (x, y)
            if point_in_shape(point, shape):
                points.append(point)
    return points

def required_place_keys(address_csv: Path):
    keys = set()
    with address_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            for city_field, state_field in (
                ("geocode_city", "geocode_state"), ("case_city", "case_state")
            ):
                state = (row.get(state_field) or "").upper()
                city = name_norm(row.get(city_field) or "")
                if state and city:
                    keys.add((state, city))
    return keys

def build_place_crosswalk(place_zip: Path, county_zip: Path, output_csv: Path, required_keys):
    counties = load_zipped_shapefile(county_zip)
    places = load_zipped_shapefile(place_zip)
    counties_by_state = defaultdict(list)
    county_names = {}
    for county in counties:
        statefp = county["STATEFP"]
        county_fips = county["GEOID"]
        counties_by_state[statefp].append(county)
        county_names[county_fips] = county.get("NAMELSAD") or county.get("NAME", "")

    name_counties = defaultdict(set)
    name_geoids = defaultdict(list)
    for place in places:
        statefp = place["STATEFP"]
        state = FIPS_TO_STATE.get(statefp, "")
        if not state:
            continue
        key = (state, name_norm(place.get("NAME", "")))
        if not key[1] or key not in required_keys:
            continue
        candidates = [
            county for county in counties_by_state[statefp]
            if bbox_overlaps(place["bbox"], county["bbox"])
        ]
        if len(candidates) == 1:
            overlaps = {candidates[0]["GEOID"]}
        else:
            probes = []
            anchor = None
            try:
                anchor = (float(place["INTPTLON"]), float(place["INTPTLAT"]))
                probes.append(anchor)
            except (KeyError, TypeError, ValueError):
                pass
            probes.extend(interior_grid_points(place))
            overlaps = {
                county["GEOID"]
                for county in candidates
                if any(point_in_shape(point, county) for point in probes)
            }
        name_counties[key].update(overlaps)
        name_geoids[key].append(place.get("GEOID", ""))

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "state", "place_name_norm", "place_entity_count", "county_count",
            "county_fips", "county_name", "place_geoids", "mapping_quality",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key in sorted(name_geoids):
            county_list = sorted(name_counties[key])
            unique = len(county_list) == 1
            writer.writerow({
                "state": key[0],
                "place_name_norm": key[1],
                "place_entity_count": len(name_geoids[key]),
                "county_count": len(county_list),
                "county_fips": county_list[0] if unique else "",
                "county_name": county_names.get(county_list[0], "") if unique else "",
                "place_geoids": ";".join(sorted(name_geoids[key])),
                "mapping_quality": "city_only_unique_county" if unique else "ambiguous",
            })

def build_zip_crosswalk(relationship_txt: Path, output_csv: Path):
    zip_counties = defaultdict(set)
    county_names = {}
    with relationship_txt.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="|"):
            zipcode = (row.get("GEOID_ZCTA5_20") or "").strip()
            county = (row.get("GEOID_COUNTY_20") or "").strip()
            if zipcode and county:
                zip_counties[zipcode].add(county)
                county_names[county] = (row.get("NAMELSAD_COUNTY_20") or "").strip()

    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        fields = ["zip", "county_count", "county_fips", "county_name", "mapping_quality"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for zipcode in sorted(zip_counties):
            counties = sorted(zip_counties[zipcode])
            unique = len(counties) == 1
            writer.writerow({
                "zip": zipcode,
                "county_count": len(counties),
                "county_fips": counties[0] if unique else "",
                "county_name": county_names.get(counties[0], "") if unique else "",
                "mapping_quality": "zip_unique_county" if unique else "ambiguous",
            })

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("place_zip", type=Path)
    parser.add_argument("county_zip", type=Path)
    parser.add_argument("zcta_county_txt", type=Path)
    parser.add_argument("place_output_csv", type=Path)
    parser.add_argument("zip_output_csv", type=Path)
    parser.add_argument("address_candidates_csv", type=Path)
    args = parser.parse_args()
    keys = required_place_keys(args.address_candidates_csv)
    build_place_crosswalk(args.place_zip, args.county_zip, args.place_output_csv, keys)
    build_zip_crosswalk(args.zcta_county_txt, args.zip_output_csv)
    print(f"Wrote {args.place_output_csv}")
    print(f"Wrote {args.zip_output_csv}")

if __name__ == "__main__":
    main()
