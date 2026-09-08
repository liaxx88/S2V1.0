from __future__ import annotations

import hashlib
import json
import sys
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

def future_sum(series: pd.Series, start: int, end: int) -> pd.Series:
    width = end - start + 1

    
    return series.shift(-end).rolling(width, min_periods=width).sum()

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    audit = root / "data" / "clean" / "results"
    gate2 = root / "data" / "clean" / "gate2"
    gate25 = root / "data" / "clean" / "gate25"
    pivot = root / "data" / "clean" / "final_pivot"
    output = root / "data" / "clean" / "jeem_extension"
    output.mkdir(parents=True, exist_ok=True)

    panel_path = gate2 / "county_week_analysis_v1.parquet"
    support_path = gate25 / "gate25_final_esample_keys.dta"
    exposure_path = pivot / "county_predicted_heat_exposure_2010_v1.parquet"
    union_path = pivot / "petition_parent_union_v1.parquet"

    columns = [
        "county_fips", "state_fips", "week_start", "week", "week_index",
        "calendar_month", "calendar_year", "county_id", "state_id",
        "county_month_fe", "state_yearweek_fe", "rc_petition_count",
        "any_rc_petition", "p95_days", "p95_days_lag1_4",
        "p95_days_lag5_8", "p95_days_lag9_12", "p95_days_lag13_16",
        "p95_days_future9_16", "private_emp_lag12", "log_private_emp_lag12",
        "analysis_sample", "ppml_core_sample",
    ]
    panel = pd.read_parquet(panel_path, columns=columns)
    panel["week_start"] = pd.to_datetime(panel["week_start"])
    panel = panel.sort_values(["county_id", "week_index"]).reset_index(drop=True)
    if panel.duplicated(["county_fips", "week_start"]).any():
        raise ValueError("County-week panel is not unique")

    grouped = panel.groupby("county_id", sort=False, group_keys=False)
    for start, end in [(1, 4), (5, 8), (9, 12), (13, 16)]:
        panel[f"p95_days_future{start}_{end}"] = grouped["p95_days"].transform(
            lambda series, a=start, b=end: future_sum(series, a, b)
        ).astype(np.float32)
    reconstructed = panel["p95_days_future9_12"] + panel["p95_days_future13_16"]
    overlap = panel["p95_days_future9_16"].notna() & reconstructed.notna()
    if not np.allclose(
        panel.loc[overlap, "p95_days_future9_16"], reconstructed.loc[overlap],
        rtol=0, atol=1e-6,
    ):
        raise ValueError("New four-week future blocks do not reproduce specified future 9--16")

    panel = panel.loc[panel["analysis_sample"].astype(bool)].copy().reset_index(drop=True)
    if len(panel) != 2_260_083:
        raise ValueError(f"Unexpected analysis-sample county-week row count: {len(panel):,}")

    panel["county_woy_fe"] = pd.factorize(
        panel["county_fips"].astype(str) + "|" + panel["week"].astype(str).str.zfill(2),
        sort=True,
    )[0].astype(np.int32) + 1

    support = pd.read_stata(support_path, convert_dates=True)
    support["week_start"] = pd.to_datetime(support["week_start"])
    support = support[["county_fips", "week_start"]].copy()
    support["county_fips"] = support["county_fips"].astype(str).str.zfill(5)
    support["primary_esample"] = np.int8(1)
    panel["county_fips"] = panel["county_fips"].astype(str).str.zfill(5)
    panel = panel.merge(
        support, on=["county_fips", "week_start"], how="left", validate="one_to_one"
    )
    panel["primary_esample"] = panel["primary_esample"].fillna(0).astype(np.int8)
    if int(panel.primary_esample.sum()) != 192_690:
        raise ValueError("Primary PPML e(sample) key count mismatch")

    exposure = pd.read_parquet(
        exposure_path,
        columns=["county_fips", "metro2013", "private_emp_2010"],
    )
    exposure["county_fips"] = exposure["county_fips"].astype(str).str.zfill(5)
    if exposure.duplicated("county_fips").any():
        raise ValueError("County exposure file is not unique")
    counties = exposure[["county_fips", "private_emp_2010"]].dropna().copy()
    counties = counties.sort_values(["private_emp_2010", "county_fips"]).reset_index(drop=True)
    counties["private_emp_2010_q"] = pd.qcut(
        np.arange(len(counties)), 4, labels=[1, 2, 3, 4]
    ).astype(np.int8)
    exposure = exposure.merge(
        counties[["county_fips", "private_emp_2010_q"]],
        on="county_fips", how="left", validate="one_to_one",
    )
    panel = panel.merge(exposure, on="county_fips", how="left", validate="many_to_one")
    panel["metro2013"] = panel["metro2013"].astype("float32")
    panel["private_emp_2010_q"] = panel["private_emp_2010_q"].astype("float32")

    selected = [
        "county_fips", "state_fips", "week_start", "week", "week_index",
        "calendar_month", "calendar_year", "county_id", "state_id",
        "county_month_fe", "county_woy_fe", "state_yearweek_fe",
        "rc_petition_count", "any_rc_petition", "p95_days",
        "p95_days_lag1_4", "p95_days_lag5_8", "p95_days_lag9_12",
        "p95_days_lag13_16", "p95_days_future1_4", "p95_days_future5_8",
        "p95_days_future9_12", "p95_days_future13_16", "private_emp_lag12",
        "log_private_emp_lag12", "analysis_sample", "ppml_core_sample",
        "primary_esample", "metro2013", "private_emp_2010",
        "private_emp_2010_q",
    ]
    extension = panel[selected].copy()
    for name in ["analysis_sample", "ppml_core_sample"]:
        extension[name] = extension[name].astype(np.int8)

    parquet_path = output / "jeem_extension_county_week_v1.parquet"
    dta_path = output / "jeem_extension_county_week_v1.dta"
    pq.write_table(
        pa.Table.from_pandas(extension, preserve_index=False), parquet_path, compression="zstd"
    )
    stata = extension.copy()
    stata.to_stata(
        dta_path, write_index=False, version=118, convert_dates={"week_start": "td"}
    )

    union = pd.read_parquet(union_path)
    union["week_start"] = pd.to_datetime(union["week_start"])
    union = union.loc[union["mapped"].astype(bool)].copy()
    exact_cells = union.groupby(
        ["parent_union", "state_fips", "week_start"], dropna=False
    ).agg(petitions=("case_number", "size"), counties=("county_fips", "nunique")).reset_index()
    exact_cells["qualifying_cell"] = exact_cells["counties"].ge(2)
    qualifying = exact_cells.loc[exact_cells.qualifying_cell]
    qualifying_petitions = int(qualifying.petitions.sum())
    mapped_petitions = int(len(union))
    qualifying_share = qualifying_petitions / mapped_petitions if mapped_petitions else 0.0

    exact_week_pass = qualifying_petitions >= 5_000 and qualifying_share >= 0.30
    exact_cells.to_csv(audit / "union_state_exact_week_cell_audit.csv", index=False, lineterminator="\n")
    union_gate = pd.DataFrame([
        {"metric": "verified_parent_union_petitions", "value": mapped_petitions, "threshold": "descriptive", "pass": True},
        {"metric": "qualifying_parent_state_week_cells", "value": len(qualifying), "threshold": "descriptive", "pass": True},
        {"metric": "qualifying_parent_state_week_petitions", "value": qualifying_petitions, "threshold": ">=5,000", "pass": qualifying_petitions >= 5_000},
        {"metric": "qualifying_share_mapped_pct", "value": 100 * qualifying_share, "threshold": ">=30%", "pass": qualifying_share >= 0.30},
        {"metric": "parent_union_exact_week_gate", "value": "PASS" if exact_week_pass else "HOLD", "threshold": "both numeric rules", "pass": exact_week_pass},
    ])
    union_gate.to_csv(audit / "union_exact_week_data_gate.csv", index=False, lineterminator="\n")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(extension),
        "primary_esample_rows": int(extension.primary_esample.sum()),
        "future_block_validation_rows": int(overlap.sum()),
        "exact_week_union_gate": "PASS" if exact_week_pass else "HOLD",
        "inputs": {
            str(path.relative_to(root)).replace("\\", "/"): sha256(path)
            for path in [panel_path, support_path, exposure_path, union_path]
        },
        "outputs": {
            str(parquet_path.relative_to(root)).replace("\\", "/"): sha256(parquet_path),
            str(dta_path.relative_to(root)).replace("\\", "/"): sha256(dta_path),
        },
    }
    (output / "jeem_extension_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"manifest": manifest, "union_gate": union_gate.to_dict("records")}, indent=2))

if __name__ == "__main__":
    main()
