from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import pyarrow as pa
import pyarrow.parquet as pq

HEAT_BLOCKS = [
    "p95_days_lag1_4",
    "p95_days_lag5_8",
    "p95_days_lag9_12",
    "p95_days_lag13_16",
    "p95_days_lag17_20",
    "p95_days_lag21_24",
]
PRIMARY_OUTCOMES = [
    "rc_petition_count",
    "election_180_count",
    "certified_rep_365_count",
    "failed_180_count",
]
TALLY_OUTCOME = "certified_tally_proxy_365_count"
QCEW_COLS = [
    "area_fips", "own_code", "industry_code", "agglvl_code", "qtr",
    "disclosure_code", "month1_emplvl", "month2_emplvl", "month3_emplvl",
]
COMBINED_SECTORS = {"31": "31-33", "32": "31-33", "33": "31-33",
                    "44": "44-45", "45": "44-45", "48": "48-49", "49": "48-49"}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def weighted_average(group: pd.DataFrame, value: str, weight: str) -> float:
    valid = group[value].notna() & group[weight].gt(0)
    if not valid.any():
        return np.nan
    return float(np.average(group.loc[valid, value], weights=group.loc[valid, weight]))

def save_frame(frame: pd.DataFrame, parquet: Path, dta: Path) -> None:
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), parquet, compression="zstd")
    stata = frame.copy()
    bool_cols = [c for c in stata if stata[c].dtype == bool]
    stata[bool_cols] = stata[bool_cols].astype(np.int8)
    date_cols = {c: "td" for c in stata if pd.api.types.is_datetime64_any_dtype(stata[c])}
    stata.to_stata(dta, write_index=False, version=118, convert_dates=date_cols)

