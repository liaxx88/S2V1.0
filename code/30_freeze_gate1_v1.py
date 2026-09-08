from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

EXPECTED = {
    "rc_main_sample": 25_965,
    "all_region_rc": 26_659,
    "exact_census_address_matches": 9_493,
    "county_fips_matches": 22_596,
    "county_match_rate_pct": 87.02,
    "exact_address_or_clear_location_rate_pct": 89.33,
    "election_merge": 18_541,
    "election_merge_rate_pct": 71.41,
}

SNAPSHOTS = {
    "nlrb_petitions_gate1_v1.parquet": "nlrb_petitions_master.csv",
    "nlrb_elections_gate1_v1.parquet": "nlrb_elections_rc.csv",
    "nlrb_case_election_gate1_v1.parquet": "nlrb_petition_progression.csv",
    "nlrb_geocode_gate1_v1.parquet": "nlrb_geography_master.csv",
}

AUDITS = (
    "gate1_summary.csv",
    "gate1_by_year.csv",
    "gate1_by_state.csv",
    "gate1_geocode_quality.csv",
    "gate1_election_merge.csv",
)

DATE_COLUMNS = {"date_filed", "date_closed", "tally_date", "first_tally_date", "last_tally_date"}
STRING_COLUMNS = {
    "case_number", "case_group", "case_subtype", "unit_id", "election_result_id",
    "state", "county_fips", "preliminary_county_fips", "state_fips", "tract", "block",
    "geocode_zip", "date_filed_raw", "date_closed_raw", "tally_date_raw",
    "employees_on_petition_raw", "voters_raw", "eligible_voters_raw", "void_ballots_raw",
    "votes_for_union_1_raw", "votes_for_union_2_raw", "votes_for_union_3_raw",
    "votes_against_raw", "total_ballots_counted_raw", "challenged_ballots_raw",
}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def read_typed_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    for column in frame.columns:
        if column in DATE_COLUMNS:
            frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
        elif column in STRING_COLUMNS or column.endswith("_raw"):
            continue
        else:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            nonblank = frame[column].ne("")
            if nonblank.sum() == numeric.notna().sum():
                frame[column] = numeric
    return frame

