from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE_START, BASE_END = 1981, 2010
WEEKLY_START = pd.Timestamp("2010-08-30")  
WEEKLY_END = pd.Timestamp("2024-12-31")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def climate_doy(month: np.ndarray, day: np.ndarray) -> np.ndarray:

    dates = pd.to_datetime({"year": np.full(len(month), 2000), "month": month, "day": day})
    return dates.dt.dayofyear.to_numpy(dtype=np.int16)

def quantiles_from_climatology(values: np.ndarray, quantiles: tuple[float, ...],
                               batch_size: int = 32) -> tuple[np.ndarray, np.ndarray]:
    n_counties = values.shape[0]
    output = np.full((len(quantiles), n_counties, 366), np.nan, dtype=np.float32)
    counts = np.zeros((n_counties, 366), dtype=np.int16)
    for start in range(0, n_counties, batch_size):
        block = values[start:start + batch_size]
        extended = np.concatenate([block[:, :, -15:], block, block[:, :, :15]], axis=2)
        windows = np.lib.stride_tricks.sliding_window_view(extended, 31, axis=2)
        counts[start:start + len(block)] = np.isfinite(windows).sum(axis=(1, 3)).astype(np.int16)
        q = np.nanquantile(windows, quantiles, axis=(1, 3), method="linear")
        output[:, start:start + len(block)] = q.astype(np.float32)
        print(f"Thresholds: counties {start + 1}-{start + len(block)} of {n_counties}", flush=True)
    return output, counts

