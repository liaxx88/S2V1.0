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

PANEL_START = pd.Timestamp("2011-01-03")
PANEL_END = pd.Timestamp("2024-12-30")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def employer_standardize(value: object) -> str:
    text = str(value or "").upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\b(THE|LLC|L L C|INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LTD|LP|LLP|PLC)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if "STARBUCKS" in text:
        return "STARBUCKS"
    if re.search(r"\bAMAZON\b|AMAZON COM|AMAZON FULFILLMENT", text):
        return "AMAZON"
    return text or "MISSING"

def place_key(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper())
    return re.sub(r"\s+", " ", text).strip()

def harmonize_connecticut_2020_counties(main: pd.DataFrame, root: Path,
                                         audit_dir: Path) -> pd.DataFrame:

    output = main.copy().reset_index(drop=True)
    output["county_fips_gate1"] = output["county_fips"].astype("string")
    planning = output["county_fips_gate1"].str.fullmatch(r"09(?:110|120|130|140|150|160|170|180|190)", na=False)
    if not planning.any():
        pd.DataFrame(columns=[
            "case_number", "city", "source_county_fips", "target_county_fips",
            "harmonization_rule", "source_file",
        ]).to_csv(audit_dir / "gate2_county_harmonization.csv", index=False,
                  encoding="utf-8", lineterminator="\n")
        return output

    source_file = (root / "data" / "raw" / "census" / "relationships_2020"
                   / "national_place_by_county2020.txt")
    places = pd.read_csv(source_file, sep="|", dtype=str, keep_default_na=False)
    places = places.loc[places["STATEFP"].eq("09")].copy()
    places["place_key"] = (
        places["PLACENAME"]
        .str.replace(r" (city|town|borough|village|CDP)$", "", case=False, regex=True)
        .map(place_key)
    )
    place_map = places.groupby("place_key", as_index=False).agg(
        target_county_fips=("COUNTYFP", lambda values: "09" + values.iloc[0]),
        target_county_count=("COUNTYFP", "nunique"),
    )

    
    place_map = place_map.loc[place_map["target_county_count"].eq(1)].copy()
    output["place_key"] = output["city"].map(place_key)
    output = output.merge(place_map[["place_key", "target_county_fips"]], on="place_key",
                          how="left", validate="many_to_one")
    failed = planning & output["target_county_fips"].isna()
    if failed.any():
        raise ValueError("Connecticut planning-region cases without a unique 2020 county: "
                         + ", ".join(output.loc[failed, "case_number"].head(10)))
    audit = output.loc[planning, [
        "case_number", "city", "county_fips_gate1", "target_county_fips"
    ]].rename(columns={"county_fips_gate1": "source_county_fips"})
    audit["harmonization_rule"] = "official_2020_place_to_county"
    audit["source_file"] = source_file.relative_to(root).as_posix()
    audit.to_csv(audit_dir / "gate2_county_harmonization.csv", index=False,
                 encoding="utf-8", lineterminator="\n")
    output.loc[planning, "county_fips"] = output.loc[planning, "target_county_fips"]
    return output.drop(columns=["place_key", "target_county_fips"])

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

    gate1 = root / "data" / "clean" / "gate1"
    noaa = root / "data" / "clean" / "noaa"
    qcew = root / "data" / "clean" / "qcew"
    gate2 = root / "data" / "clean" / "gate2"
    audit_dir = root / "data" / "clean" / "results"
    gate2.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    petitions = pd.read_parquet(gate1 / "nlrb_petitions_gate1_v1.parquet")
    geography = pd.read_parquet(gate1 / "nlrb_geocode_gate1_v1.parquet")
    petitions = petitions.merge(
        geography[["case_number", "county_fips", "geocode_quality", "county_source"]],
        on="case_number", how="left", validate="one_to_one"
    )
    petitions["date_filed"] = pd.to_datetime(petitions["date_filed"])
    petitions["main_geo"] = pd.to_numeric(petitions["main_geo"], errors="coerce").fillna(0).astype(int)
    main = petitions.loc[petitions["main_geo"].eq(1)].copy()
    main = harmonize_connecticut_2020_counties(main, root, audit_dir)
    main["employer_std"] = main["employer_name_raw"].map(employer_standardize)
    main["week_start"] = main["date_filed"] - pd.to_timedelta(main["date_filed"].dt.weekday, unit="D")
    main["employees_on_petition"] = pd.to_numeric(main["employees_on_petition"], errors="coerce")

    employer_counts = main.groupby("employer_std").size().sort_values(ascending=False)
    top10 = list(employer_counts.head(10).index)
    concentration = pd.DataFrame({
        "rank": np.arange(1, len(employer_counts) + 1),
        "employer_std": employer_counts.index,
        "petitions": employer_counts.values,
    })
    concentration["share_pct"] = 100 * concentration["petitions"] / len(main)
    concentration["cumulative_share_pct"] = concentration["share_pct"].cumsum()
    concentration.head(100).to_csv(audit_dir / "gate2_top_employers.csv", index=False,
                                    encoding="utf-8", lineterminator="\n")

    valid_county = (
        main["county_fips"].fillna("").astype(str).str.fullmatch(r"\d{5}")
        & ~main["county_fips"].fillna("").astype(str).eq("00000")
    )
    matched_petitions = main.loc[
        valid_county
        & main["week_start"].between(PANEL_START, PANEL_END)
    ].copy()
    matched_petitions["county_fips"] = matched_petitions["county_fips"].astype(str).str.zfill(5)
    matched_petitions["not_top1"] = ~matched_petitions["employer_std"].isin(top10[:1])
    matched_petitions["not_top5"] = ~matched_petitions["employer_std"].isin(top10[:5])
    matched_petitions["not_top10"] = ~matched_petitions["employer_std"].isin(top10[:10])
    matched_petitions["not_starbucks"] = ~matched_petitions["employer_std"].eq("STARBUCKS")
    matched_petitions["not_starbucks_amazon"] = ~matched_petitions["employer_std"].isin({"STARBUCKS", "AMAZON"})
    weekly_petitions = matched_petitions.groupby(["county_fips", "week_start"], as_index=False).agg(
        rc_petition_count=("case_number", "size"),
        workers_requested_sum=("employees_on_petition", lambda values: values.sum(min_count=1)),
        rc_count_excl_top1=("not_top1", "sum"), rc_count_excl_top5=("not_top5", "sum"),
        rc_count_excl_top10=("not_top10", "sum"),
        rc_count_excl_starbucks=("not_starbucks", "sum"),
        rc_count_excl_starbucks_amazon=("not_starbucks_amazon", "sum"),
    )

    weather = pd.read_parquet(noaa / "noaa_county_week_heat_2010_2024.parquet")
    weather["week_start"] = pd.to_datetime(weather["week_start"])
    panel = weather.loc[weather["week_start"].between(PANEL_START, PANEL_END)].copy()
    if panel.duplicated(["county_fips", "week_start"]).any():
        raise ValueError("Weather panel is not unique by county-week")
    expected_weeks = len(pd.date_range(PANEL_START, PANEL_END, freq="7D"))
    county_week_counts = panel.groupby("county_fips").size()
    if not county_week_counts.eq(expected_weeks).all():
        bad = county_week_counts[~county_week_counts.eq(expected_weeks)].head().to_dict()
        raise ValueError(f"Panel is not a balanced county-week universe: {bad}")
    panel = panel.merge(weekly_petitions, on=["county_fips", "week_start"], how="left",
                        validate="one_to_one")
    count_columns = [
        "rc_petition_count", "workers_requested_sum", "rc_count_excl_top1", "rc_count_excl_top5",
        "rc_count_excl_top10", "rc_count_excl_starbucks", "rc_count_excl_starbucks_amazon",
    ]
    panel[count_columns] = panel[count_columns].fillna(0)
    panel["rc_petition_count"] = panel["rc_petition_count"].astype(np.int16)
    panel["any_rc_petition"] = panel["rc_petition_count"].gt(0).astype(np.int8)

    employment = pd.read_parquet(qcew / "qcew_county_month_private.parquet")
    employment["county_fips"] = employment["county_fips"].astype(str).str.zfill(5)
    base_fields = [
        "county_fips", "year", "month", "private_employment", "nlra_proxy_employment",
        "nlra_proxy_employment_partial", "private_establishments", "avg_weekly_wage",
    ]
    lag = employment[base_fields].copy()
    lag["year"] = lag["year"].astype(int) + 1
    lag = lag.rename(columns={
        "private_employment": "private_emp_lag12",
        "nlra_proxy_employment": "nlra_proxy_emp_lag12",
        "nlra_proxy_employment_partial": "nlra_proxy_emp_partial_lag12",
        "private_establishments": "establishments_lag12",
        "avg_weekly_wage": "avg_wage_lag12",
    })
    panel["employment_year"] = panel["week_start"].dt.year.astype(int)
    panel["employment_month"] = panel["week_start"].dt.month.astype(int)
    panel = panel.merge(
        lag, left_on=["county_fips", "employment_year", "employment_month"],
        right_on=["county_fips", "year", "month"], how="left", validate="many_to_one",
        suffixes=("", "_qcew")
    ).drop(columns=["year_qcew", "month"])
    current = employment[base_fields].rename(columns={
        "year": "employment_year", "month": "employment_month",
        "private_employment": "private_emp_current",
        "nlra_proxy_employment": "nlra_proxy_emp_current",
        "nlra_proxy_employment_partial": "nlra_proxy_emp_partial_current",
        "private_establishments": "establishments_current", "avg_weekly_wage": "avg_wage_current",
    })
    panel = panel.merge(current, on=["county_fips", "employment_year", "employment_month"],
                        how="left", validate="many_to_one")
    panel["log_private_emp_lag12"] = np.log(panel["private_emp_lag12"].where(panel["private_emp_lag12"] > 0))
    panel["log_nlra_proxy_emp_lag12"] = np.log(
        panel["nlra_proxy_emp_lag12"].where(panel["nlra_proxy_emp_lag12"] > 0)
    )
    panel["log_nlra_proxy_partial_lag12"] = np.log(
        panel["nlra_proxy_emp_partial_lag12"].where(panel["nlra_proxy_emp_partial_lag12"] > 0)
    )
    panel["calendar_month"] = panel["week_start"].dt.month.astype(np.int8)
    panel["calendar_year"] = panel["week_start"].dt.year.astype(np.int16)
    panel["county_id"] = pd.factorize(panel["county_fips"], sort=True)[0].astype(np.int32) + 1
    panel["state_id"] = pd.factorize(panel["state_fips"], sort=True)[0].astype(np.int16) + 1
    panel["county_month_fe"] = pd.factorize(
        panel["county_fips"] + "_" + panel["calendar_month"].astype(str), sort=True
    )[0].astype(np.int32) + 1
    panel["state_yearweek_fe"] = pd.factorize(
        panel["state_fips"] + "_" + panel["week_start"].dt.strftime("%Y-%m-%d"), sort=True
    )[0].astype(np.int32) + 1
    panel["baseline_48state"] = ~panel["state_fips"].eq("11")
    required_heat = [
        "p95_days_lag1_4", "p95_days_lag5_8", "p95_days_lag9_12", "p95_days_lag13_16"
    ]
    panel["weather_complete"] = panel[required_heat].notna().all(axis=1)
    panel["qcew_lag12_matched"] = panel["private_emp_lag12"].gt(0)
    panel["analysis_sample"] = (
        panel["baseline_48state"] & panel["weather_complete"] & panel["qcew_lag12_matched"]
    )

    

    

    panel["ppml_core_sample"] = False
    analysis_index = panel.index[panel["analysis_sample"]]
    analysis_panel = panel.loc[analysis_index]
    county_month_positive = analysis_panel.groupby("county_month_fe")[
        "rc_petition_count"
    ].transform("sum").gt(0)
    state_week_positive = analysis_panel.groupby("state_yearweek_fe")[
        "rc_petition_count"
    ].transform("sum").gt(0)
    panel.loc[analysis_index, "ppml_core_sample"] = (
        county_month_positive & state_week_positive
    ).to_numpy()
    if panel.loc[panel["ppml_core_sample"], "rc_petition_count"].sum() != panel.loc[
        panel["analysis_sample"], "rc_petition_count"
    ].sum():
        raise ValueError("PPML core-sample filter dropped positive outcomes")

    weather_counties = set(panel["county_fips"])
    qcew_keys = set(zip(lag["county_fips"], lag["year"], lag["month"]))
    qcew_positive = lag.loc[lag["private_emp_lag12"].gt(0)].copy()
    qcew_positive_keys = set(zip(
        qcew_positive["county_fips"], qcew_positive["year"], qcew_positive["month"]
    ))
    lag_value_lookup = {
        (county, int(year), int(month)): value
        for county, year, month, value in zip(
            lag["county_fips"], lag["year"], lag["month"], lag["private_emp_lag12"]
        )
    }
    petition_noaa = matched_petitions["county_fips"].isin(weather_counties)
    petition_keys = [
        (county, int(date.year), int(date.month))
        for county, date in zip(matched_petitions["county_fips"], matched_petitions["week_start"])
    ]
    petition_qcew = pd.Series(
        [key in qcew_keys for key in petition_keys], index=matched_petitions.index
    )
    petition_qcew_positive = pd.Series(
        [key in qcew_positive_keys for key in petition_keys], index=matched_petitions.index
    )
    final_filing_cohort = petition_noaa & petition_qcew_positive

    

    

    unusable_lag12 = matched_petitions.loc[
        petition_noaa & petition_qcew & ~petition_qcew_positive,
        ["case_number", "date_filed", "week_start", "county_fips", "state"],
    ].copy()
    unusable_lag12["private_emp_lag12"] = [
        lag_value_lookup[key]
        for key, keep in zip(petition_keys, petition_noaa & petition_qcew & ~petition_qcew_positive)
        if keep
    ]
    unusable_lag12["exclusion_reason"] = "nonpositive_lag12_private_employment"
    unusable_lag12.to_csv(
        audit_dir / "gate2_unusable_lag12_petitions.csv", index=False,
        encoding="utf-8", lineterminator="\n"
    )
    gate1_county_raw = (
        main["county_fips_gate1"].fillna("").astype(str).str.fullmatch(r"\d{5}")
        & ~main["county_fips_gate1"].fillna("").astype(str).eq("00000")
    )
    gate1_county = int(gate1_county_raw.sum())
    conus_county = int((valid_county & ~main["state"].eq("DC")).sum())
    merge_audit = pd.DataFrame([
        {"item": "County-located petitions (48 states + DC)", "n": gate1_county, "denominator": len(main),
         "rate_pct": 100 * gate1_county / len(main)},
        {"item": "48-state county petitions", "n": conus_county, "denominator": gate1_county,
         "rate_pct": 100 * conus_county / gate1_county},
        {"item": "NOAA matched", "n": int(petition_noaa.sum()), "denominator": conus_county,
         "rate_pct": 100 * petition_noaa.sum() / conus_county},
        {"item": "QCEW county-month record matched", "n": int((petition_noaa & petition_qcew).sum()),
         "denominator": int(petition_noaa.sum()),
         "rate_pct": 100 * (petition_noaa & petition_qcew).sum() / petition_noaa.sum()},
        {"item": "Positive usable lag-12 employment", "n": int(final_filing_cohort.sum()),
         "denominator": int((petition_noaa & petition_qcew).sum()),
         "rate_pct": 100 * final_filing_cohort.sum() / (petition_noaa & petition_qcew).sum()},
        {"item": "Final employment-supported filing cohorts", "n": int(final_filing_cohort.sum()),
         "denominator": int(final_filing_cohort.sum()), "rate_pct": 100.0},
    ])
    merge_audit["rate_pct"] = merge_audit["rate_pct"].round(4)
    merge_audit.to_csv(audit_dir / "gate2_merge_audit.csv", index=False, encoding="utf-8",
                       lineterminator="\n")

    descriptive = main.assign(year=main["date_filed"].dt.year, month=main["date_filed"].dt.month)
    trends = descriptive.groupby("year").size().rename("rc_petitions").reset_index()
    trends.to_csv(audit_dir / "gate2_petitions_by_year.csv", index=False, encoding="utf-8", lineterminator="\n")
    seasonality = descriptive.groupby("month").size().rename("rc_petitions").reset_index()
    seasonality.to_csv(audit_dir / "gate2_petitions_by_month.csv", index=False, encoding="utf-8", lineterminator="\n")

    panel = panel.sort_values(["county_fips", "week_start"]).reset_index(drop=True)
    output_parquet = gate2 / "county_week_analysis_v1.parquet"
    output_dta = gate2 / "county_week_analysis_v1.dta"
    output_core_dta = gate2 / "county_week_ppml_core_v1.dta"
    table = pa.Table.from_pandas(panel, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata.update({
        b"unit": b"county x Monday-Sunday week",
        b"universe": b"all NOAA nClimGrid CONUS counties x weeks, 2011-01-03 to 2024-12-30",
        b"outcome": b"official NLRB RC petition count; zero when no filing",
        b"offset": b"log private QCEW employment in same calendar month one year earlier",
        b"gate1_version": b"v1 immutable",
    })
    temp_parquet = output_parquet.with_suffix(".parquet.tmp")
    pq.write_table(table.replace_schema_metadata(metadata), temp_parquet, compression="zstd",
                   use_dictionary=["county_fips", "state_fips"])
    os.replace(temp_parquet, output_parquet)

    stata = panel.copy()
    for column in ("baseline_48state", "weather_complete", "qcew_lag12_matched",
                   "analysis_sample", "ppml_core_sample"):
        stata[column] = stata[column].astype(np.int8)
    stata.to_stata(output_dta, write_index=False, version=118,
                   convert_dates={"week_start": "td"})
    stata.loc[stata["ppml_core_sample"].eq(1)].to_stata(
        output_core_dta, write_index=False, version=118,
        convert_dates={"week_start": "td"}
    )
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "gate1_manifest_sha256": sha256(gate1 / "gate1_v1_manifest.json"),
        "weather_sha256": sha256(noaa / "noaa_county_week_heat_2010_2024.parquet"),
        "qcew_sha256": sha256(qcew / "qcew_county_month_private.parquet"),
        "parquet_sha256": sha256(output_parquet), "dta_sha256": sha256(output_dta),
        "ppml_core_dta_sha256": sha256(output_core_dta),
        "rows": len(panel), "counties": panel["county_fips"].nunique(),
        "weeks": panel["week_start"].nunique(), "petition_total": int(panel["rc_petition_count"].sum()),
        "ppml_core_rows": int(panel["ppml_core_sample"].sum()),
    }
    (gate2 / "county_week_analysis_v1_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote Gate 2 analysis panel: {len(panel):,} rows, "
          f"{panel['county_fips'].nunique():,} counties, {panel['week_start'].nunique():,} weeks")

if __name__ == "__main__":
    main()
