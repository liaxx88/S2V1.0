from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import pyarrow as pa
import pyarrow.parquet as pq

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def monday(date: pd.Series) -> pd.Series:
    return date - pd.to_timedelta(date.dt.weekday, unit="D")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    gate1 = root / "data" / "clean" / "gate1"
    gate2 = root / "data" / "clean" / "gate2"
    gate3b = root / "data" / "clean" / "gate3b"
    audit = root / "data" / "clean" / "results"
    gate3b.mkdir(parents=True, exist_ok=True)

    progression_path = gate1 / "nlrb_case_election_gate1_v1.parquet"
    geocode_path = gate1 / "nlrb_geocode_gate1_v1.parquet"
    panel_path = gate2 / "county_week_analysis_v1.parquet"
    progression = pd.read_parquet(progression_path)
    geocode = pd.read_parquet(geocode_path, columns=["case_number", "county_fips", "geocode_quality"])
    progression = progression.merge(geocode, on="case_number", how="left", validate="one_to_one")
    ct_path = audit / "gate2_county_harmonization.csv"
    if ct_path.exists():
        ct = pd.read_csv(ct_path, dtype=str, keep_default_na=False)[
            ["case_number", "target_county_fips"]
        ]
        progression = progression.merge(ct, on="case_number", how="left", validate="one_to_one")
        has_ct_target = progression["target_county_fips"].fillna("").str.fullmatch(r"\d{5}")
        progression.loc[has_ct_target, "county_fips"] = progression.loc[has_ct_target, "target_county_fips"]
        progression = progression.drop(columns="target_county_fips")
    for column in ("date_filed", "date_closed", "first_tally_date", "last_tally_date"):
        progression[column] = pd.to_datetime(progression[column], errors="coerce")
    progression["week_start"] = monday(progression["date_filed"])
    progression["state_fips"] = progression["county_fips"].fillna("").astype(str).str[:2]
    progression["days_file_to_close"] = (progression["date_closed"] - progression["date_filed"]).dt.days
    progression["days_file_to_first_tally"] = (
        progression["first_tally_date"] - progression["date_filed"]
    ).dt.days
    valid_election_timing = progression["days_file_to_first_tally"].between(0, 180)
    valid_close_180 = progression["days_file_to_close"].between(0, 180)
    valid_close_365 = progression["days_file_to_close"].between(0, 365)
    reason = progression["reason_closed"].fillna("").astype(str).str.strip().str.lower()
    progression["election_within180"] = (
        progression["election_held"].eq(1) & valid_election_timing
    ).astype(np.int8)

    
    progression["certified_rep_caseclosed_within365"] = (
        reason.eq("certific. of representative") & valid_close_365
    ).astype(np.int8)
    progression["certified_tally_proxy_within365"] = (
        progression["certified"].eq(1)
        & progression["days_file_to_first_tally"].between(0, 365)
    ).astype(np.int8)
    progression["withdrawn_within180"] = (
        progression["withdrawn"].eq(1) & valid_close_180
    ).astype(np.int8)
    progression["dismissed_within180"] = (
        progression["dismissed"].eq(1) & valid_close_180
    ).astype(np.int8)
    progression["failed_within180"] = (
        progression["withdrawn_within180"].eq(1)
        | progression["dismissed_within180"].eq(1)
    ).astype(np.int8)
    progression["invalid_negative_election_timing"] = (
        progression["days_file_to_first_tally"].lt(0)
    ).astype(np.int8)
    progression["invalid_negative_close_timing"] = progression["days_file_to_close"].lt(0).astype(np.int8)

    panel = pd.read_parquet(panel_path)
    panel["week_start"] = pd.to_datetime(panel["week_start"])
    analysis_keys = panel.loc[panel["analysis_sample"].astype(bool), ["county_fips", "week_start"]].copy()
    analysis_keys["in_gate2_analysis"] = 1
    valid_county = progression["county_fips"].fillna("").astype(str).str.fullmatch(r"\d{5}")
    cohort = progression.loc[
        progression["main_geo"].eq(1) & valid_county & ~progression["state_fips"].eq("11")
    ].copy()
    cohort = cohort.merge(analysis_keys, on=["county_fips", "week_start"], how="left", validate="many_to_one")
    cohort = cohort.loc[cohort["in_gate2_analysis"].eq(1)].copy()
    cohort = cohort.drop(columns="in_gate2_analysis")
    if len(cohort) != 21_990:
        raise ValueError(f"Gate 3B filing cohort does not reproduce Gate 2 petition total: {len(cohort):,}")
    admin_cutoff = max(progression["date_closed"].max(), progression["last_tally_date"].max())
    max_followup_required = cohort["date_filed"].max() + pd.Timedelta(days=365)
    if admin_cutoff < max_followup_required:
        raise ValueError(
            f"Right-censoring remains: administrative cutoff {admin_cutoff.date()} < "
            f"required {max_followup_required.date()}"
        )

    petition_columns = [
        "case_number", "county_fips", "state_fips", "week_start", "date_filed", "date_closed",
        "first_tally_date", "last_tally_date", "case_status", "reason_closed", "geocode_quality",
        "employees_on_petition", "election_held", "certified", "withdrawn", "dismissed",
        "days_file_to_close", "days_file_to_first_tally", "election_within180",
        "certified_rep_caseclosed_within365", "certified_tally_proxy_within365",
        "withdrawn_within180", "dismissed_within180", "failed_within180",
        "invalid_negative_election_timing", "invalid_negative_close_timing",
    ]
    petition_out = cohort[petition_columns].sort_values("case_number").reset_index(drop=True)
    petition_parquet = gate3b / "petition_progression_gate3b_v1.parquet"
    petition_csv = gate3b / "petition_progression_gate3b_v1.csv"
    petition_dta = gate3b / "petition_progression_gate3b_v1.dta"
    pq.write_table(pa.Table.from_pandas(petition_out, preserve_index=False), petition_parquet, compression="zstd")
    petition_out.to_csv(petition_csv, index=False, lineterminator="\n")
    stata_petition = petition_out.rename(columns={
        "certified_rep_caseclosed_within365": "cert_rep_closed_365",
        "certified_tally_proxy_within365": "cert_tally_proxy_365",
        "invalid_negative_election_timing": "invalid_neg_election_timing",
        "invalid_negative_close_timing": "invalid_neg_close_timing",
    }).copy()
    stata_petition.to_stata(
        petition_dta, write_index=False, version=118,
        convert_dates={c: "td" for c in ("week_start", "date_filed", "date_closed", "first_tally_date", "last_tally_date")},
    )

    outcomes = {
        "rc_petition_count": "case_number",
        "election_180_count": "election_within180",
        "certified_rep_365_count": "certified_rep_caseclosed_within365",
        "certified_tally_proxy_365_count": "certified_tally_proxy_within365",
        "withdrawn_180_count": "withdrawn_within180",
        "dismissed_180_count": "dismissed_within180",
        "failed_180_count": "failed_within180",
    }
    grouped = cohort.groupby(["county_fips", "week_start"])
    counts = grouped.size().rename("rc_petition_count").reset_index()
    for output, source_column in outcomes.items():
        if output == "rc_petition_count":
            continue
        addition = grouped[source_column].sum().rename(output).reset_index()
        counts = counts.merge(addition, on=["county_fips", "week_start"], validate="one_to_one")
    progression_panel = panel.drop(columns=["rc_petition_count"]).merge(
        counts, on=["county_fips", "week_start"], how="left", validate="one_to_one"
    )
    count_columns = list(outcomes)
    progression_panel[count_columns] = progression_panel[count_columns].fillna(0).astype(np.int16)
    progression_panel["any_election_180"] = progression_panel["election_180_count"].gt(0).astype(np.int8)
    progression_panel["any_certified_rep_365"] = progression_panel["certified_rep_365_count"].gt(0).astype(np.int8)
    progression_panel["any_failed_180"] = progression_panel["failed_180_count"].gt(0).astype(np.int8)
    if progression_panel.loc[progression_panel["analysis_sample"].astype(bool), "rc_petition_count"].sum() != len(cohort):
        raise ValueError("County-week Gate 3B counts do not reproduce filing cohorts")

    primary_outcomes = ["rc_petition_count", "election_180_count", "certified_rep_365_count", "failed_180_count"]
    analysis_mask = progression_panel["analysis_sample"].astype(bool)
    for outcome in primary_outcomes:
        cm_positive = progression_panel.loc[analysis_mask].groupby("county_month_fe")[outcome].transform("sum").gt(0)
        sw_positive = progression_panel.loc[analysis_mask].groupby("state_yearweek_fe")[outcome].transform("sum").gt(0)
        flag = f"core_{outcome}"
        progression_panel[flag] = False
        progression_panel.loc[analysis_mask, flag] = (cm_positive & sw_positive).to_numpy()
    union_core = progression_panel[[f"core_{outcome}" for outcome in primary_outcomes]].any(axis=1)

    panel_parquet = gate3b / "county_week_progression_v1.parquet"
    panel_dta = gate3b / "county_week_progression_v1.dta"
    core_dta = gate3b / "county_week_progression_ppml_core_v1.dta"
    pq.write_table(pa.Table.from_pandas(progression_panel, preserve_index=False), panel_parquet, compression="zstd")
    stata_panel = progression_panel.copy()
    bool_columns = [column for column in stata_panel.columns if stata_panel[column].dtype == bool]
    stata_panel[bool_columns] = stata_panel[bool_columns].astype(np.int8)
    stata_panel.to_stata(panel_dta, write_index=False, version=118, convert_dates={"week_start": "td"})
    stata_panel.loc[union_core].to_stata(core_dta, write_index=False, version=118, convert_dates={"week_start": "td"})

    state_week = progression_panel.loc[analysis_mask].groupby(["state_fips", "week_start"], as_index=False)[
        primary_outcomes
    ].sum()
    state_exposure = pd.read_parquet(gate2.parent / "gate25" / "state_week_incidence_v1.parquet")
    state_exposure["week_start"] = pd.to_datetime(state_exposure["week_start"])
    state_week = state_exposure.drop(columns=["rc_petition_count", "any_rc_petition"]).merge(
        state_week, on=["state_fips", "week_start"], how="left", validate="one_to_one"
    )
    state_week[primary_outcomes] = state_week[primary_outcomes].fillna(0).astype(np.int16)
    state_parquet = gate3b / "state_week_progression_v1.parquet"
    state_dta = gate3b / "state_week_progression_v1.dta"
    pq.write_table(pa.Table.from_pandas(state_week, preserve_index=False), state_parquet, compression="zstd")
    state_week.to_stata(state_dta, write_index=False, version=118, convert_dates={"week_start": "td"})

    audit_rows = [
        {"item": "Employment-supported filing cohorts", "n": len(cohort), "rate_pct": 100.0},
        {"item": "Election within 180 days", "n": int(cohort["election_within180"].sum()),
         "rate_pct": 100 * cohort["election_within180"].mean()},
        {"item": "Certification-of-Representative case closure within 365 days",
         "n": int(cohort["certified_rep_caseclosed_within365"].sum()),
         "rate_pct": 100 * cohort["certified_rep_caseclosed_within365"].mean()},
        {"item": "Union-to-certify tally proxy within 365 days",
         "n": int(cohort["certified_tally_proxy_within365"].sum()),
         "rate_pct": 100 * cohort["certified_tally_proxy_within365"].mean()},
        {"item": "Withdrawal/dismissal within 180 days", "n": int(cohort["failed_within180"].sum()),
         "rate_pct": 100 * cohort["failed_within180"].mean()},
        {"item": "Invalid negative election timing", "n": int(cohort["invalid_negative_election_timing"].sum()),
         "rate_pct": 100 * cohort["invalid_negative_election_timing"].mean()},
        {"item": "Invalid negative closure timing", "n": int(cohort["invalid_negative_close_timing"].sum()),
         "rate_pct": 100 * cohort["invalid_negative_close_timing"].mean()},
    ]
    pd.DataFrame(audit_rows).to_csv(audit / "gate3b_outcome_audit.csv", index=False, lineterminator="\n")
    by_year = cohort.assign(filing_year=cohort["date_filed"].dt.year).groupby("filing_year").agg(
        petitions=("case_number", "size"),
        election_180=("election_within180", "sum"),
        certified_rep_365=("certified_rep_caseclosed_within365", "sum"),
        certified_tally_proxy_365=("certified_tally_proxy_within365", "sum"),
        failed_180=("failed_within180", "sum"),
    ).reset_index()
    by_year.to_csv(audit / "gate3b_outcomes_by_year.csv", index=False, lineterminator="\n")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "progression_source_sha256": sha256(progression_path),
        "geocode_source_sha256": sha256(geocode_path),
        "gate2_panel_source_sha256": sha256(panel_path),
        "petition_parquet_sha256": sha256(petition_parquet),
        "county_week_parquet_sha256": sha256(panel_parquet),
        "state_week_parquet_sha256": sha256(state_parquet),
        "administrative_followup_cutoff": admin_cutoff.date().isoformat(),
        "latest_required_365_day_followup": max_followup_required.date().isoformat(),
        "filing_cohorts": len(cohort),
        "certification_definition": "official reason_closed == Certific. of Representative and date_closed within 365 days; date_closed is a case-closure proxy, not a separate certification issuance date",
    }
    (gate3b / "gate3b_v1_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
