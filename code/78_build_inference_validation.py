from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

COUNTY_SEED = 20260828
STATE_SEED = 20260829
WILD_SEED = 20260830
VALIDATION_REPETITIONS = 100
WILD_REPETITIONS = 9_999

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def make_mapping(rng: np.random.Generator, units: int, year_lengths: np.ndarray) -> np.ndarray:
    mapping = np.tile(np.arange(len(year_lengths), dtype=np.int16), (units, 1))
    for length in np.unique(year_lengths):
        target = np.flatnonzero(year_lengths == length)
        draws = np.argsort(rng.random((units, len(target))), axis=1)
        mapping[:, target] = target[draws]
    return mapping

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    pivot = root / "data" / "clean" / "final_pivot"
    gate2 = root / "data" / "clean" / "gate2"
    gate25 = root / "data" / "clean" / "gate25"
    audit = root / "data" / "clean" / "results"
    score_path = gate25 / "gate25_ri_null_score_sample.dta"
    weather_path = gate2 / "county_week_analysis_v1.parquet"
    formal_path = gate25 / "gate25_randomization_score_results.parquet"
    scores = pd.read_stata(score_path, convert_dates=True)
    scores.week_start = pd.to_datetime(scores.week_start)
    weather = pd.read_parquet(
        weather_path,
        columns=["county_id", "state_id", "calendar_year", "week_start", "p95_days_lag1_4"],
    )
    weather.week_start = pd.to_datetime(weather.week_start)
    counties = np.sort(scores.county_id.unique())
    weather = weather.loc[weather.county_id.isin(counties)].sort_values(
        ["county_id", "calendar_year", "week_start"]
    ).copy()
    weather["week_slot"] = weather.groupby(["county_id", "calendar_year"]).cumcount()
    years = np.sort(weather.calendar_year.unique()).astype(np.int16)
    year_lengths = weather.groupby("calendar_year").week_slot.max().reindex(years).to_numpy(np.int16) + 1
    county_lookup = {county: i for i, county in enumerate(counties)}
    year_lookup = {year: i for i, year in enumerate(years)}
    c_w = weather.county_id.map(county_lookup).to_numpy(np.int32)
    y_w = weather.calendar_year.map(year_lookup).to_numpy(np.int8)
    slot_w = weather.week_slot.to_numpy(np.int8)
    cube = np.full((len(counties), len(years), int(year_lengths.max())), np.nan, dtype=np.float32)
    cube[c_w, y_w, slot_w] = weather.p95_days_lag1_4.to_numpy(np.float32)

    key = weather[["county_id", "calendar_year", "week_start", "week_slot"]]
    scores = scores.merge(key, on=["county_id", "calendar_year", "week_start"], validate="one_to_one")
    c_idx = scores.county_id.map(county_lookup).to_numpy(np.int32)
    y_idx = scores.calendar_year.map(year_lookup).to_numpy(np.int8)
    slots = scores.week_slot.to_numpy(np.int8)
    residual = scores.ri_residual.to_numpy(np.float64)
    observed_h = scores.p95_days_lag1_4.to_numpy(np.float64)
    observed_score = float(observed_h @ residual)

    county_state = scores.drop_duplicates("county_id").set_index("county_id").state_id
    states = np.sort(county_state.unique())
    state_lookup = {state: i for i, state in enumerate(states)}
    county_state_idx = np.array([state_lookup[county_state.loc[c]] for c in counties], dtype=np.int16)

    output = scores[["county_id", "week_start"]].copy()
    score_rows: list[dict[str, float | int | str]] = []
    for design, seed, prefix in [
        ("county_year", COUNTY_SEED, "cy"),
        ("state_year_block", STATE_SEED, "sy"),
    ]:
        rng = np.random.default_rng(seed)
        for repetition in range(1, VALIDATION_REPETITIONS + 1):
            if design == "county_year":
                mapping = make_mapping(rng, len(counties), year_lengths)
            else:
                state_mapping = make_mapping(rng, len(states), year_lengths)
                mapping = state_mapping[county_state_idx]
            source_year = mapping[c_idx, y_idx]
            h = cube[c_idx, source_year, slots].astype(np.float64)
            if np.isnan(h).any():
                raise ValueError("Validation permutation generated missing heat")
            output[f"{prefix}{repetition:03d}"] = h.astype(np.float32)
            score_rows.append({
                "design": design,
                "repetition": repetition,
                "score": float(h @ residual),
                "observed_score": observed_score,
            })
    validation_scores = pd.DataFrame(score_rows)

    formal = pd.read_parquet(formal_path)
    check = validation_scores.merge(
        formal[["design", "repetition", "score"]].rename(columns={"score": "formal_score"}),
        on=["design", "repetition"], validate="one_to_one",
    )
    if not np.allclose(check.score, check.formal_score, rtol=0, atol=1e-6):
        raise ValueError("Validation score sequence does not reproduce the first 100 formal RI draws")

    validation_path = pivot / "ri_validation_permutations_v1.dta"
    output.to_stata(validation_path, write_index=False, version=118, convert_dates={"week_start": "td"})
    validation_scores.to_csv(audit / "ri_validation_scores.csv", index=False, lineterminator="\n")

    score_frame = pd.DataFrame({
        "state_id": scores.state_id.to_numpy(),
        "contribution": observed_h * residual,
    })
    cluster_scores = score_frame.groupby("state_id").contribution.sum().reindex(states).to_numpy(np.float64)
    if not np.isclose(cluster_scores.sum(), observed_score, rtol=0, atol=1e-6):
        raise ValueError("Cluster score contributions do not reproduce observed score")
    rng = np.random.default_rng(WILD_SEED)
    draws = rng.choice(np.array([-1.0, 1.0]), size=(WILD_REPETITIONS, len(states)))
    bootstrap_scores = draws @ cluster_scores
    extreme = int(np.sum(np.abs(bootstrap_scores) >= abs(observed_score)))
    wild_p = (extreme + 1) / (WILD_REPETITIONS + 1)
    pd.DataFrame({
        "repetition": np.arange(1, WILD_REPETITIONS + 1),
        "wild_score": bootstrap_scores,
        "observed_score": observed_score,
        "as_or_more_extreme_two_sided": np.abs(bootstrap_scores) >= abs(observed_score),
    }).to_csv(audit / "state_cluster_wild_score_draws.csv", index=False, lineterminator="\n")
    wild_summary = pd.DataFrame([{
        "method": "state-cluster Rademacher wild-score bootstrap",
        "clusters": len(states),
        "repetitions": WILD_REPETITIONS,
        "seed": WILD_SEED,
        "observed_score": observed_score,
        "extreme_two_sided": extreme,
        "two_sided_p": wild_p,
    }])
    wild_summary.to_csv(audit / "state_cluster_wild_score_summary.csv", index=False, lineterminator="\n")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "validation_repetitions_each": VALIDATION_REPETITIONS,
        "county_seed": COUNTY_SEED,
        "state_seed": STATE_SEED,
        "wild_seed": WILD_SEED,
        "wild_repetitions": WILD_REPETITIONS,
        "score_sample_sha256": sha256(score_path),
        "validation_permutations_sha256": sha256(validation_path),
        "wild_two_sided_p": wild_p,
    }
    (pivot / "inference_validation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"manifest": manifest, "wild": wild_summary.to_dict("records")}, indent=2))

if __name__ == "__main__":
    main()
