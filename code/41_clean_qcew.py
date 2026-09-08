from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

USECOLS = [
    "area_fips", "own_code", "industry_code", "agglvl_code", "year", "qtr",
    "disclosure_code", "qtrly_estabs", "month1_emplvl", "month2_emplvl",
    "month3_emplvl", "total_qtrly_wages", "avg_wkly_wage",
]
EXCLUDED = {"11", "481", "482", "814"}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def clean_code(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()

def read_year(path: Path, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = []
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected one CSV in {path}, found {names}")
        with archive.open(names[0]) as raw:
            for chunk in pd.read_csv(raw, dtype=str, usecols=USECOLS, chunksize=250_000,
                                     keep_default_na=False):
                for column in ("area_fips", "own_code", "industry_code", "agglvl_code"):
                    chunk[column] = clean_code(chunk[column])
                county = chunk["area_fips"].str.fullmatch(r"\d{5}") & ~chunk["area_fips"].str.endswith("000")
                private = chunk["own_code"].eq("5")
                total = chunk["agglvl_code"].eq("71") & chunk["industry_code"].eq("10")
                excluded = (
                    (chunk["agglvl_code"].eq("74") & chunk["industry_code"].eq("11"))
                    | (chunk["agglvl_code"].eq("75") & chunk["industry_code"].isin({"481", "482", "814"}))
                )
                keep = county & private & (total | excluded)
                if keep.any():
                    selected.append(chunk.loc[keep].copy())
    if not selected:
        raise ValueError(f"No required county-private rows in {path}")
    data = pd.concat(selected, ignore_index=True)
    if not clean_code(data["year"]).eq(str(year)).all():
        raise ValueError(f"Year mismatch in {path}")
    data["qtr"] = pd.to_numeric(data["qtr"], errors="raise").astype(int)
    for column in ("qtrly_estabs", "month1_emplvl", "month2_emplvl", "month3_emplvl",
                   "total_qtrly_wages", "avg_wkly_wage"):
        data[column] = pd.to_numeric(data[column], errors="coerce")

    total = data[data["agglvl_code"].eq("71") & data["industry_code"].eq("10")].copy()
    if total.duplicated(["area_fips", "qtr"]).any():
        raise ValueError(f"Duplicate county-quarter private totals in {path}")
    total = total.rename(columns={
        "area_fips": "county_fips", "qtrly_estabs": "private_establishments",
        "avg_wkly_wage": "avg_weekly_wage", "total_qtrly_wages": "total_quarterly_wages",
    })

    excluded = data[~(data["agglvl_code"].eq("71") & data["industry_code"].eq("10"))].copy()
    excluded["suppressed"] = excluded["disclosure_code"].str.strip().eq("N")
    monthly = []
    for month_in_quarter in (1, 2, 3):
        month = (total["qtr"] - 1) * 3 + month_in_quarter
        block = total[["county_fips", "qtr", "private_establishments", "avg_weekly_wage",
                       "total_quarterly_wages"]].copy()
        block["year"] = year
        block["month"] = month.astype(int)
        block["private_employment"] = total[f"month{month_in_quarter}_emplvl"].to_numpy()

        ex = excluded[["area_fips", "qtr", "industry_code", "disclosure_code", "suppressed",
                       f"month{month_in_quarter}_emplvl"]].copy()
        ex = ex.rename(columns={"area_fips": "county_fips",
                                f"month{month_in_quarter}_emplvl": "excluded_employment"})
        ex["excluded_employment"] = pd.to_numeric(ex["excluded_employment"], errors="coerce")
        ex_group = ex.groupby(["county_fips", "qtr"], as_index=False).agg(
            excluded_employment_observed=("excluded_employment", lambda x: x.sum(min_count=1)),
            excluded_suppressed_cells=("suppressed", "sum"),
            excluded_published_cells=("industry_code", "size"),
        )
        block = block.merge(ex_group, on=["county_fips", "qtr"], how="left", validate="one_to_one")
        block["excluded_employment_observed"] = block["excluded_employment_observed"].fillna(0)
        block["excluded_suppressed_cells"] = block["excluded_suppressed_cells"].fillna(0).astype(int)
        block["excluded_published_cells"] = block["excluded_published_cells"].fillna(0).astype(int)
        block["nlra_proxy_complete"] = block["excluded_suppressed_cells"].eq(0)
        block["nlra_proxy_employment"] = (
            block["private_employment"] - block["excluded_employment_observed"]
        ).where(block["nlra_proxy_complete"])
        block["nlra_proxy_employment_partial"] = (
            block["private_employment"] - block["excluded_employment_observed"]
        )
        block["source_year"] = year
        monthly.append(block)
    monthly_frame = pd.concat(monthly, ignore_index=True)
    monthly_frame = monthly_frame[[
        "county_fips", "year", "month", "private_employment", "nlra_proxy_employment",
        "nlra_proxy_employment_partial", "nlra_proxy_complete", "private_establishments",
        "avg_weekly_wage", "total_quarterly_wages", "excluded_employment_observed",
        "excluded_suppressed_cells", "excluded_published_cells", "source_year",
    ]]
    monthly_frame["state_fips"] = monthly_frame["county_fips"].str[:2]
    ordered_columns = [
        "county_fips", "state_fips", "year", "month", "private_employment",
        "nlra_proxy_employment", "nlra_proxy_employment_partial", "nlra_proxy_complete",
        "private_establishments", "avg_weekly_wage", "total_quarterly_wages",
        "excluded_employment_observed", "excluded_suppressed_cells",
        "excluded_published_cells", "source_year",
    ]
    monthly_frame = monthly_frame[ordered_columns]

    audit = pd.DataFrame([{
        "year": year,
        "county_month_rows": len(monthly_frame),
        "unique_counties": monthly_frame["county_fips"].nunique(),
        "private_employment_complete_rate_pct": round(100 * monthly_frame["private_employment"].notna().mean(), 4),
        "nlra_proxy_complete_rate_pct": round(100 * monthly_frame["nlra_proxy_employment"].notna().mean(), 4),
        "nlra_proxy_partial_positive_rate_pct": round(
            100 * monthly_frame["nlra_proxy_employment_partial"].gt(0).mean(), 4
        ),
        "suppressed_exclusion_cells": int(monthly_frame["excluded_suppressed_cells"].sum()),
        "raw_zip_bytes": path.stat().st_size,
        "raw_zip_sha256": sha256(path),
    }])
    return monthly_frame, audit

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

    raw_dir = root / "data" / "raw" / "qcew" / "quarterly_singlefile"
    clean_dir = root / "data" / "clean" / "qcew"
    audit_dir = root / "data" / "clean" / "results"
    clean_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    annual_dir = clean_dir / "annual_cache"
    annual_dir.mkdir(parents=True, exist_ok=True)
    output = clean_dir / "qcew_county_month_private.parquet"
    audit_output = audit_dir / "qcew_county_month_audit.csv"
    manifest_output = clean_dir / "qcew_county_month_private_manifest.json"

    frames, audits = [], []
    for year in range(2010, 2025):
        path = raw_dir / f"{year}_qtrly_singlefile.zip"
        if not path.exists():
            raise FileNotFoundError(path)
        annual_path = annual_dir / f"qcew_county_month_private_{year}.parquet"
        annual_audit_path = annual_dir / f"qcew_county_month_audit_{year}.csv"
        if annual_path.exists() and annual_audit_path.exists():
            frame = pd.read_parquet(annual_path)
            audit = pd.read_csv(annual_audit_path)
            expected_hash = audit.loc[0, "raw_zip_sha256"]
            if sha256(path) != expected_hash:
                raise RuntimeError(f"Cached QCEW year {year} does not match immutable raw ZIP")
            audit["nlra_proxy_partial_positive_rate_pct"] = round(
                100 * frame["nlra_proxy_employment_partial"].gt(0).mean(), 4
            )
        else:
            frame, audit = read_year(path, year)
            frame.to_parquet(annual_path, index=False, compression="zstd")
            audit.to_csv(annual_audit_path, index=False, encoding="utf-8", lineterminator="\n")
        frames.append(frame)
        audits.append(audit)
        print(f"QCEW clean: {year} ({len(frame):,} county-month rows)", flush=True)
    result = pd.concat(frames, ignore_index=True).sort_values(["county_fips", "year", "month"])
    if result.duplicated(["county_fips", "year", "month"]).any():
        raise ValueError("QCEW clean output is not unique by county_fips x year x month")
    if not result["month"].between(1, 12).all():
        raise ValueError("Invalid QCEW month")

    table = pa.Table.from_pandas(result, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata.update({
        b"source": b"BLS QCEW NAICS quarterly singlefiles 2010-2024",
        b"broad_private": b"own_code=5; agglvl_code=71; industry_code=10",
        b"nlra_proxy": b"broad private minus NAICS 11, 481, 482, and 814; exact proxy missing if an exclusion cell is suppressed; partial proxy subtracts all published cells",
    })
    temp = output.with_suffix(".parquet.tmp")
    pq.write_table(table.replace_schema_metadata(metadata), temp, compression="zstd")
    temp.replace(output)
    audit = pd.concat(audits, ignore_index=True)
    audit.to_csv(audit_output, index=False, encoding="utf-8", lineterminator="\n")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output": output.relative_to(root).as_posix(), "output_sha256": sha256(output),
        "rows": len(result), "unique_counties": result["county_fips"].nunique(),
        "years": [2010, 2024],
    }
    manifest_output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(result):,} unique county-month rows to {output}")

if __name__ == "__main__":
    main()