def build_state_week(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (state, week), group in panel.groupby(["state_fips", "week_start"], sort=True):
        row: dict[str, object] = {
            "state_fips": state,
            "week_start": week,
            "rc_petition_count": int(group["rc_petition_count"].sum()),
            "state_private_emp_lag12": float(group["private_emp_lag12"].sum()),
        }
        for variable in HEAT_BLOCKS:
            row[f"state_{variable}"] = weighted_average(group, variable, "private_emp_lag12")
        rows.append(row)
    output = pd.DataFrame(rows)
    output["calendar_month"] = output.week_start.dt.month.astype(np.int8)
    output["state_id"] = pd.factorize(output.state_fips, sort=True)[0].astype(np.int16) + 1
    output["national_week_fe"] = pd.factorize(output.week_start, sort=True)[0].astype(np.int16) + 1
    output["state_month_fe"] = pd.factorize(
        output.state_fips + "_" + output.calendar_month.astype(str), sort=True
    )[0].astype(np.int16) + 1
    output["log_state_private_emp_lag12"] = np.log(output.state_private_emp_lag12)
    if output.duplicated(["state_fips", "week_start"]).any():
        raise ValueError("State-week dynamic panel is not unique")
    return output

def iterative_common_support(frame: pd.DataFrame, outcomes: list[str]) -> tuple[pd.Series, list[dict[str, int]]]:
    mask = frame.analysis_sample.astype(bool).copy()
    audit: list[dict[str, int]] = []
    for iteration in range(1, 101):
        active = frame.loc[mask]
        keep = pd.Series(True, index=active.index)
        for outcome in outcomes:
            cm_sum = active.groupby("county_month_fe")[outcome].transform("sum")
            sw_sum = active.groupby("state_yearweek_fe")[outcome].transform("sum")
            keep &= cm_sum.gt(0) & sw_sum.gt(0)
        cm_n = active.groupby("county_month_fe")[outcomes[0]].transform("size")
        sw_n = active.groupby("state_yearweek_fe")[outcomes[0]].transform("size")
        keep &= cm_n.gt(1) & sw_n.gt(1)
        new_mask = pd.Series(False, index=frame.index)
        new_mask.loc[active.index] = keep
        audit.append({
            "iteration": iteration,
            "rows": int(new_mask.sum()),
            **{f"{outcome}_count": int(frame.loc[new_mask, outcome].sum()) for outcome in outcomes},
        })
        if new_mask.equals(mask):
            return new_mask, audit
        mask = new_mask
    raise RuntimeError("Common-support pruning did not converge")

def read_qcew_2010(path: Path) -> pd.DataFrame:
    selected: list[pd.DataFrame] = []
    with zipfile.ZipFile(path) as archive:
        member = archive.namelist()[0]
        for chunk in pd.read_csv(
            archive.open(member), dtype=str, usecols=QCEW_COLS, chunksize=250_000,
            keep_default_na=False, low_memory=False,
        ):
            county = chunk.area_fips.str.fullmatch(r"\d{5}", na=False)
            private = chunk.own_code.eq("5")
            wanted = (
                (chunk.agglvl_code.eq("71") & chunk.industry_code.eq("10"))
                | chunk.agglvl_code.eq("74")
                | chunk.agglvl_code.eq("75")
            )
            part = chunk.loc[county & private & wanted].copy()
            if not part.empty:
                selected.append(part)
    data = pd.concat(selected, ignore_index=True)
    for column in ["month1_emplvl", "month2_emplvl", "month3_emplvl"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["quarter_mean_emp"] = data[["month1_emplvl", "month2_emplvl", "month3_emplvl"]].mean(axis=1)
    data.loc[data.disclosure_code.str.strip().ne(""), "quarter_mean_emp"] = np.nan
    annual = (
        data.groupby(["area_fips", "agglvl_code", "industry_code"], as_index=False)
        .agg(employment_2010=("quarter_mean_emp", "mean"), published_quarters=("quarter_mean_emp", "count"))
    )
    annual = annual.loc[annual.published_quarters.gt(0)].copy()
    return annual

def sector_key(code: object) -> str:
    text = str(code).strip()
    if text in {"31-33", "44-45", "48-49"}:
        return text
    return COMBINED_SECTORS.get(text[:2], text[:2])

def build_county_exposure(qcew: pd.DataFrame, exposure: pd.DataFrame, counties: pd.DataFrame) -> pd.DataFrame:
    exp2 = exposure.loc[exposure.naics_level.eq("naics2")].copy()
    exp2["sector_key"] = exp2.naics_source.astype(str).map(sector_key)
    exp2 = exp2.drop_duplicates("sector_key")
    exp2 = exp2[["sector_key", "heat_exposure_index", "thermal_exposure"]].rename(
        columns={"heat_exposure_index": "sector_heat_index", "thermal_exposure": "sector_thermal"}
    )
    exp3 = exposure.loc[exposure.naics_level.eq("naics3")].copy()
    exp3 = exp3.drop_duplicates("naics_2017").set_index("naics_2017")

    total = qcew.loc[qcew.agglvl_code.eq("71") & qcew.industry_code.eq("10"),
                     ["area_fips", "employment_2010"]].rename(
                         columns={"area_fips": "county_fips", "employment_2010": "private_emp_2010"}
                     )
    sectors = qcew.loc[qcew.agglvl_code.eq("74")].copy()
    sectors["sector_key"] = sectors.industry_code.map(sector_key)
    sectors = sectors.merge(exp2, on="sector_key", how="left", validate="many_to_one")
    sectors["broad_num"] = sectors.employment_2010 * sectors.sector_heat_index
    sectors["broad_thermal_num"] = sectors.employment_2010 * sectors.sector_thermal
    sectors["is_agriculture"] = sectors.sector_key.eq("11")

    sector_agg = sectors.groupby("area_fips").agg(
        sector_emp_published=("employment_2010", "sum"),
        broad_num=("broad_num", "sum"),
        broad_thermal_num=("broad_thermal_num", "sum"),
        matched_sector_emp=("employment_2010", lambda s: float(s[sectors.loc[s.index, "sector_heat_index"].notna()].sum())),
        agriculture_emp_2010=("employment_2010", lambda s: float(s[sectors.loc[s.index, "is_agriculture"]].sum())),
    ).reset_index().rename(columns={"area_fips": "county_fips"})

    eligible_sectors = sectors.loc[~sectors.is_agriculture & sectors.sector_heat_index.notna()].copy()
    nlra_sector = eligible_sectors.groupby("area_fips").agg(
        nlra_emp_before_detail_exclusions=("employment_2010", "sum"),
        nlra_num_before_detail_exclusions=("broad_num", "sum"),
        nlra_thermal_before_detail_exclusions=("broad_thermal_num", "sum"),
    ).reset_index().rename(columns={"area_fips": "county_fips"})

    exclusions = qcew.loc[qcew.agglvl_code.eq("75") & qcew.industry_code.isin(["481", "482", "814"])].copy()
    exclusions["exposure"] = exclusions.industry_code.map(exp3.heat_exposure_index)
    exclusions["thermal"] = exclusions.industry_code.map(exp3.thermal_exposure)
    exclusions["exclude_num"] = exclusions.employment_2010 * exclusions.exposure
    exclusions["exclude_thermal_num"] = exclusions.employment_2010 * exclusions.thermal
    excluded = exclusions.groupby("area_fips").agg(
        excluded_emp_481_482_814=("employment_2010", "sum"),
        excluded_num=("exclude_num", "sum"),
        excluded_thermal_num=("exclude_thermal_num", "sum"),
    ).reset_index().rename(columns={"area_fips": "county_fips"})

    out = counties.merge(total, on="county_fips", how="left", validate="one_to_one")
    out = out.merge(sector_agg, on="county_fips", how="left", validate="one_to_one")
    out = out.merge(nlra_sector, on="county_fips", how="left", validate="one_to_one")
    out = out.merge(excluded, on="county_fips", how="left", validate="one_to_one")
    out[["excluded_emp_481_482_814", "excluded_num", "excluded_thermal_num"]] = out[
        ["excluded_emp_481_482_814", "excluded_num", "excluded_thermal_num"]
    ].fillna(0)
    out["sector_coverage"] = out.matched_sector_emp / out.private_emp_2010
    out["pred_heat_broad_2010"] = out.broad_num / out.matched_sector_emp
    out["pred_thermal_broad_2010"] = out.broad_thermal_num / out.matched_sector_emp
    out["nlra_proxy_emp_2010"] = (
        out.nlra_emp_before_detail_exclusions - out.excluded_emp_481_482_814
    )
    out["nlra_num"] = out.nlra_num_before_detail_exclusions - out.excluded_num
    out["nlra_thermal_num"] = out.nlra_thermal_before_detail_exclusions - out.excluded_thermal_num
    out["pred_heat_nlra_2010"] = out.nlra_num / out.nlra_proxy_emp_2010
    out["pred_thermal_nlra_2010"] = out.nlra_thermal_num / out.nlra_proxy_emp_2010
    out["agriculture_share_2010"] = out.agriculture_emp_2010 / out.private_emp_2010
    out["log_private_emp_2010"] = np.log(out.private_emp_2010)

    detail = qcew.loc[qcew.agglvl_code.eq("75")].copy()
    detail["naics3"] = detail.industry_code.astype(str).str.extract(r"^(\d{3})", expand=False)
    detail = detail.merge(
        exp3[["heat_exposure_index", "thermal_exposure"]], left_on="naics3", right_index=True,
        how="left", validate="many_to_one",
    )
    detail = detail.loc[
        ~detail.naics3.str.startswith("11", na=False)
        & ~detail.naics3.isin(["481", "482", "814"])
        & detail.heat_exposure_index.notna()
    ].copy()
    detail["num3"] = detail.employment_2010 * detail.heat_exposure_index
    agg3 = detail.groupby("area_fips").agg(
        naics3_matched_emp_2010=("employment_2010", "sum"),
        naics3_num=("num3", "sum"),
    ).reset_index().rename(columns={"area_fips": "county_fips"})
    out = out.merge(agg3, on="county_fips", how="left", validate="one_to_one")
    out["naics3_coverage"] = out.naics3_matched_emp_2010 / out.nlra_proxy_emp_2010
    out["pred_heat_naics3_2010"] = out.naics3_num / out.naics3_matched_emp_2010

    
    out["exposure_primary_eligible"] = (
        out.sector_coverage.ge(0.80) & out.pred_heat_nlra_2010.notna() & out.nlra_proxy_emp_2010.gt(0)
    )
    out["exposure_naics3_eligible"] = out.naics3_coverage.ge(0.80) & out.pred_heat_naics3_2010.notna()
    for variable in [
        "pred_heat_nlra_2010", "pred_heat_broad_2010", "pred_thermal_nlra_2010",
        "agriculture_share_2010", "log_private_emp_2010",
    ]:
        valid = out.exposure_primary_eligible & out[variable].notna()
        mean = out.loc[valid, variable].mean()
        sd = out.loc[valid, variable].std(ddof=0)
        out[f"z_{variable}"] = (out[variable] - mean) / sd
    valid3 = out.exposure_naics3_eligible
    mean3 = out.loc[valid3, "pred_heat_naics3_2010"].mean()
    sd3 = out.loc[valid3, "pred_heat_naics3_2010"].std(ddof=0)
    out["z_pred_heat_naics3_2010"] = (out.pred_heat_naics3_2010 - mean3) / sd3
    out = out.rename(columns={
        "nlra_emp_before_detail_exclusions": "nlra_emp_pre_excl",
        "nlra_num_before_detail_exclusions": "nlra_num_pre_excl",
        "nlra_thermal_before_detail_exclusions": "nlra_thermal_pre_excl",
    })
    return out

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    pivot = root / "data" / "clean" / "final_pivot"
    audit_dir = root / "data" / "clean" / "results"
    pivot.mkdir(parents=True, exist_ok=True)

    panel_path = root / "data" / "clean" / "gate2" / "county_week_analysis_v1.parquet"
    prog_path = root / "data" / "clean" / "gate3b" / "county_week_progression_v1.parquet"
    qcew_path = root / "data" / "raw" / "qcew" / "quarterly_singlefile" / "2010_qtrly_singlefile.zip"
    exposure_path = root / "data" / "clean" / "gate3" / "industry_heat_exposure_2019.parquet"
    flags_path = root / "data" / "clean" / "gate25" / "gate25_separation_flags.parquet"

    panel = pd.read_parquet(panel_path)
    panel.week_start = pd.to_datetime(panel.week_start)
    analysis = panel.loc[panel.analysis_sample.astype(bool)].copy()

    state_week = build_state_week(analysis)
    save_frame(state_week, pivot / "state_week_dynamic_v1.parquet", pivot / "state_week_dynamic_v1.dta")

    progression = pd.read_parquet(prog_path)
    progression.week_start = pd.to_datetime(progression.week_start)
    common, common_iterations = iterative_common_support(progression, PRIMARY_OUTCOMES)
    tally_support, tally_iterations = iterative_common_support(progression, [TALLY_OUTCOME])
    progression["common_progression_support"] = common
    progression["tally_support"] = tally_support
    keep = common | tally_support
    common_panel = progression.loc[keep].copy()
    save_frame(
        common_panel,
        pivot / "progression_common_support_v1.parquet",
        pivot / "progression_common_support_v1.dta",
    )

    qcew = read_qcew_2010(qcew_path)
    exposure = pd.read_parquet(exposure_path)
    counties = analysis[["county_fips", "state_fips", "county_id", "state_id"]].drop_duplicates("county_fips")
    flags = pd.read_parquet(flags_path, columns=["county_fips", "metro2013", "rucc2013"])
    flags = flags.drop_duplicates("county_fips")
    counties = counties.merge(flags, on="county_fips", how="left", validate="one_to_one")
    county_exposure = build_county_exposure(qcew, exposure, counties)
    save_frame(
        county_exposure,
        pivot / "county_predicted_heat_exposure_2010_v1.parquet",
        pivot / "county_predicted_heat_exposure_2010_v1.dta",
    )

    exposure_panel = panel.loc[panel.ppml_core_sample.astype(bool)].merge(
        county_exposure, on=["county_fips", "state_fips", "county_id", "state_id"],
        how="left", validate="many_to_one", suffixes=("", "_county"),
    )
    save_frame(
        exposure_panel,
        pivot / "county_week_exposure_ppml_core_v1.parquet",
        pivot / "county_week_exposure_ppml_core_v1.dta",
    )

    common_audit = pd.DataFrame(common_iterations)
    common_audit["support"] = "primary_intersection"
    tally_audit = pd.DataFrame(tally_iterations)
    tally_audit["support"] = "tally_own"
    pd.concat([common_audit, tally_audit], ignore_index=True).to_csv(
        audit_dir / "final_pivot_common_support_audit.csv", index=False, lineterminator="\n"
    )

    audit_rows = [
        {"metric": "county_universe", "value": len(county_exposure), "note": "48-state Gate 2 county universe"},
        {"metric": "primary_exposure_counties", "value": int(county_exposure.exposure_primary_eligible.sum()), "note": "sector coverage >=80%"},
        {"metric": "primary_exposure_county_pct", "value": 100 * county_exposure.exposure_primary_eligible.mean(), "note": "unweighted county share"},
        {"metric": "employment_weighted_sector_coverage", "value": np.average(county_exposure.sector_coverage.dropna(), weights=county_exposure.loc[county_exposure.sector_coverage.notna(), "private_emp_2010"]), "note": "2010 private-employment weighted"},
        {"metric": "naics3_eligible_counties", "value": int(county_exposure.exposure_naics3_eligible.sum()), "note": "published NAICS3 coverage >=80%"},
        {"metric": "median_naics3_coverage", "value": county_exposure.naics3_coverage.median(), "note": "county median"},
        {"metric": "common_support_rows", "value": int(common.sum()), "note": "iterative intersection across four primary outcomes"},
        {"metric": "common_support_petitions", "value": int(progression.loc[common, "rc_petition_count"].sum()), "note": "all petitions on common support"},
        {"metric": "common_support_certifications", "value": int(progression.loc[common, "certified_rep_365_count"].sum()), "note": "closure-based certifications"},
        {"metric": "common_support_tally_certifications", "value": int(progression.loc[common, TALLY_OUTCOME].sum()), "note": "union-to-certify tally proxy"},
    ]
    pd.DataFrame(audit_rows).to_csv(
        audit_dir / "final_pivot_data_audit.csv", index=False, lineterminator="\n"
    )

    outputs = [
        pivot / "state_week_dynamic_v1.parquet",
        pivot / "progression_common_support_v1.parquet",
        pivot / "county_predicted_heat_exposure_2010_v1.parquet",
        pivot / "county_week_exposure_ppml_core_v1.parquet",
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {str(p.relative_to(root)).replace("\\", "/"): sha256(p) for p in [panel_path, prog_path, qcew_path, exposure_path]},
        "outputs": {str(p.relative_to(root)).replace("\\", "/"): sha256(p) for p in outputs},
        "heat_blocks": HEAT_BLOCKS,
        "common_support_outcomes": PRIMARY_OUTCOMES,
    }
    (pivot / "final_pivot_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"audit": audit_rows, "manifest": manifest}, indent=2, default=str))

if __name__ == "__main__":
    main()
