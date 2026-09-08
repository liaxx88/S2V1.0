from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260831
DEFAULT_REPETITIONS = 999
TREND_STRATA = ((2011, 2014), (2015, 2018), (2019, 2022), (2023, 2024))

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def trend_group(year: int) -> int:
    for group, (first, last) in enumerate(TREND_STRATA):
        if first <= year <= last:
            return group
    raise ValueError(f"Year {year} is outside the prespecified strata")

def make_state_mapping(
    rng: np.random.Generator,
    state_count: int,
    years: np.ndarray,
    year_lengths: np.ndarray,
) -> np.ndarray:
    mapping = np.tile(np.arange(len(years), dtype=np.int16), (state_count, 1))
    trend_groups = np.array([trend_group(int(year)) for year in years], dtype=np.int8)
    for group in np.unique(trend_groups):
        for length in np.unique(year_lengths[trend_groups == group]):
            targets = np.flatnonzero((trend_groups == group) & (year_lengths == length))
            if len(targets) <= 1:
                continue
            order = np.argsort(rng.random((state_count, len(targets))), axis=1)
            mapping[:, targets] = targets[order]
    return mapping

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    args = parser.parse_args()

    root = args.root.resolve()
    gate2 = root / "data" / "clean" / "gate2"
    gate25 = root / "data" / "clean" / "gate25"
    extension = root / "data" / "clean" / "jeem_extension"
    audit = root / "data" / "clean" / "results"
    score_path = gate25 / "gate25_ri_null_score_sample.dta"
    weather_path = gate2 / "county_week_analysis_v1.parquet"

    scores = pd.read_stata(score_path, convert_dates=True)
    scores["week_start"] = pd.to_datetime(scores["week_start"])
    weather = pd.read_parquet(
        weather_path,
        columns=["county_id", "state_id", "calendar_year", "week_start", "p95_days_lag1_4"],
    )
    weather["week_start"] = pd.to_datetime(weather["week_start"])

    core_counties = np.sort(scores["county_id"].unique())
    weather = weather.loc[weather["county_id"].isin(core_counties)].copy()
    weather = weather.sort_values(["county_id", "calendar_year", "week_start"])
    weather["week_slot"] = weather.groupby(["county_id", "calendar_year"]).cumcount()
    years = np.sort(weather["calendar_year"].unique()).astype(np.int16)
    if not np.array_equal(years, np.arange(2011, 2025)):
        raise ValueError(f"Unexpected analysis years: {years}")
    year_lengths = (
        weather.groupby("calendar_year")["week_slot"].max().reindex(years).to_numpy(np.int16) + 1
    )

    county_lookup = {county: index for index, county in enumerate(core_counties)}
    year_lookup = {year: index for index, year in enumerate(years)}
    county_idx_w = weather["county_id"].map(county_lookup).to_numpy(np.int32)
    year_idx_w = weather["calendar_year"].map(year_lookup).to_numpy(np.int8)
    week_slot_w = weather["week_slot"].to_numpy(np.int8)
    cube = np.full(
        (len(core_counties), len(years), int(year_lengths.max())), np.nan, dtype=np.float32
    )
    cube[county_idx_w, year_idx_w, week_slot_w] = weather["p95_days_lag1_4"].to_numpy(np.float32)

    key = weather[["county_id", "calendar_year", "week_start", "week_slot"]]
    scores = scores.merge(
        key, on=["county_id", "calendar_year", "week_start"], how="left", validate="one_to_one"
    )
    if scores["week_slot"].isna().any():
        raise ValueError("Null-score rows did not match the frozen weather cube")

    county_idx = scores["county_id"].map(county_lookup).to_numpy(np.int32)
    target_year = scores["calendar_year"].map(year_lookup).to_numpy(np.int8)
    week_slot = scores["week_slot"].to_numpy(np.int8)
    residual = scores["ri_residual"].to_numpy(np.float64)
    observed_heat = scores["p95_days_lag1_4"].to_numpy(np.float64)
    observed_score = float(observed_heat @ residual)

    county_state = scores.drop_duplicates("county_id").set_index("county_id")["state_id"]
    states = np.sort(county_state.unique())
    state_lookup = {state: index for index, state in enumerate(states)}
    county_state_idx = np.array(
        [state_lookup[county_state.loc[county]] for county in core_counties], dtype=np.int16
    )

    rng = np.random.default_rng(SEED)
    rows: list[dict[str, float | int | str]] = []
    for repetition in range(1, args.repetitions + 1):
        state_mapping = make_state_mapping(rng, len(states), years, year_lengths)
        mapping = state_mapping[county_state_idx]
        source_year = mapping[county_idx, target_year]
        permuted_heat = cube[county_idx, source_year, week_slot].astype(np.float64)
        if np.isnan(permuted_heat).any():
            raise ValueError("A trend/length-stratified mapping generated missing heat")
        rows.append(
            {
                "design": "trend_preserving_state_year_block",
                "repetition": repetition,
                "score": float(permuted_heat @ residual),
                "observed_score": observed_score,
            }
        )
        if repetition % 100 == 0 or repetition == args.repetitions:
            print(f"trend-preserving state-year blocks: {repetition}/{args.repetitions}", flush=True)

    results = pd.DataFrame(rows)
    results["as_or_more_extreme_two_sided"] = (
        results["score"].abs() >= abs(observed_score)
    ).astype(np.int8)
    results["as_or_more_extreme_right_tail"] = (results["score"] >= observed_score).astype(np.int8)
    extreme_two = int(results["as_or_more_extreme_two_sided"].sum())
    extreme_right = int(results["as_or_more_extreme_right_tail"].sum())
    summary = pd.DataFrame(
        [
            {
                "design": "trend_preserving_state_year_block",
                "repetitions": args.repetitions,
                "observed_score": observed_score,
                "permutation_score_mean": float(results["score"].mean()),
                "permutation_score_sd": float(results["score"].std(ddof=1)),
                "two_sided_extreme": extreme_two,
                "two_sided_tail_probability": (extreme_two + 1) / (args.repetitions + 1),
                "right_tail_extreme": extreme_right,
                "right_tail_probability": (extreme_right + 1) / (args.repetitions + 1),
            }
        ]
    )

    result_path = extension / "jeem_trend_preserving_permutation.parquet"
    summary_path = audit / "jeem_trend_preserving_permutation_summary.csv"
    results.to_parquet(result_path, index=False)
    results.to_csv(audit / "jeem_trend_preserving_permutation_draws.csv", index=False, lineterminator="\n")
    summary.to_csv(summary_path, index=False, lineterminator="\n")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "label": "dependence- and trend-preserving permutation diagnostic",
        "experimental_randomization_inference": False,
        "statistic": "primary PPML null score",
        "repetitions": args.repetitions,
        "seed": SEED,
        "trend_strata": [list(item) for item in TREND_STRATA],
        "week_length_compatibility": True,
        "score_sample_sha256": sha256(score_path),
        "weather_source_sha256": sha256(weather_path),
        "results_sha256": sha256(result_path),
        "summary_sha256": sha256(summary_path),
    }
    (extension / "jeem_trend_preserving_permutation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