def lag_sum(series: pd.Series, start_lag: int, end_lag: int) -> pd.Series:
    width = end_lag - start_lag + 1
    return series.shift(start_lag).rolling(width, min_periods=width).sum()

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

    clean = root / "data" / "clean" / "noaa"
    audit_dir = root / "data" / "clean" / "results"
    daily_path = clean / "noaa_county_daily_1981_2024.parquet"
    threshold_path = clean / "noaa_heat_thresholds_1981_2010.parquet"
    weekly_path = clean / "noaa_county_week_heat_2010_2024.parquet"
    audit_path = audit_dir / "heat_measure_audit.csv"
    manifest_path = clean / "noaa_heat_exposure_manifest.json"
    parquet = pq.ParquetFile(daily_path)

    capacity = 4_000
    tmax_base = np.full((capacity, 30, 366), np.nan, dtype=np.float32)
    tmin_base = np.full((capacity, 30, 366), np.nan, dtype=np.float32)
    county_to_index: dict[str, int] = {}
    counties: list[str] = []

    for group in range(parquet.metadata.num_row_groups):
        table = parquet.read_row_group(group, columns=[
            "county_fips", "year", "month", "day", "tmax_c", "tmin_c"
        ])
        frame = table.to_pandas()
        year = int(frame["year"].iloc[0])
        if year > BASE_END:
            continue
        for county in frame["county_fips"].unique():
            if county not in county_to_index:
                if len(counties) >= capacity:
                    raise RuntimeError("County array capacity exceeded")
                county_to_index[county] = len(counties)
                counties.append(county)
        county_index = frame["county_fips"].map(county_to_index).to_numpy(dtype=np.int32)
        year_index = frame["year"].to_numpy(dtype=np.int16) - BASE_START
        day_index = climate_doy(frame["month"].to_numpy(), frame["day"].to_numpy()) - 1
        existing = tmax_base[county_index, year_index, day_index]
        if np.isfinite(existing).any():
            raise ValueError("Duplicate county/climate-day/year in NOAA baseline")
        tmax_base[county_index, year_index, day_index] = frame["tmax_c"].to_numpy(dtype=np.float32)
        tmin_base[county_index, year_index, day_index] = frame["tmin_c"].to_numpy(dtype=np.float32)

    n_counties = len(counties)
    tmax_base = tmax_base[:n_counties]
    tmin_base = tmin_base[:n_counties]
    tmax_q, window_n = quantiles_from_climatology(tmax_base, (0.90, 0.95, 0.99))
    tmin_q, window_n_tmin = quantiles_from_climatology(tmin_base, (0.95,))
    county_order = np.array(counties, dtype=object)
    template = pd.date_range("2000-01-01", "2000-12-31", freq="D")
    threshold = pd.DataFrame({
        "county_fips": np.repeat(county_order, 366),
        "climate_doy": np.tile(np.arange(1, 367, dtype=np.int16), n_counties),
        "month": np.tile(template.month.to_numpy(dtype=np.int8), n_counties),
        "day": np.tile(template.day.to_numpy(dtype=np.int8), n_counties),
        "p90_tmax_c": tmax_q[0].reshape(-1),
        "p95_tmax_c": tmax_q[1].reshape(-1),
        "p99_tmax_c": tmax_q[2].reshape(-1),
        "p95_tmin_c": tmin_q[0].reshape(-1),
        "tmax_window_n": window_n.reshape(-1),
        "tmin_window_n": window_n_tmin.reshape(-1),
    })
    threshold["p90_tmax_f"] = threshold["p90_tmax_c"] * 9 / 5 + 32
    threshold["p95_tmax_f"] = threshold["p95_tmax_c"] * 9 / 5 + 32
    threshold["p99_tmax_f"] = threshold["p99_tmax_c"] * 9 / 5 + 32
    threshold["p95_tmin_f"] = threshold["p95_tmin_c"] * 9 / 5 + 32
    threshold_table = pa.Table.from_pandas(threshold, preserve_index=False)
    threshold_meta = dict(threshold_table.schema.metadata or {})
    threshold_meta.update({
        b"climatology": b"1981-2010, entirely predating the outcome sample",
        b"window": b"calendar day +/-15 days, circular over a 366-day leap template",
        b"comparison": b"strictly greater than threshold",
    })
    pq.write_table(threshold_table.replace_schema_metadata(threshold_meta), threshold_path,
                   compression="zstd", use_dictionary=["county_fips"])

    analysis_dates = pd.date_range(WEEKLY_START, WEEKLY_END, freq="D")
    day_position = {date.date(): index for index, date in enumerate(analysis_dates)}
    heat_matrix = np.zeros((n_counties, len(analysis_dates)), dtype=bool)
    observed_matrix = np.zeros((n_counties, len(analysis_dates)), dtype=bool)
    partials = []
    for group in range(parquet.metadata.num_row_groups):
        table = parquet.read_row_group(group, columns=[
            "county_fips", "date", "year", "month", "day", "tmax_c", "tmax_f", "tmin_c", "prcp_mm"
        ])
        frame = table.to_pandas()
        dates = pd.to_datetime(frame["date"])
        if dates.max() < WEEKLY_START or dates.min() > WEEKLY_END:
            continue
        keep = dates.between(WEEKLY_START, WEEKLY_END)
        frame = frame.loc[keep].copy()
        dates = dates.loc[keep]
        index = frame["county_fips"].map(county_to_index)
        if index.isna().any():
            missing_counties = sorted(frame.loc[index.isna(), "county_fips"].unique())
            raise ValueError(f"Post-2010 NOAA counties absent from 1981-2010 baseline: {missing_counties}")
        ci = index.to_numpy(dtype=np.int32)
        clim = climate_doy(frame["month"].to_numpy(), frame["day"].to_numpy()) - 1
        tmax = frame["tmax_c"].to_numpy(dtype=np.float32)
        tmin = frame["tmin_c"].to_numpy(dtype=np.float32)
        p90 = tmax > tmax_q[0, ci, clim]
        p95 = tmax > tmax_q[1, ci, clim]
        p99 = tmax > tmax_q[2, ci, clim]
        night = tmin > tmin_q[0, ci, clim]
        frame["p90_day"] = p90.astype(np.int8)
        frame["p95_day"] = p95.astype(np.int8)
        frame["p99_day"] = p99.astype(np.int8)
        frame["day_90f"] = (frame["tmax_f"].to_numpy() >= 90).astype(np.int8)
        frame["day_95f"] = (frame["tmax_f"].to_numpy() >= 95).astype(np.int8)
        frame["day_100f"] = (frame["tmax_f"].to_numpy() >= 100).astype(np.int8)
        frame["excess_heat_c"] = np.maximum(0, tmax - tmax_q[1, ci, clim]).astype(np.float32)
        frame["night_heat_day"] = night.astype(np.int8)
        frame["week_start"] = dates - pd.to_timedelta(dates.dt.weekday, unit="D")
        day_idx = np.array([day_position[value] for value in dates.dt.date], dtype=np.int32)
        heat_matrix[ci, day_idx] = p95
        observed_matrix[ci, day_idx] = True
        monthly_week = frame.groupby(["county_fips", "week_start"], as_index=False).agg(
            p90_days=("p90_day", "sum"), p95_days=("p95_day", "sum"),
            p99_days=("p99_day", "sum"), days90f=("day_90f", "sum"),
            days95f=("day_95f", "sum"), days100f=("day_100f", "sum"),
            excess_heat_c=("excess_heat_c", "sum"), night_heat_days=("night_heat_day", "sum"),
            precipitation_mm=("prcp_mm", "sum"), observed_days=("date", "size"),
        )
        partials.append(monthly_week)

    prev1 = np.zeros_like(heat_matrix); prev1[:, 1:] = heat_matrix[:, :-1]
    prev2 = np.zeros_like(heat_matrix); prev2[:, 2:] = heat_matrix[:, :-2]
    next1 = np.zeros_like(heat_matrix); next1[:, :-1] = heat_matrix[:, 1:]
    next2 = np.zeros_like(heat_matrix); next2[:, :-2] = heat_matrix[:, 2:]
    heatwave = heat_matrix & ((prev1 & prev2) | (prev1 & next1) | (next1 & next2))

    weekly = pd.concat(partials, ignore_index=True).groupby(
        ["county_fips", "week_start"], as_index=False
    ).sum(numeric_only=True)
    week_dates = pd.DatetimeIndex(analysis_dates - pd.to_timedelta(analysis_dates.weekday, unit="D"))
    unique_weeks = pd.DatetimeIndex(sorted(week_dates.unique()))
    week_code = pd.Categorical(week_dates, categories=unique_weeks, ordered=True).codes
    heatwave_rows = []
    for ci_value, county in enumerate(counties):
        sums = np.bincount(week_code, weights=heatwave[ci_value].astype(np.int8),
                           minlength=len(unique_weeks)).astype(np.int8)
        observed = np.bincount(week_code, weights=observed_matrix[ci_value].astype(np.int8),
                               minlength=len(unique_weeks)).astype(np.int8)
        heatwave_rows.append(pd.DataFrame({
            "county_fips": county, "week_start": unique_weeks,
            "heatwave_days": sums, "matrix_observed_days": observed,
        }))
    heatwave_week = pd.concat(heatwave_rows, ignore_index=True)
    weekly = weekly.merge(heatwave_week, on=["county_fips", "week_start"], how="outer",
                          validate="one_to_one")
    weekly = weekly.sort_values(["county_fips", "week_start"]).reset_index(drop=True)
    weekly["state_fips"] = weekly["county_fips"].str[:2]
    weekly["year"] = weekly["week_start"].dt.year.astype(np.int16)
    weekly["week"] = weekly["week_start"].dt.isocalendar().week.astype(np.int16)
    weekly["week_index"] = ((weekly["week_start"] - unique_weeks.min()).dt.days // 7).astype(np.int32)
    if weekly.duplicated(["county_fips", "week_start"]).any():
        raise ValueError("Weekly weather is not unique by county_fips x week_start")

    grouped = weekly.groupby("county_fips", sort=False, group_keys=False)
    for start, end in ((1, 4), (5, 8), (9, 12), (13, 16), (17, 20), (21, 24)):
        weekly[f"p95_days_lag{start}_{end}"] = grouped["p95_days"].transform(
            lambda series, a=start, b=end: lag_sum(series, a, b)
        ).astype(np.float32)
    for source, target in (
        ("p90_days", "p90_days_lag1_4"), ("p99_days", "p99_days_lag1_4"),
        ("days90f", "days90f_lag1_4"), ("days95f", "days95f_lag1_4"),
        ("days100f", "days100f_lag1_4"), ("excess_heat_c", "excess_heat_c_lag1_4"),
        ("heatwave_days", "heatwave_days_lag1_4"), ("night_heat_days", "night_heat_lag1_4"),
        ("precipitation_mm", "precipitation_lag1_4"),
    ):
        weekly[target] = grouped[source].transform(lambda series: lag_sum(series, 1, 4)).astype(np.float32)
    weekly["p95_days_future9_16"] = grouped["p95_days"].transform(
        lambda series: series.shift(-16).rolling(8, min_periods=8).sum()
    ).astype(np.float32)
    weekly["p95_days_next_year"] = grouped["p95_days"].shift(-52).astype(np.float32)
    weekly["p95_days_cumulative_1_16"] = weekly[[
        "p95_days_lag1_4", "p95_days_lag5_8", "p95_days_lag9_12", "p95_days_lag13_16"
    ]].sum(axis=1, min_count=4).astype(np.float32)
    weekly["p95_days_cumulative_1_24"] = weekly[[
        "p95_days_lag1_4", "p95_days_lag5_8", "p95_days_lag9_12", "p95_days_lag13_16",
        "p95_days_lag17_20", "p95_days_lag21_24"
    ]].sum(axis=1, min_count=6).astype(np.float32)
    weekly = weekly[[
        "county_fips", "state_fips", "week_start", "year", "week", "week_index",
        "p90_days", "p95_days", "p99_days", "days90f", "days95f", "days100f",
        "excess_heat_c", "heatwave_days", "night_heat_days", "precipitation_mm", "observed_days",
        "p95_days_lag1_4", "p95_days_lag5_8", "p95_days_lag9_12", "p95_days_lag13_16",
        "p95_days_lag17_20", "p95_days_lag21_24", "p90_days_lag1_4", "p99_days_lag1_4",
        "days90f_lag1_4", "days95f_lag1_4", "days100f_lag1_4", "excess_heat_c_lag1_4",
        "heatwave_days_lag1_4", "night_heat_lag1_4", "precipitation_lag1_4",
        "p95_days_future9_16", "p95_days_next_year", "p95_days_cumulative_1_16",
        "p95_days_cumulative_1_24",
    ]]
    weekly_table = pa.Table.from_pandas(weekly, preserve_index=False)
    weekly_meta = dict(weekly_table.schema.metadata or {})
    weekly_meta.update({
        b"week_definition": b"Monday-Sunday",
        b"week0_rule": b"week 0 excluded from all pre-filing exposure variables",
        b"primary": b"Tmax > county/calendar-day 1981-2010 P95, +/-15-day window",
        b"heatwave": b"daily P95 exceedance belonging to a spell of at least 3 consecutive days",
    })
    temp_weekly = weekly_path.with_suffix(".parquet.tmp")
    pq.write_table(weekly_table.replace_schema_metadata(weekly_meta), temp_weekly,
                   compression="zstd", use_dictionary=["county_fips", "state_fips"])
    os.replace(temp_weekly, weekly_path)

    audit = pd.DataFrame([
        {"metric": "threshold_counties", "value": n_counties},
        {"metric": "threshold_rows", "value": len(threshold)},
        {"metric": "minimum_tmax_window_observations", "value": int(window_n.min())},
        {"metric": "weekly_rows", "value": len(weekly)},
        {"metric": "weekly_unique_counties", "value": weekly["county_fips"].nunique()},
        {"metric": "weekly_start", "value": weekly["week_start"].min().date().isoformat()},
        {"metric": "weekly_end", "value": weekly["week_start"].max().date().isoformat()},
        {"metric": "p95_days_mean", "value": float(weekly["p95_days"].mean())},
        {"metric": "p95_days_zero_share", "value": float(weekly["p95_days"].eq(0).mean())},
    ])
    audit.to_csv(audit_path, index=False, encoding="utf-8", lineterminator="\n")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "daily_source_sha256": sha256(daily_path),
        "threshold_output_sha256": sha256(threshold_path),
        "weekly_output_sha256": sha256(weekly_path),
        "threshold_definition": "1981-2010 county/calendar-day +/-15-day P90/P95/P99; strict exceedance",
        "week_definition": "Monday-Sunday; pre-filing lags begin at w-1",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote thresholds ({len(threshold):,} rows) and weekly heat ({len(weekly):,} rows)")

if __name__ == "__main__":
    main()
