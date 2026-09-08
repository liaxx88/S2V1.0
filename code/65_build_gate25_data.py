from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import pyarrow as pa
import pyarrow.parquet as pq

RUCC_URL = (
    "https://gisportal.ers.usda.gov/server/rest/services/"
    "Rural_Atlas_Data/County_Classifications/MapServer/0/query"
)

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def download_rucc(raw_path: Path) -> dict:
    if raw_path.exists():
        return json.loads(raw_path.read_text(encoding="utf-8"))
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "FIPSTXT,State,County,RuralUrbanContinuumCode2013",
            "returnGeometry": "false",
            "orderByFields": "FIPSTXT",
            "resultOffset": str(offset),
            "resultRecordCount": "2000",
            "f": "json",
        }
        url = RUCC_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=120) as response:
            page = json.load(response)
        if "error" in page:
            raise RuntimeError(f"USDA ERS ArcGIS error: {page['error']}")
        page_features = page.get("features", [])
        features.extend(page_features)
        if not page.get("exceededTransferLimit", False) or not page_features:
            break
        offset += len(page_features)
    payload = {
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": RUCC_URL,
        "source_agency": "USDA Economic Research Service",
        "classification": "2013 Rural-Urban Continuum Codes",
        "features": features,
    }
    temp = raw_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, raw_path)
    return payload

REGION_BY_STATE = {

    **{fips: "Northeast" for fips in ("09", "23", "25", "33", "44", "50", "34", "36", "42")},

    **{fips: "Midwest" for fips in ("18", "17", "26", "39", "55", "19", "20", "27", "29", "31", "38", "46")},

    **{fips: "South" for fips in ("10", "11", "12", "13", "24", "37", "45", "51", "54", "01", "21", "28", "47", "05", "22", "40", "48")},

    **{fips: "West" for fips in ("04", "08", "16", "35", "30", "49", "32", "56", "02", "06", "15", "41", "53")},
}