def flag(frame: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(frame[name], errors="coerce").fillna(0).astype(int).eq(1)

def validate_and_build_audits(nlrb_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    frames = {target: read_typed_csv(nlrb_dir / source) for target, source in SNAPSHOTS.items()}
    petitions = frames["nlrb_petitions_gate1_v1.parquet"].copy()
    elections = frames["nlrb_elections_gate1_v1.parquet"].copy()
    progression = frames["nlrb_case_election_gate1_v1.parquet"].copy()
    geography = frames["nlrb_geocode_gate1_v1.parquet"].copy()

    for name, frame in {
        "petitions": petitions, "progression": progression, "geography": geography
    }.items():
        if frame["case_number"].duplicated().any():
            raise ValueError(f"{name} is not unique by case_number")
    if elections["election_result_id"].duplicated().any():
        raise ValueError("elections is not unique by election_result_id")

    audit = petitions[["case_number", "filing_year", "state", "main_geo"]].merge(
        geography[[
            "case_number", "county_fips", "geocode_quality", "geocode_quality_label",
            "has_street_address"
        ]], on="case_number", how="left", validate="one_to_one"
    ).merge(
        progression[["case_number", "election_held"]], on="case_number", how="left",
        validate="one_to_one"
    )

    main = flag(audit, "main_geo")
    exact = pd.to_numeric(audit["geocode_quality"], errors="coerce").eq(1)
    county = audit["county_fips"].fillna("").astype(str).str.strip().ne("")
    clear = flag(audit, "has_street_address") | pd.to_numeric(
        audit["geocode_quality"], errors="coerce"
    ).between(1, 3)
    merged = flag(audit, "election_held")

    actual = {
        "rc_main_sample": int(main.sum()),
        "all_region_rc": int(len(audit)),
        "exact_census_address_matches": int((main & exact).sum()),
        "county_fips_matches": int((main & county).sum()),
        "county_match_rate_pct": round(100 * (main & county).sum() / main.sum(), 2),
        "exact_address_or_clear_location_rate_pct": round(100 * (main & clear).sum() / main.sum(), 2),
        "election_merge": int((main & merged).sum()),
        "election_merge_rate_pct": round(100 * (main & merged).sum() / main.sum(), 2),
    }
    if actual != EXPECTED:
        differences = {key: {"expected": EXPECTED[key], "actual": actual[key]}
                       for key in EXPECTED if EXPECTED[key] != actual[key]}
        raise ValueError(f"Gate 1 frozen-stat validation failed: {differences}")

    summary_rows = [
        ("rc_main_sample", actual["rc_main_sample"], actual["all_region_rc"],
         100 * actual["rc_main_sample"] / actual["all_region_rc"], "Contiguous 48 states plus DC"),
        ("all_region_rc", actual["all_region_rc"], actual["all_region_rc"], 100.0,
         "All official 2011-2024 RC petitions"),
        ("exact_census_address_matches", actual["exact_census_address_matches"], actual["rc_main_sample"],
         100 * actual["exact_census_address_matches"] / actual["rc_main_sample"],
         "Official Census Batch Geocoder exact address match"),
        ("county_fips_matches", actual["county_fips_matches"], actual["rc_main_sample"],
         100 * actual["county_fips_matches"] / actual["rc_main_sample"],
         "Exact address, unique ZIP, or unique place/county"),
        ("exact_address_or_clear_location", int((main & clear).sum()), actual["rc_main_sample"],
         100 * (main & clear).sum() / actual["rc_main_sample"],
         "Parsed street address or official unambiguous county assignment"),
        ("election_merge", actual["election_merge"], actual["rc_main_sample"],
         100 * actual["election_merge"] / actual["rc_main_sample"],
         "Any official RC election result matched by Case Number"),
    ]
    summary = pd.DataFrame(summary_rows, columns=["metric", "n", "denominator", "rate_pct", "definition"])
    summary["rate_pct"] = summary["rate_pct"].round(4)
    summary["gate"] = "PASS"
    summary["version"] = "v1"

    def grouped(keys: list[str]) -> pd.DataFrame:
        base = audit.assign(
            is_main=main.astype(int), county_matched=county.astype(int), exact_address=exact.astype(int),
            clear_location=clear.astype(int), election_merged=merged.astype(int)
        )
        out = base.groupby(keys, dropna=False).agg(
            all_region_rc=("case_number", "size"), rc_main_sample=("is_main", "sum"),
            county_fips_matches=("county_matched", lambda x: int((x * base.loc[x.index, "is_main"]).sum())),
            exact_census_address_matches=("exact_address", lambda x: int((x * base.loc[x.index, "is_main"]).sum())),
            exact_or_clear_location=("clear_location", lambda x: int((x * base.loc[x.index, "is_main"]).sum())),
            election_merge=("election_merged", lambda x: int((x * base.loc[x.index, "is_main"]).sum())),
        ).reset_index()
        denominator = out["rc_main_sample"].astype(float).mask(out["rc_main_sample"].eq(0))
        out["county_match_rate_pct"] = (100 * out["county_fips_matches"] / denominator).round(4)
        out["exact_or_clear_location_rate_pct"] = (100 * out["exact_or_clear_location"] / denominator).round(4)
        out["election_merge_rate_pct"] = (100 * out["election_merge"] / denominator).round(4)
        return out

    by_year = grouped(["filing_year"]).sort_values("filing_year")
    by_state = grouped(["state"]).sort_values("state")

    quality = audit.assign(scope="all_region")
    quality_main = audit.loc[main].assign(scope="main_sample")
    geocode_quality = pd.concat([quality, quality_main], ignore_index=True).groupby(
        ["scope", "geocode_quality", "geocode_quality_label"], dropna=False
    ).size().rename("petitions").reset_index()
    totals = geocode_quality.groupby("scope")["petitions"].transform("sum")
    geocode_quality["share_pct"] = (100 * geocode_quality["petitions"] / totals).round(4)
    geocode_quality = geocode_quality.sort_values(["scope", "geocode_quality"])

    merge_rows = []
    for scope, subset in (("all_region", audit), ("main_sample", audit.loc[main])):
        for year_label, block in [("ALL", subset), *[(str(int(year)), group) for year, group in subset.groupby("filing_year")]]:
            total = len(block)
            n_merged = int(flag(block, "election_held").sum())
            for status, count in (("merged", n_merged), ("not_merged", total - n_merged)):
                merge_rows.append((scope, year_label, status, count, total, round(100 * count / total, 4)))
    election_merge = pd.DataFrame(merge_rows, columns=[
        "scope", "filing_year", "merge_status", "petitions", "denominator", "share_pct"
    ])

    audits = {
        "gate1_summary.csv": summary,
        "gate1_by_year.csv": by_year,
        "gate1_by_state.csv": by_state,
        "gate1_geocode_quality.csv": geocode_quality,
        "gate1_election_merge.csv": election_merge,
    }
    return frames, audits

def write_csv_atomic(frame: pd.DataFrame, target: Path) -> None:
    temp = target.with_suffix(target.suffix + ".tmp")
    frame.to_csv(temp, index=False, encoding="utf-8", lineterminator="\n")
    os.replace(temp, target)

def write_parquet_atomic(frame: pd.DataFrame, target: Path, source_hash: str) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError(
            "pyarrow is required."
        ) from error
    table = pa.Table.from_pandas(frame, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata.update({
        b"project": b"Heat, Worker Voice, and the Initiation of Formal Representation",
        b"gate": b"Gate 1",
        b"version": b"v1",
        b"frozen": b"true",
        b"source_sha256": source_hash.encode("ascii"),
    })
    table = table.replace_schema_metadata(metadata)
    temp = target.with_suffix(target.suffix + ".tmp")
    pq.write_table(table, temp, compression="zstd", use_dictionary=True)
    os.replace(temp, target)

def verify_existing(root: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    for relative, recorded in manifest["files"].items():
        path = root / relative
        if not path.exists():
            failures.append(f"missing {relative}")
        elif sha256(path) != recorded["sha256"]:
            failures.append(f"hash mismatch {relative}")
    if failures:
        raise RuntimeError(
            "Gate 1 V1 is immutable and failed verification: " + "; ".join(failures)
        )
    print(f"Verified immutable Gate 1 V1 ({len(manifest['files'])} files); no files overwritten")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    vendor = root / "code" / "vendor" / "python"
    if vendor.exists():
        sys.path.insert(0, str(vendor))

    nlrb_dir = root / "data" / "clean" / "nlrb"
    gate_dir = root / "data" / "clean" / "gate1"
    audit_dir = root / "data" / "clean" / "results"
    manifest_path = gate_dir / "gate1_v1_manifest.json"
    gate_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists():
        verify_existing(root, manifest_path)
        return

    preexisting = [path for path in [*(gate_dir / name for name in SNAPSHOTS),
                                      *(audit_dir / name for name in AUDITS)] if path.exists()]
    if preexisting:
        raise RuntimeError(
            "Refusing to create V1 around pre-existing unmanifested files: "
            + ", ".join(str(path) for path in preexisting)
        )

    frames, audits = validate_and_build_audits(nlrb_dir)
    source_hashes = {source: sha256(nlrb_dir / source) for source in SNAPSHOTS.values()}
    for target_name, source_name in SNAPSHOTS.items():
        write_parquet_atomic(frames[target_name], gate_dir / target_name, source_hashes[source_name])
    for target_name, frame in audits.items():
        write_csv_atomic(frame, audit_dir / target_name)

    files = {}
    for path in [*(gate_dir / name for name in SNAPSHOTS), *(audit_dir / name for name in AUDITS)]:
        relative = path.relative_to(root).as_posix()
        files[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "gate": "Gate 1",
        "version": "v1",
        "status": "PASS",
        "immutable": True,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "rule": "No post-weather sample redefinition; objective coding errors require documented versioning.",
        "expected_statistics": EXPECTED,
        "source_files": {name: {"sha256": digest} for name, digest in source_hashes.items()},
        "files": files,
    }
    temp_manifest = manifest_path.with_suffix(".json.tmp")
    temp_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_manifest, manifest_path)
    print("Created immutable Gate 1 V1; all archived statistics validated; Gate 1 PASS")

if __name__ == "__main__":
    main()
