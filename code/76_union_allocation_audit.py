from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import pyarrow as pa
import pyarrow.parquet as pq

PARENT_PATTERNS = OrderedDict([
    ("TEAMSTERS", r"TEAMSTER"),
    ("SEIU", r"SERVICE EMPLOYEES INTERNATIONAL|SEIU|\b1199\b"),
    ("UFCW", r"UNITED FOOD.*COMMERCIAL|\bUFCW\b"),
    ("IBEW", r"ELECTRICAL WORKERS|\bIBEW\b"),
    ("IATSE", r"THEATRICAL STAGE|\bIATSE\b"),
    ("USW", r"UNITED STEELWORKERS|UNITED STEEL WORKERS|UNITED STEEL PAPER|\bUSW\b"),
    ("UAW", r"UNITED AUTO(?:MOBILE)? WORKERS|AUTO.*AEROSPACE.*AGRICULTURAL|\bUAW\b"),
    ("IAM", r"MACHINIST|\bIAMAW\b|\bIAM\b"),
    ("UNITE_HERE", r"UNITE\s*HERE|HOTEL.*RESTAURANT EMPLOYEES|\bHERE LOCAL"),
    ("CWA", r"COMMUNICATIONS WORKERS|\bCWA\b"),
    ("AFSCME", r"STATE.*COUNTY.*MUNICIPAL EMPLOYEES|\bAFSCME\b"),
    ("ATU", r"AMALGAMATED TRANSIT|\bATU\b"),
    ("LIUNA", r"LABORERS.? INTERNATIONAL|\bLIUNA\b|LABORERS.? LOCAL"),
    ("IUOE", r"OPERATING ENGINEERS|\bIUOE\b"),
    ("CARPENTERS", r"CARPENTER"),
    ("SMART", r"SHEET METAL.*AIR.*RAIL|\bSMART\b|SHEET METAL WORKERS"),
    ("UA_PLUMBERS_PIPEFITTERS", r"UNITED ASSOCIATION.*JOURNEYMEN|PLUMBER|PIPEFITTER"),
    ("NNU", r"NATIONAL NURSES UNITED|CALIFORNIA NURSES ASSOCIATION|NATIONAL NURSES ORGANIZING"),
    ("AFT", r"FEDERATION OF TEACHERS|\bAFT\b"),
    ("NEA", r"NATIONAL EDUCATION ASSOCIATION|\bNEA\b"),
    ("OPEIU", r"OFFICE.*PROFESSIONAL EMPLOYEES|\bOPEIU\b"),
    ("ILWU", r"LONGSHORE.*WAREHOUSE|\bILWU\b"),
    ("ILA", r"INTERNATIONAL LONGSHOREMEN|\bILA\b"),
    ("RWDSU", r"RETAIL.*WHOLESALE.*DEPARTMENT|\bRWDSU\b"),
    ("WORKERS_UNITED", r"\bWORKERS UNITED\b"),
    ("SAG_AFTRA", r"SAG.AFTRA|SCREEN ACTORS|TELEVISION.*RADIO ARTISTS"),
    ("AFM", r"FEDERATION OF MUSICIANS|\bAFM\b"),
    ("AFL_CIO_DIRECTLY_CHARTERED", r"AFL.CIO.*DIRECTLY CHARTERED"),
    ("UE", r"UNITED ELECTRICAL.*RADIO.*MACHINE WORKERS|\bUE LOCAL"),
    ("NATCA", r"AIR TRAFFIC CONTROLLERS|\bNATCA\b"),
    ("APWU", r"AMERICAN POSTAL WORKERS|\bAPWU\b"),
    ("NALC", r"LETTER CARRIERS|\bNALC\b"),
    ("AAUP", r"UNIVERSITY PROFESSORS|\bAAUP\b"),
])

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def petitioner_union(participants: object) -> str:
    text = "" if pd.isna(participants) else str(participants)
    match = re.search(
        r"Petitioner,\s*Union,\s*(.*?)(?=\s(?:Employer|Petitioner),\s*"
        r"(?:Additional Service|Legal Representative|Employer|Union),|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    value = match.group(1).strip()

    value = re.sub(r",\s*[^,]+,\s*[A-Z]{2},\s*\d{5}(?:-\d{4})?.*$", "", value)
    value = re.sub(r",\s*\(?\d{3}\)?[-\s]\d{3}[-\s]\d{4}.*$", "", value)
    return value.strip(" ,")

def normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value).upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def generic_family(text: str) -> str:
    value = re.sub(r"\bAFL CIO\b|\bCLC\b|\bAFL\b|\bCIO\b", " ", text)
    value = re.split(
        r"\b(?:LOCAL|LODGE|DISTRICT|COUNCIL|CHAPTER|DIVISION|REGION|UNIT)\b(?:\s+(?:NO\s*)?\d+[A-Z]?)?",
        value,
        maxsplit=1,
    )[0]
    value = re.sub(r"\b(?:INTERNATIONAL|NATIONAL)\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    words = value.split()
    if len(words) > 10:
        value = " ".join(words[:10])
    return value

def map_parent(text: str) -> tuple[str, str]:
    for parent, pattern in PARENT_PATTERNS.items():
        if re.search(pattern, text):
            return parent, "dictionary"
    family = generic_family(text)
    if len(family) >= 5 and re.search(r"[A-Z]", family):
        return "INDEPENDENT__" + family.replace(" ", "_"), "deterministic_family"
    return "", "unmapped"

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    gate1 = root / "data" / "clean" / "gate1"
    pivot = root / "data" / "clean" / "final_pivot"
    audit_dir = root / "data" / "clean" / "results"
    petitions_path = gate1 / "nlrb_petitions_gate1_v1.parquet"
    geocode_path = gate1 / "nlrb_geocode_gate1_v1.parquet"
    panel_path = root / "data" / "clean" / "gate2" / "county_week_analysis_v1.parquet"
    petitions = pd.read_parquet(petitions_path)
    geocode = pd.read_parquet(geocode_path, columns=["case_number", "county_fips"])
    petitions = petitions.merge(geocode, on="case_number", how="left", validate="one_to_one")
    ct_path = audit_dir / "gate2_county_harmonization.csv"
    if ct_path.exists():
        ct = pd.read_csv(ct_path, dtype=str, keep_default_na=False)[["case_number", "target_county_fips"]]
        petitions = petitions.merge(ct, on="case_number", how="left", validate="one_to_one")
        use_target = petitions.target_county_fips.str.fullmatch(r"\d{5}", na=False)
        petitions.loc[use_target, "county_fips"] = petitions.loc[use_target, "target_county_fips"]
    petitions.date_filed = pd.to_datetime(petitions.date_filed)
    petitions["week_start"] = petitions.date_filed - pd.to_timedelta(petitions.date_filed.dt.weekday, unit="D")
    petitions["state_fips"] = petitions.county_fips.fillna("").astype(str).str[:2]

    panel = pd.read_parquet(panel_path)
    panel.week_start = pd.to_datetime(panel.week_start)
    keys = panel.loc[panel.analysis_sample.astype(bool), ["county_fips", "week_start"]].copy()
    keys["gate2"] = 1
    cohort = petitions.merge(keys, on=["county_fips", "week_start"], how="left", validate="many_to_one")
    cohort = cohort.loc[cohort.gate2.eq(1)].copy()
    if len(cohort) != 21_990:
        raise ValueError(f"Gate 2 cohort mismatch: {len(cohort):,}")

    parsed = cohort.participants_raw.map(petitioner_union)
    direct = cohort.union_name_raw.fillna("").astype(str).str.strip()
    cohort["union_text_source"] = np.where(parsed.str.len().gt(0), "participants", np.where(direct.str.len().gt(0), "union_field", "missing"))
    cohort["union_text"] = parsed.where(parsed.str.len().gt(0), direct)
    cohort["union_normalized"] = cohort.union_text.map(normalize_text)
    mapped = cohort.union_normalized.map(map_parent)
    cohort["parent_union"] = [item[0] for item in mapped]
    cohort["mapping_method"] = [item[1] for item in mapped]
    cohort["union_year_month"] = cohort.date_filed.dt.to_period("M").astype(str)

    

    cohort["mapped"] = cohort.mapping_method.eq("dictionary")

    mapped_cohort = cohort.loc[cohort.mapped].copy()
    cell_stats = mapped_cohort.groupby(["parent_union", "state_fips", "union_year_month"]).agg(
        petitions=("case_number", "size"), counties=("county_fips", "nunique")
    ).reset_index()
    cell_stats["qualifying_cell"] = cell_stats.counties.ge(2)
    mapped_cohort = mapped_cohort.merge(
        cell_stats, on=["parent_union", "state_fips", "union_year_month"],
        how="left", validate="many_to_one",
    )
    multicounty_petitions = int(mapped_cohort.loc[mapped_cohort.qualifying_cell, "case_number"].nunique())
    mapping_rate = len(mapped_cohort) / len(cohort)
    multicounty_share = multicounty_petitions / len(mapped_cohort) if len(mapped_cohort) else 0
    gate_pass = mapping_rate >= 0.70 and multicounty_petitions >= 5_000 and multicounty_share >= 0.30

    audit_rows = [
        {"metric": "gate2_petition_cohorts", "value": len(cohort), "threshold": "fixed 21,990", "pass": len(cohort) == 21_990},
        {"metric": "parent_union_mapped", "value": len(mapped_cohort), "threshold": ">=70%", "pass": mapping_rate >= 0.70},
        {"metric": "parent_union_mapping_pct", "value": 100 * mapping_rate, "threshold": ">=70%", "pass": mapping_rate >= 0.70},
        {"metric": "multi_county_cell_petitions", "value": multicounty_petitions, "threshold": ">=5,000", "pass": multicounty_petitions >= 5_000},
        {"metric": "multi_county_share_mapped_pct", "value": 100 * multicounty_share, "threshold": ">=30%", "pass": multicounty_share >= 0.30},
        {"metric": "qualifying_union_state_month_cells", "value": int(cell_stats.qualifying_cell.sum()), "threshold": "descriptive", "pass": True},
        {"metric": "organizer_allocation_gate", "value": "PASS" if gate_pass else "HOLD", "threshold": "all three gates", "pass": gate_pass},
    ]
    pd.DataFrame(audit_rows).to_csv(audit_dir / "union_allocation_data_gate.csv", index=False, lineterminator="\n")
    method_counts = cohort.groupby("mapping_method").size().rename("petitions").reset_index()
    method_counts.to_csv(audit_dir / "union_mapping_methods.csv", index=False, lineterminator="\n")
    top = cohort.groupby(["parent_union", "mapping_method", "union_normalized"], dropna=False).size().rename("petitions").reset_index()
    top = top.sort_values("petitions", ascending=False).head(150)
    top.to_csv(audit_dir / "union_mapping_top150_review.csv", index=False, lineterminator="\n")
    cell_stats.to_csv(audit_dir / "union_state_month_cell_audit.csv", index=False, lineterminator="\n")

    petition_map = cohort[[
        "case_number", "county_fips", "state_fips", "date_filed", "week_start",
        "union_text_source", "union_normalized", "parent_union", "mapping_method",
        "union_year_month", "mapped",
    ]].copy()
    pq.write_table(pa.Table.from_pandas(petition_map, preserve_index=False), pivot / "petition_parent_union_v1.parquet", compression="zstd")

    if gate_pass:
        qualifying = cell_stats.loc[cell_stats.qualifying_cell, ["parent_union", "state_fips", "union_year_month"]]
        filings = mapped_cohort.merge(
            qualifying, on=["parent_union", "state_fips", "union_year_month"],
            how="inner", validate="many_to_one", suffixes=("", "_qual"),
        )
        filing_counts = filings.groupby(
            ["parent_union", "state_fips", "union_year_month", "county_fips", "week_start"]
        ).size().rename("union_petition_count").reset_index()

        state_month_panel = panel.loc[panel.analysis_sample.astype(bool)].copy()
        pieces: list[pd.DataFrame] = []
        for state, qcells in qualifying.groupby("state_fips", sort=True):
            base = state_month_panel.loc[state_month_panel.state_fips.eq(state)]
            for month, month_cells in qcells.groupby("union_year_month", sort=True):
                month_period = pd.Period(month, freq="M")
                month_start = month_period.start_time.normalize()
                month_end = month_period.end_time.normalize()

                

                base_month = base.loc[
                    base.week_start.between(month_start - pd.Timedelta(days=6), month_end)
                ]
                if base_month.empty:
                    continue
                for parent in month_cells.parent_union:
                    part = base_month.copy()
                    part["parent_union"] = parent
                    part["union_year_month"] = month
                    pieces.append(part)
        risk = pd.concat(pieces, ignore_index=True)
        risk = risk.merge(
            filing_counts,
            on=["parent_union", "state_fips", "union_year_month", "county_fips", "week_start"],
            how="left", validate="one_to_one",
        )
        risk["union_petition_count"] = risk.union_petition_count.fillna(0).astype(np.int16)
        risk["union_state_month_fe"] = pd.factorize(
            risk.parent_union + "|" + risk.state_fips + "|" + risk.union_year_month, sort=True
        )[0].astype(np.int32) + 1
        risk["parent_union_id"] = pd.factorize(risk.parent_union, sort=True)[0].astype(np.int16) + 1
        if risk.union_petition_count.sum() != multicounty_petitions:
            raise ValueError("Organizer risk set does not reproduce qualifying petition counts")
        risk_path = pivot / "union_allocation_risk_v1.parquet"
        pq.write_table(pa.Table.from_pandas(risk, preserve_index=False), risk_path, compression="zstd")
        stata = risk.copy()
        bool_cols = [c for c in stata if stata[c].dtype == bool]
        stata[bool_cols] = stata[bool_cols].astype(np.int8)
        stata.to_stata(
            pivot / "union_allocation_risk_v1.dta", write_index=False, version=118,
            convert_dates={"week_start": "td"},
        )

    status = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "gate_status": "PASS" if gate_pass else "HOLD",
        "mapping_rate": mapping_rate,
        "multi_county_petitions": multicounty_petitions,
        "multi_county_share_mapped": multicounty_share,
        "dictionary_patterns": list(PARENT_PATTERNS),
        "risk_set_definition": "All Gate 2 counties and Monday-start weeks in qualifying union-parent x state x filing-month cells",
        "sources": {
            str(petitions_path.relative_to(root)).replace("\\", "/"): sha256(petitions_path),
            str(panel_path.relative_to(root)).replace("\\", "/"): sha256(panel_path),
        },
    }
    (pivot / "union_allocation_gate_status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"audit": audit_rows, "status": status}, indent=2))

if __name__ == "__main__":
    main()