def weighted_average(group: pd.DataFrame, value: str, weight: str) -> float:
    valid = group[value].notna() & group[weight].gt(0)
    if not valid.any():
        return np.nan
    return float(np.average(group.loc[valid, value], weights=group.loc[valid, weight]))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    vendor = root / "code" / "vendor" / "python"
    if vendor.exists():
        sys.path.insert(0, str(vendor))

    gate2 = root / "data" / "clean" / "gate2"
    gate25 = root / "data" / "clean" / "gate25"
    audit = root / "data" / "clean" / "results"
    raw_path = root / "data" / "raw" / "usda" / "rucc2013_arcgis_raw.json"
    gate25.mkdir(parents=True, exist_ok=True)
    source = gate2 / "county_week_analysis_v1.parquet"
    panel = pd.read_parquet(source)
    panel["week_start"] = pd.to_datetime(panel["week_start"])
    sample = panel.loc[panel["analysis_sample"].astype(bool)].copy()
    if len(sample) != 2_260_083:
        raise ValueError(f"Analysis-sample count changed: {len(sample):,}")

    cm_sum = sample.groupby("county_month_fe")["rc_petition_count"].transform("sum")
    sample["county_month_positive"] = cm_sum.gt(0)
    sw_sum = sample.groupby("state_yearweek_fe")["rc_petition_count"].transform("sum")
    sample["state_week_positive"] = sw_sum.gt(0)
    sample["after_county_month"] = sample["county_month_positive"]
    sample["prefilter_core"] = sample["county_month_positive"] & sample["state_week_positive"]
    if not np.array_equal(sample["prefilter_core"].to_numpy(), sample["ppml_core_sample"].astype(bool).to_numpy()):
        raise ValueError("Reconstructed support does not equal frozen ppml_core_sample")
    if sample.loc[sample["prefilter_core"], "rc_petition_count"].sum() != sample["rc_petition_count"].sum():
        raise ValueError("Support restriction removed positive petition counts")

    stage_masks = [
        ("Analysis panel", np.ones(len(sample), dtype=bool)),
        ("County x month-of-year positive-outcome support", sample["after_county_month"].to_numpy()),
        ("Plus state x exact-week positive-outcome support", sample["prefilter_core"].to_numpy()),
    ]
    stages = []
    for order, (label, mask) in enumerate(stage_masks, 1):
        part = sample.loc[mask]
        stages.append({
            "stage_order": order,
            "specification": label,
            "initial_n": len(sample),
            "retained_n": len(part),
            "retained_pct": 100 * len(part) / len(sample),
            "positive_outcome_rows": int(part["any_rc_petition"].sum()),
            "petition_count": int(part["rc_petition_count"].sum()),
            "counties": int(part["county_fips"].nunique()),
        })
    pd.DataFrame(stages).to_csv(
        audit / "gate25_separation_stages_pre_stata.csv", index=False, lineterminator="\n"
    )

    rucc_payload = download_rucc(raw_path)
    rucc_rows = [feature.get("attributes", {}) for feature in rucc_payload["features"]]
    rucc = pd.DataFrame(rucc_rows)
    rucc = rucc.rename(columns={
        "FIPSTXT": "county_fips",
        "RuralUrbanContinuumCode2013": "rucc2013",
        "State": "rucc_state",
        "County": "rucc_county",
    })
    rucc["county_fips"] = rucc["county_fips"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    rucc["rucc2013"] = pd.to_numeric(rucc["rucc2013"], errors="coerce")
    rucc = rucc.drop_duplicates("county_fips")
    sample = sample.merge(rucc, on="county_fips", how="left", validate="many_to_one")
    sample["metro2013"] = np.where(
        sample["rucc2013"].between(1, 3), 1,
        np.where(sample["rucc2013"].between(4, 9), 0, np.nan),
    )
    sample["region"] = sample["state_fips"].map(REGION_BY_STATE).fillna("Unclassified")
    county_activity = sample.groupby("county_fips").agg(
        county_petitions_2011_2024=("rc_petition_count", "sum"),
        county_positive_weeks=("any_rc_petition", "sum"),
    )
    sample = sample.join(county_activity, on="county_fips")
    sample["county_ever_petition"] = sample["county_petitions_2011_2024"].gt(0).astype(np.int8)
    sample["retention_status"] = np.where(sample["prefilter_core"], "Retained", "Excluded")

    comparisons = []
    for label, part in sample.groupby("retention_status", sort=False):
        comparisons.append({
            "retention_status": label,
            "observations": len(part),
            "counties": part["county_fips"].nunique(),
            "positive_outcome_rows": int(part["any_rc_petition"].sum()),
            "petition_count": int(part["rc_petition_count"].sum()),
            "mean_p95_days_lag1_4": part["p95_days_lag1_4"].mean(),
            "mean_private_emp_lag12": part["private_emp_lag12"].mean(),
            "median_private_emp_lag12": part["private_emp_lag12"].median(),
            "mean_county_petitions_2011_2024": part["county_petitions_2011_2024"].mean(),
            "share_county_ever_petition": part["county_ever_petition"].mean(),
            "share_metro_2013": part["metro2013"].mean(),
            "rucc_matched_pct": 100 * part["rucc2013"].notna().mean(),
        })
    pd.DataFrame(comparisons).to_csv(
        audit / "gate25_retained_dropped_comparison.csv", index=False, lineterminator="\n"
    )

    for dimension, filename in (("region", "gate25_retention_by_region.csv"),
                                ("metro2013", "gate25_retention_by_metro.csv")):
        rows = []
        for (status, category), part in sample.groupby(["retention_status", dimension], dropna=False):
            rows.append({
                "retention_status": status,
                dimension: category,
                "observations": len(part),
                "observation_share_pct": 100 * len(part) / len(sample),
                "counties": part["county_fips"].nunique(),
                "mean_p95_days_lag1_4": part["p95_days_lag1_4"].mean(),
                "mean_private_emp_lag12": part["private_emp_lag12"].mean(),
                "petition_count": int(part["rc_petition_count"].sum()),
            })
        pd.DataFrame(rows).to_csv(audit / filename, index=False, lineterminator="\n")

    flags = sample[[
        "county_fips", "week_start", "county_month_positive", "state_week_positive",
        "prefilter_core", "region", "rucc2013", "metro2013",
        "county_petitions_2011_2024", "county_positive_weeks",
    ]].copy()
    flag_path = gate25 / "gate25_separation_flags.parquet"
    pq.write_table(pa.Table.from_pandas(flags, preserve_index=False), flag_path, compression="zstd")

    heat_vars = [
        "p95_days_lag1_4", "p95_days_cumulative_1_16", "p95_days_cumulative_1_24",
        "p90_days_lag1_4", "p99_days_lag1_4", "days95f_lag1_4",
    ]
    rows = []
    for (state_fips, week_start), group in sample.groupby(["state_fips", "week_start"], sort=True):
        row = {
            "state_fips": state_fips,
            "week_start": week_start,
            "rc_petition_count": int(group["rc_petition_count"].sum()),
            "state_private_emp_lag12": float(group["private_emp_lag12"].sum()),
            "state_nlra_proxy_emp_lag12": float(group["nlra_proxy_emp_partial_lag12"].sum(min_count=1)),
            "state_counties": int(group["county_fips"].nunique()),
        }
        for variable in heat_vars:
            row[f"state_{variable}"] = weighted_average(group, variable, "private_emp_lag12")
        rows.append(row)
    state_week = pd.DataFrame(rows)
    state_week["any_rc_petition"] = state_week["rc_petition_count"].gt(0).astype(np.int8)
    state_week["calendar_month"] = state_week["week_start"].dt.month.astype(np.int8)
    state_week["calendar_year"] = state_week["week_start"].dt.year.astype(np.int16)
    state_week["state_id"] = pd.factorize(state_week["state_fips"], sort=True)[0].astype(np.int16) + 1
    state_week["national_week_fe"] = pd.factorize(state_week["week_start"], sort=True)[0].astype(np.int16) + 1
    state_week["state_month_fe"] = pd.factorize(
        state_week["state_fips"] + "_" + state_week["calendar_month"].astype(str), sort=True
    )[0].astype(np.int16) + 1
    state_week["log_state_private_emp_lag12"] = np.log(state_week["state_private_emp_lag12"])
    if state_week.duplicated(["state_fips", "week_start"]).any():
        raise ValueError("State-week keys are not unique")
    state_parquet = gate25 / "state_week_incidence_v1.parquet"
    state_dta = gate25 / "state_week_incidence_v1.dta"
    pq.write_table(pa.Table.from_pandas(state_week, preserve_index=False), state_parquet, compression="zstd")
    state_week.to_stata(state_dta, write_index=False, version=118, convert_dates={"week_start": "td"})

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_panel_sha256": sha256(source),
        "rucc_raw_sha256": sha256(raw_path),
        "flags_sha256": sha256(flag_path),
        "state_week_parquet_sha256": sha256(state_parquet),
        "state_week_dta_sha256": sha256(state_dta),
        "analysis_rows": len(sample),
        "county_month_support_rows": int(sample["after_county_month"].sum()),
        "prefilter_core_rows": int(sample["prefilter_core"].sum()),
        "state_week_rows": len(state_week),
        "state_week_states": int(state_week["state_fips"].nunique()),
        "state_week_weeks": int(state_week["week_start"].nunique()),
    }
    manifest_path = gate25 / "gate25_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
