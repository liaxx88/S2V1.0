from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

COUNTY_SEED = 20260828
STATE_SEED = 20260829
DEFAULT_REPETITIONS = 999

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def make_mapping(rng: np.random.Generator, units: int, years: np.ndarray,
                 year_lengths: np.ndarray) -> np.ndarray:
    mapping = np.tile(np.arange(len(years), dtype=np.int16), (units, 1))
    for length in np.unique(year_lengths):
        target = np.flatnonzero(year_lengths == length)
        draws = np.argsort(rng.random((units, len(target))), axis=1)
        mapping[:, target] = target[draws]
    return mapping

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    args = parser.parse_args()
    root = args.root.resolve()
    gate2 = root / "data" / "clean" / "gate2"
    gate25 = root / "data" / "clean" / "gate25"
    audit = root / "data" / "clean" / "results"
    figures = root / "figures"
    score_path = gate25 / "gate25_ri_null_score_sample.dta"
    weather_path = gate2 / "county_week_analysis_v1.parquet"

    scores = pd.read_stata(score_path, convert_dates=True)
    weather = pd.read_parquet(
        weather_path,
        columns=["county_id", "state_id", "calendar_year", "week_start", "p95_days_lag1_4"],
    )
    weather["week_start"] = pd.to_datetime(weather["week_start"])
    scores["week_start"] = pd.to_datetime(scores["week_start"])
    core_counties = np.sort(scores["county_id"].unique())
    weather = weather.loc[weather["county_id"].isin(core_counties)].copy()
    weather = weather.sort_values(["county_id", "calendar_year", "week_start"])
    weather["week_slot"] = weather.groupby(["county_id", "calendar_year"]).cumcount()
    years = np.sort(weather["calendar_year"].unique()).astype(np.int16)
    if not np.array_equal(years, np.arange(2011, 2025)):
        raise ValueError(f"Unexpected years: {years}")
    year_lengths = (
        weather.groupby("calendar_year")["week_slot"].max().reindex(years).to_numpy(dtype=np.int16) + 1
    )

    county_lookup = {county: idx for idx, county in enumerate(core_counties)}
    county_idx_w = weather["county_id"].map(county_lookup).to_numpy(dtype=np.int32)
    year_lookup = {year: idx for idx, year in enumerate(years)}
    year_idx_w = weather["calendar_year"].map(year_lookup).to_numpy(dtype=np.int8)
    week_slot_w = weather["week_slot"].to_numpy(dtype=np.int8)
    max_slots = int(year_lengths.max())
    cube = np.full((len(core_counties), len(years), max_slots), np.nan, dtype=np.float32)
    cube[county_idx_w, year_idx_w, week_slot_w] = weather["p95_days_lag1_4"].to_numpy(np.float32)

    key = weather[["county_id", "calendar_year", "week_start", "week_slot"]]
    scores = scores.merge(key, on=["county_id", "calendar_year", "week_start"], how="left", validate="one_to_one")
    if scores["week_slot"].isna().any():
        raise ValueError("Null-score rows failed to match the frozen weather cube")
    county_idx = scores["county_id"].map(county_lookup).to_numpy(dtype=np.int32)
    target_year = scores["calendar_year"].map(year_lookup).to_numpy(dtype=np.int8)
    week_slot = scores["week_slot"].to_numpy(dtype=np.int8)
    residual = scores["ri_residual"].to_numpy(dtype=np.float64)
    observed_h = scores["p95_days_lag1_4"].to_numpy(dtype=np.float64)
    observed_score = float(np.dot(observed_h, residual))

    county_state = scores.drop_duplicates("county_id").set_index("county_id")["state_id"]
    state_values = np.sort(county_state.unique())
    state_lookup = {state: idx for idx, state in enumerate(state_values)}
    county_state_idx = np.array([state_lookup[county_state.loc[county]] for county in core_counties], dtype=np.int16)

    all_rows = []
    for design, seed in (("county_year", COUNTY_SEED), ("state_year_block", STATE_SEED)):
        rng = np.random.default_rng(seed)
        for repetition in range(1, args.repetitions + 1):
            if design == "county_year":
                mapping = make_mapping(rng, len(core_counties), years, year_lengths)
            else:
                state_mapping = make_mapping(rng, len(state_values), years, year_lengths)
                mapping = state_mapping[county_state_idx]
            source_year = mapping[county_idx, target_year]
            permuted_h = cube[county_idx, source_year, week_slot].astype(np.float64)
            if np.isnan(permuted_h).any():
                raise ValueError("Block-length-stratified permutation generated missing heat")
            score = float(np.dot(permuted_h, residual))
            all_rows.append({"design": design, "repetition": repetition, "score": score})
            if repetition % 100 == 0 or repetition == args.repetitions:
                print(f"{design}: {repetition}/{args.repetitions}", flush=True)

    results = pd.DataFrame(all_rows)
    results["observed_score"] = observed_score
    results["as_or_more_extreme_two_sided"] = results["score"].abs().ge(abs(observed_score)).astype(np.int8)
    results["as_or_more_extreme_right_tail"] = results["score"].ge(observed_score).astype(np.int8)
    result_path = gate25 / "gate25_randomization_score_results.parquet"
    results.to_parquet(result_path, index=False)
    results.to_csv(audit / "gate25_randomization_inference.csv", index=False, lineterminator="\n")

    summary_rows = []
    for design, part in results.groupby("design"):
        n = len(part)
        extreme_two = int(part["as_or_more_extreme_two_sided"].sum())
        extreme_right = int(part["as_or_more_extreme_right_tail"].sum())
        summary_rows.append({
            "design": design,
            "repetitions": n,
            "observed_score": observed_score,
            "permutation_score_mean": part["score"].mean(),
            "permutation_score_sd": part["score"].std(ddof=1),
            "two_sided_extreme": extreme_two,
            "two_sided_p": (extreme_two + 1) / (n + 1),
            "right_tail_extreme": extreme_right,
            "right_tail_p": (extreme_right + 1) / (n + 1),
        })
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(audit / "gate25_randomization_summary.csv", index=False, lineterminator="\n")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "method": "PPML null-score randomization inference; whole weather-year blocks stratified by 52/53-week length",
        "repetitions_each_design": args.repetitions,
        "county_seed": COUNTY_SEED,
        "state_seed": STATE_SEED,
        "score_sample_sha256": sha256(score_path),
        "weather_source_sha256": sha256(weather_path),
        "results_sha256": sha256(result_path),
    }
    (gate25 / "gate25_randomization_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
