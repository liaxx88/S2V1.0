from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

VARIABLES = ("tmax", "tmin", "prcp")
VALUE_NAMES = {"tmax": "tmax_c", "tmin": "tmin_c", "prcp": "prcp_mm"}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

def load_state_crosswalk(path: Path) -> dict[str, str]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame.columns = [normalize_header(column) for column in frame.columns]
    ncei_candidates = [column for column in frame if "ncei" in column and "code" in column]
    fips_candidates = [column for column in frame if "fips" in column and "code" in column]
    if not ncei_candidates or not fips_candidates:
        raise ValueError(f"Cannot identify NCEI/FIPS columns in {path}: {list(frame.columns)}")
    ncei_col, fips_col = ncei_candidates[0], fips_candidates[0]
    crosswalk = {
        str(ncei).strip().zfill(2): str(fips).strip().zfill(2)
        for ncei, fips in zip(frame[ncei_col], frame[fips_col]) if str(ncei).strip() and str(fips).strip()
    }
    if len(crosswalk) < 48:
        raise ValueError(f"Incomplete NCEI-to-FIPS state crosswalk ({len(crosswalk)} rows)")
    return crosswalk

def load_manual_crosswalk(path: Path) -> pd.DataFrame:
    required = ["source_county_fips", "target_county_fips", "start_date", "end_date",
                "reason", "source_url", "active"]
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(frame.columns) != required:
        raise ValueError(f"Manual county crosswalk schema must be {required}")
    if frame.empty:
        return frame
    frame = frame[frame["active"].str.strip().str.lower().isin({"1", "true", "yes"})].copy()
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="raise")
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="raise")
    return frame

