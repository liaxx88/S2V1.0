from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

CONTEXTS = {
    "4.C.2.b.1.b": "thermal_exposure",
    "4.C.2.a.1.c": "outdoor_weather",
    "4.C.2.a.1.b": "nonclimate_controlled",
    "4.C.2.a.1.d": "outdoor_under_cover",
    "4.C.2.a.1.e": "open_vehicle_equipment",
}

EXPOSURE_COLUMNS = [
    "thermal_exposure",
    "outdoor_weather",
    "nonclimate_controlled",
    "outdoor_under_cover",
    "open_vehicle_equipment",
    "outdoor_exposure",
    "heat_exposure_index",
]

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def normalize_soc(value: object) -> str | None:
    if pd.isna(value):
        return None
    match = re.search(r"(\d{2})-(\d{4})", str(value))
    return f"{match.group(1)}-{match.group(2)}" if match else None

def normalize_naics(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace(".0", "")
    return text if re.fullmatch(r"\d{2,6}|\d{2}-\d{2}", text) else None

def weighted_mean(frame: pd.DataFrame, column: str) -> float:
    valid = frame[column].notna() & frame["employment"].notna() & (frame["employment"] > 0)
    if not valid.any():
        return np.nan
    return float(np.average(frame.loc[valid, column], weights=frame.loc[valid, "employment"]))

def read_oews_member(archive: zipfile.ZipFile, member: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(archive.read(member)), dtype={"naics": str, "occ_code": str})

def aggregate_industries(
    source: pd.DataFrame,
    occupation_exposure: pd.DataFrame,
    level: str,
) -> pd.DataFrame:
    source = source.copy()
    source["occ_code"] = source["occ_code"].map(normalize_soc)
    source["employment"] = pd.to_numeric(source["tot_emp"], errors="coerce")
    source["naics_source"] = source["naics"].map(normalize_naics)

    totals = (
        source.loc[source["o_group"].eq("total"), ["naics_source", "tot_emp"]]
        .assign(industry_total_employment=lambda d: pd.to_numeric(d["tot_emp"], errors="coerce"))
        .drop(columns="tot_emp")
        .drop_duplicates("naics_source")
    )
    detail = source.loc[source["o_group"].eq("detailed")].copy()
    detail = detail.merge(occupation_exposure, on="occ_code", how="left", validate="many_to_one")

    records: list[dict[str, object]] = []
    for naics, group in detail.groupby("naics_source", sort=True, dropna=True):
        observed = float(group["employment"].sum(min_count=1))
        matched_mask = group["heat_exposure_index"].notna() & group["employment"].notna()
        matched = float(group.loc[matched_mask, "employment"].sum(min_count=1))
        row: dict[str, object] = {
            "naics_source": naics,
            "naics_title": group["naics_title"].dropna().iloc[0],
            "own_code_source": str(group["own_code"].dropna().iloc[0]),
            "detailed_occupations_published": int(group["occ_code"].notna().sum()),
            "detailed_occupations_mapped": int(group.loc[matched_mask, "occ_code"].nunique()),
            "detailed_employment_observed": observed,
            "detailed_employment_mapped": matched,
            "occupation_mapping_coverage": matched / observed if observed > 0 else np.nan,
        }
        for column in EXPOSURE_COLUMNS:
            row[column] = weighted_mean(group, column)
        records.append(row)

    result = pd.DataFrame(records).merge(totals, on="naics_source", how="left", validate="one_to_one")
    result["detailed_employment_observed_share"] = (
        result["detailed_employment_observed"] / result["industry_total_employment"]
    )

    if level == "naics2":
        expansion = {
            "31-33": ["31", "32", "33"],
            "44-45": ["44", "45"],
            "48-49": ["48", "49"],
        }
        expanded: list[pd.Series] = []
        for _, row in result.iterrows():
            codes = expansion.get(str(row["naics_source"]), [str(row["naics_source"])[:2]])
            for code in codes:
                copy = row.copy()
                copy["naics_2017"] = code
                copy["shared_sector_estimate"] = int(len(codes) > 1)
                expanded.append(copy)
        result = pd.DataFrame(expanded)
    elif level == "naics3":
        result["naics_2017"] = result["naics_source"].str[:3]
        result["shared_sector_estimate"] = 0
    else:
        raise ValueError(level)

    result["naics_level"] = level
    result["nlra_scope_flag"] = (~result["naics_2017"].isin(["11", "481", "482", "814", "99", "999"])).astype(int)
    result["exposure_source"] = "O*NET 24.1 + OEWS May 2019"
    result["onet_version"] = "24.1 (November 2019)"
    result["oews_version"] = "May 2019 (2017 NAICS; hybrid SOC)"

    rank = result["heat_exposure_index"].rank(method="first")
    result["heat_exposure_quintile"] = pd.qcut(rank, 5, labels=False).astype("Int64") + 1
    return result

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root / "code" / "vendor" / "python"))

    onet_zip_path = root / "data" / "raw" / "onet" / "24_1" / "db_24_1_text.zip"
    oews_zip_path = root / "data" / "raw" / "oews" / "2019" / "oesm19in4.zip"
    hybrid_path = root / "data" / "raw" / "oews" / "2019" / "oes_2019_hybrid_structure.xlsx"
    output_dir = root / "data" / "clean" / "gate3"
    audit_dir = root / "data" / "clean" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(onet_zip_path) as archive:
        work = pd.read_csv(archive.open("db_24_1_text/Work Context.txt"), sep="\t")
        occupations = pd.read_csv(archive.open("db_24_1_text/Occupation Data.txt"), sep="\t")

    selected = work.loc[
        work["Element ID"].isin(CONTEXTS)
        & work["Scale ID"].eq("CX")
        & work["Data Value"].notna()
    ].copy()
    if selected.duplicated(["O*NET-SOC Code", "Element ID"]).any():
        raise RuntimeError("O*NET work-context ratings are not unique by occupation and element.")
    selected["context_name"] = selected["Element ID"].map(CONTEXTS)
    occupation = selected.pivot(index="O*NET-SOC Code", columns="context_name", values="Data Value").reset_index()
    occupation.columns.name = None
    occupation = occupation.merge(
        occupations[["O*NET-SOC Code", "Title"]], on="O*NET-SOC Code", how="left", validate="one_to_one"
    )
    occupation["soc_2010"] = occupation["O*NET-SOC Code"].map(normalize_soc)
    occupation["outdoor_exposure"] = occupation[["outdoor_weather", "outdoor_under_cover"]].max(axis=1)

    

    composite_components = [
        "thermal_exposure",
        "outdoor_exposure",
        "nonclimate_controlled",
        "open_vehicle_equipment",
    ]
    for column in composite_components:
        mean = occupation[column].mean()
        std = occupation[column].std(ddof=0)
        occupation[f"z_{column}"] = (occupation[column] - mean) / std
    occupation["heat_exposure_index"] = occupation[[f"z_{c}" for c in composite_components]].mean(axis=1)

    

    soc_exposure = (
        occupation.groupby("soc_2010", as_index=False)
        .agg(
            **{column: (column, "mean") for column in EXPOSURE_COLUMNS},
            onet_specializations=("O*NET-SOC Code", "nunique"),
        )
    )

    hybrid = pd.read_excel(
        hybrid_path,
        sheet_name="OES2019 Hybrid",
        header=5,
        dtype=str,
    )
    hybrid = hybrid.rename(columns={"2018 SOC Code ": "2018 SOC Code"})
    hybrid["occ_code"] = hybrid["OES 2019 Estimates Code"].map(normalize_soc)
    hybrid["soc_2010"] = hybrid["2010 SOC Code"].map(normalize_soc)
    hybrid = hybrid.loc[hybrid["occ_code"].notna()].copy()
    hybrid_pairs = hybrid[["occ_code", "soc_2010"]].dropna().drop_duplicates()
    hybrid_pairs = hybrid_pairs.merge(soc_exposure, on="soc_2010", how="left", validate="many_to_one")
    hybrid_exposure = (
        hybrid_pairs.groupby("occ_code", as_index=False)
        .agg(
            **{column: (column, "mean") for column in EXPOSURE_COLUMNS},
            mapped_soc2010_count=("heat_exposure_index", "count"),
            crosswalk_soc2010_count=("soc_2010", "nunique"),
        )
    )
    hybrid_titles = (
        hybrid[["occ_code", "OES 2019 Estimates Title"]]
        .dropna()
        .drop_duplicates("occ_code")
        .rename(columns={"OES 2019 Estimates Title": "occ_title"})
    )
    hybrid_exposure = hybrid_titles.merge(hybrid_exposure, on="occ_code", how="left", validate="one_to_one")

    with zipfile.ZipFile(oews_zip_path) as archive:
        sector = read_oews_member(archive, "oesm19in4/natsector_M2019_dl.xlsx")
        naics3 = read_oews_member(archive, "oesm19in4/nat3d_M2019_dl.xlsx")

    industry2 = aggregate_industries(sector, hybrid_exposure, "naics2")
    industry3 = aggregate_industries(naics3, hybrid_exposure, "naics3")
    industry = pd.concat([industry2, industry3], ignore_index=True)
    industry = industry.sort_values(["naics_level", "naics_2017"]).reset_index(drop=True)

    if industry.duplicated(["naics_level", "naics_2017"]).any():
        raise RuntimeError("Industry exposure output is not unique by NAICS level and code.")
    if industry["occupation_mapping_coverage"].min() < 0.85:
        raise RuntimeError("Hybrid-SOC mapping coverage unexpectedly fell below 85 percent.")

    occupation_output = output_dir / "occupation_heat_exposure_onet24_1.parquet"
    hybrid_output = output_dir / "oews2019_hybrid_heat_exposure.parquet"
    industry_parquet = output_dir / "industry_heat_exposure_2019.parquet"
    industry_csv = output_dir / "industry_heat_exposure_2019.csv"
    industry_dta = output_dir / "industry_heat_exposure_2019.dta"
    occupation.to_parquet(occupation_output, index=False)
    hybrid_exposure.to_parquet(hybrid_output, index=False)
    industry.to_parquet(industry_parquet, index=False)
    industry.to_csv(industry_csv, index=False)

    stata = industry.copy()
    stata["heat_exposure_quintile"] = stata["heat_exposure_quintile"].astype(float)
    stata = stata.rename(
        columns={"detailed_employment_observed_share": "detail_emp_observed_share"}
    )
    stata.to_stata(industry_dta, write_index=False, version=118)

    metrics = [
        ("onet_version", "24.1 (November 2019)", "Frozen pre-pandemic occupational ratings"),
        ("oews_version", "May 2019", "2017 NAICS; hybrid 2010/2018 SOC"),
        ("onet_occupations_with_context", len(occupation), "O*NET-SOC occupations"),
        ("onet_parent_soc_with_context", soc_exposure["soc_2010"].nunique(), "2010 SOC parents"),
        ("oews_hybrid_codes", hybrid_exposure["occ_code"].nunique(), "Official crosswalk codes"),
        (
            "oews_hybrid_codes_mapped",
            int(hybrid_exposure["heat_exposure_index"].notna().sum()),
            "Codes with at least one mapped O*NET 2010 SOC rating",
        ),
        ("naics2_industries", len(industry2), "Expanded 2017 NAICS sectors"),
        ("naics3_industries", len(industry3), "Published 3-digit industries"),
        ("naics2_min_occ_mapping_coverage", industry2["occupation_mapping_coverage"].min(), "Employment share"),
        ("naics3_min_occ_mapping_coverage", industry3["occupation_mapping_coverage"].min(), "Employment share"),
        ("naics2_median_occ_mapping_coverage", industry2["occupation_mapping_coverage"].median(), "Employment share"),
        ("naics3_median_occ_mapping_coverage", industry3["occupation_mapping_coverage"].median(), "Employment share"),
    ]
    pd.DataFrame(metrics, columns=["metric", "value", "note"]).to_csv(
        audit_dir / "gate3_exposure_audit.csv", index=False
    )
    industry[
        [
            "naics_level",
            "naics_2017",
            "naics_title",
            "occupation_mapping_coverage",
            "detailed_employment_observed_share",
            "thermal_exposure",
            "outdoor_exposure",
            "nonclimate_controlled",
            "heat_exposure_index",
            "heat_exposure_quintile",
        ]
    ].to_csv(audit_dir / "gate3_exposure_by_industry.csv", index=False)

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "construction_status": "FROZEN_V1",
        "outcome_data_used": False,
        "composite_definition": (
            "Equal-weight mean of O*NET-occupation z-scores for thermal exposure, "
            "outdoor exposure (maximum of exposed-to-weather and under-cover), "
            "non-climate-controlled indoor work, and open vehicle/equipment."
        ),
        "hybrid_mapping": (
            "Official BLS May 2019 hybrid-to-2010-SOC crosswalk; equal mean across "
            "multiple contributing 2010 SOCs and O*NET specializations."
        ),
        "raw_sha256": {
            str(onet_zip_path.relative_to(root)).replace("\\", "/"): sha256(onet_zip_path),
            str(oews_zip_path.relative_to(root)).replace("\\", "/"): sha256(oews_zip_path),
            str(hybrid_path.relative_to(root)).replace("\\", "/"): sha256(hybrid_path),
        },
        "output_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in [
                occupation_output,
                hybrid_output,
                industry_parquet,
                industry_csv,
                industry_dta,
            ]
        },
    }
    (output_dir / "industry_heat_exposure_2019_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(json.dumps({"rows": len(industry), "metrics": dict((k, v) for k, v, _ in metrics)}, indent=2))

if __name__ == "__main__":
    main()