def read_month(path: Path, variable: str, year: int, month: int,
               state_map: dict[str, str], manual: pd.DataFrame) -> pd.DataFrame:

    

    raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False,
                      encoding="utf-8-sig")
    if raw.shape[1] != 37:
        raise ValueError(f"Expected 37 columns in {path}, found {raw.shape[1]}")
    if not raw[0].str.strip().str.lower().eq("cty").all():
        raise ValueError(f"Non-county row in {path}")
    metadata_ok = (
        pd.to_numeric(raw[3], errors="raise").eq(year)
        & pd.to_numeric(raw[4], errors="raise").eq(month)
        & raw[5].str.strip().str.lower().eq(variable)
    )
    if not metadata_ok.all():
        raise ValueError(f"Metadata mismatch in {path}")

    region_code = raw[1].str.strip().str.zfill(5)
    ncei_state = region_code.str[:2]
    unmapped = sorted(set(ncei_state) - set(state_map))
    if unmapped:
        raise ValueError(f"Unmapped NCEI state codes {unmapped} in {path}")
    county_fips = ncei_state.map(state_map) + region_code.str[2:]
    values = raw.iloc[:, 6:].astype(np.float32).to_numpy().reshape(-1)
    days = np.tile(np.arange(1, 32, dtype=np.int8), len(raw))
    dates = pd.to_datetime({
        "year": np.full(len(values), year, dtype=np.int16),
        "month": np.full(len(values), month, dtype=np.int8),
        "day": days,
    }, errors="coerce")
    invalid = dates.isna()
    if np.any(values[invalid] != -999.99):
        bad_days = np.unique(days[invalid & (values != -999.99)]).tolist()
        raise ValueError(f"Nonmissing value on nonexistent dates in {path}: days {bad_days}")
    keep = ~invalid
    values[values == -999.99] = np.nan
    frame = pd.DataFrame({
        "county_fips": np.repeat(county_fips.to_numpy(), 31)[keep],
        "noaa_region_code": np.repeat(region_code.to_numpy(), 31)[keep],
        "county_name_noaa": np.repeat(raw[2].str.strip().to_numpy(), 31)[keep],
        "date": dates[keep],
        VALUE_NAMES[variable]: values[keep],
    })
    if not manual.empty:
        for rule in manual.itertuples(index=False):
            mask = (frame["county_fips"].eq(rule.source_county_fips)
                    & frame["date"].between(rule.start_date, rule.end_date))
            frame.loc[mask, "county_fips"] = rule.target_county_fips
    if frame.duplicated(["county_fips", "date"]).any():
        duplicates = frame.loc[frame.duplicated(["county_fips", "date"], keep=False),
                               ["county_fips", "date"]].head().to_dict("records")
        raise ValueError(f"Duplicate county-date after crosswalk in {path}: {duplicates}")
    return frame

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    vendor = root / "code" / "vendor" / "python"
    if vendor.exists():
        sys.path.insert(0, str(vendor))
    import pyarrow as pa
    import pyarrow.parquet as pq

    raw = root / "data" / "raw" / "noaa" / "nclimgrid_daily"
    clean = root / "data" / "clean" / "noaa"
    audit_dir = root / "data" / "clean" / "results"
    clean.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    state_map = load_state_crosswalk(raw / "documentation" / "us-state-codes_ncei-to-fips.csv")
    manual_path = raw.parent / "county_crosswalk_manual.csv"
    manual = load_manual_crosswalk(manual_path)

    output = clean / "noaa_county_daily_1981_2024.parquet"
    temp_output = output.with_suffix(".parquet.tmp")
    audit_output = audit_dir / "weather_audit_by_year.csv"
    manifest_output = clean / "noaa_county_daily_1981_2024_manifest.json"
    if temp_output.exists():
        temp_output.unlink()
    writer = None
    audit_rows = []
    total_rows = 0
    input_hashes = {}
    try:
        for year in range(1981, 2025):
            year_rows = 0
            year_counties = set()
            missing = {"tmax_c": 0, "tmin_c": 0, "prcp_mm": 0}
            days_by_county: dict[str, int] = {}
            for month in range(1, 13):
                frames = []
                for variable in VARIABLES:
                    filename = f"{variable}-{year}{month:02d}-cty-scaled.csv"
                    path = raw / "county_scaled" / str(year) / filename
                    if not path.exists():
                        raise FileNotFoundError(path)
                    input_hashes[path.relative_to(root).as_posix()] = sha256(path)
                    frames.append(read_month(path, variable, year, month, state_map, manual))
                monthly = frames[0]
                monthly = monthly.merge(
                    frames[1][["county_fips", "date", "tmin_c"]],
                    on=["county_fips", "date"], how="outer", validate="one_to_one"
                ).merge(
                    frames[2][["county_fips", "date", "prcp_mm"]],
                    on=["county_fips", "date"], how="outer", validate="one_to_one"
                )
                monthly = monthly.sort_values(["county_fips", "date"]).reset_index(drop=True)
                monthly["year"] = monthly["date"].dt.year.astype(np.int16)
                monthly["month"] = monthly["date"].dt.month.astype(np.int8)
                monthly["day"] = monthly["date"].dt.day.astype(np.int8)
                monthly["doy"] = monthly["date"].dt.dayofyear.astype(np.int16)
                monthly["state_fips"] = monthly["county_fips"].str[:2]
                monthly["tmax_f"] = monthly["tmax_c"] * 9 / 5 + 32
                monthly["tmin_f"] = monthly["tmin_c"] * 9 / 5 + 32
                for column in ("tmax_c", "tmax_f", "tmin_c", "tmin_f", "prcp_mm"):
                    monthly[column] = monthly[column].astype(np.float32)
                monthly["date"] = monthly["date"].dt.date
                monthly = monthly[[
                    "county_fips", "state_fips", "date", "year", "month", "day", "doy",
                    "tmax_c", "tmax_f", "tmin_c", "tmin_f", "prcp_mm",
                    "noaa_region_code", "county_name_noaa",
                ]]
                table = pa.Table.from_pandas(monthly, preserve_index=False)
                if writer is None:
                    metadata = dict(table.schema.metadata or {})
                    metadata.update({
                        b"source": b"NOAA nClimGrid-Daily v1 county scaled area averages",
                        b"coverage": b"1981-01-01 through 2024-12-31",
                        b"missing_rule": b"-999.99 converted to null; nonexistent dates dropped",
                        b"state_crosswalk": b"official us-state-codes_ncei-to-fips.csv",
                    })
                    table = table.replace_schema_metadata(metadata)
                    writer = pq.ParquetWriter(temp_output, table.schema, compression="zstd",
                                              use_dictionary=["county_fips", "state_fips",
                                                              "noaa_region_code", "county_name_noaa"])
                writer.write_table(table)
                year_rows += len(monthly)
                total_rows += len(monthly)
                year_counties.update(monthly["county_fips"].unique())
                counts = monthly.groupby("county_fips").size()
                for county_fips, count in counts.items():
                    days_by_county[county_fips] = days_by_county.get(county_fips, 0) + int(count)
                for column in missing:
                    missing[column] += int(monthly[column].isna().sum())
            expected_days = 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
            audit_rows.append({
                "year": year, "county_day_rows": year_rows, "unique_counties": len(year_counties),
                "expected_days_per_county": expected_days,
                "min_days_per_county": min(days_by_county.values()),
                "max_days_per_county": max(days_by_county.values()),
                "counties_with_expected_days": sum(value == expected_days for value in days_by_county.values()),
                "tmax_missing_rate_pct": round(100 * missing["tmax_c"] / year_rows, 6),
                "tmin_missing_rate_pct": round(100 * missing["tmin_c"] / year_rows, 6),
                "prcp_missing_rate_pct": round(100 * missing["prcp_mm"] / year_rows, 6),
                "unique_county_date": True,
            })
            print(f"NOAA clean: {year} ({year_rows:,} county-day rows)", flush=True)
    finally:
        if writer is not None:
            writer.close()
    os.replace(temp_output, output)
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(audit_output, index=False, encoding="utf-8", lineterminator="\n")
    parquet = pq.ParquetFile(output)
    if parquet.metadata.num_rows != total_rows:
        raise ValueError("NOAA Parquet row count mismatch")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output": output.relative_to(root).as_posix(), "output_sha256": sha256(output),
        "rows": total_rows, "row_groups": parquet.metadata.num_row_groups,
        "years": [1981, 2024], "variables": list(VARIABLES),
        "state_crosswalk_sha256": sha256(raw / "documentation" / "us-state-codes_ncei-to-fips.csv"),
        "manual_county_crosswalk_sha256": sha256(manual_path),
        "input_file_count": len(input_hashes),
    }
    manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {total_rows:,} unique county-day rows to {output}")

if __name__ == "__main__":
    main()
