from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

def tex_table(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def tex_scientific(value: float, digits: int = 2) -> str:

    if value == 0:
        return "0"
    exponent = math.floor(math.log10(abs(value)))
    mantissa = value / (10 ** exponent)
    return rf"{mantissa:.{digits}f}\times 10^{{{exponent}}}"

def _continued_beta_fraction(a: float, b: float, x: float) -> float:

    max_iterations = 300
    tolerance = 3e-14
    tiny = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    result = d
    for iteration in range(1, max_iterations + 1):
        even = 2 * iteration
        coefficient = iteration * (b - iteration) * x / (
            (qam + even) * (a + even)
        )
        d = 1.0 + coefficient * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + coefficient / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        result *= d * c
        coefficient = -(a + iteration) * (qab + iteration) * x / (
            (a + even) * (qap + even)
        )
        d = 1.0 + coefficient * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + coefficient / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        update = d * c
        result *= update
        if abs(update - 1.0) < tolerance:
            return result
    raise RuntimeError("Incomplete-beta continued fraction did not converge")

def _regularized_beta(x: float, a: float, b: float) -> float:
    if not 0.0 <= x <= 1.0:
        raise ValueError("Regularized-beta argument must lie in [0, 1]")
    if x in (0.0, 1.0):
        return x
    scale = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return scale * _continued_beta_fraction(a, b, x) / a
    return 1.0 - scale * _continued_beta_fraction(b, a, 1.0 - x) / b

def student_t_two_sided_p(coefficient: float, standard_error: float, df: int = 47) -> float:

    if not math.isfinite(coefficient) or not math.isfinite(standard_error):
        return math.nan
    if standard_error <= 0:
        raise ValueError("Standard error must be positive")
    statistic = abs(coefficient / standard_error)
    beta_argument = df / (df + statistic * statistic)
    return _regularized_beta(beta_argument, df / 2.0, 0.5)

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    audit = root / "data" / "clean" / "results"
    tables = root / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    main_results = pd.read_csv(audit / "jeem_extension_main_results.csv")
    timing = pd.read_csv(audit / "jeem_extension_timing_results.csv")
    dose = pd.read_csv(audit / "jeem_extension_dose_results.csv")
    support = pd.read_csv(audit / "jeem_extension_support_results.csv")
    magnitude = pd.read_csv(audit / "jeem_extension_reallocation_summary.csv")
    trend_perm = pd.read_csv(audit / "jeem_trend_preserving_permutation_summary.csv").iloc[0]
    original_perm = pd.read_csv(audit / "gate25_randomization_summary.csv")
    wild = pd.read_csv(audit / "state_cluster_wild_score_summary.csv").iloc[0]
    identification = pd.read_csv(audit / "jeem_identification_results.csv")
    gate25_models = pd.read_csv(audit / "gate25_model_results.csv")
    gate2_models = pd.read_csv(audit / "gate2_model_results.csv")
    leave_one_state = pd.read_csv(audit / "gate2_leave_one_state_out.csv")
    merge_audit = pd.read_csv(audit / "gate2_merge_audit.csv")

    panel_columns = [
        "analysis_sample", "rc_petition_count", "any_rc_petition",
        "private_emp_lag12", "p95_days_lag1_4", "days95f_lag1_4",
        "heatwave_days_lag1_4", "precipitation_lag1_4",
    ]
    county_week = pd.read_parquet(
        root / "data" / "clean" / "gate2" / "county_week_analysis_v1.parquet",
        columns=panel_columns,
    )
    county_week = county_week.loc[county_week.analysis_sample.eq(1)].copy()
    if len(county_week) != 2_260_083:
        raise ValueError(f"Unexpected complete analysis panel size: {len(county_week):,}")

    season = main_results.loc[main_results.specification.eq("county_by_week_of_year")].iloc[0]
    primary = main_results.loc[main_results.specification.eq("state_cluster")].iloc[0]
    two_way = main_results.loc[main_results.specification.eq("state_week_two_way_cluster")].iloc[0]
    joint_future = timing.loc[timing.variable.eq("joint_future_wald")].iloc[0]
    metrics = dict(zip(magnitude.metric, magnitude.value))

    lines = [r"\begin{tabular}{lrr}", r"\toprule", r"Item & N & Rate (\%) \\", r"\midrule"]
    for row in merge_audit.itertuples(index=False):
        lines.append(f"{row.item} & {int(row.n):,} & {row.rate_pct:.2f} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    tex_table(tables / "TableJEEM1A_merge.tex", lines)

    summary_variables = [
        ("rc_petition_count", "RC petitions/week"),
        ("any_rc_petition", "Any RC petition"),
        ("private_emp_lag12", "Private employment (lag 12m)"),
        ("p95_days_lag1_4", "P95 heat days, weeks 1--4"),
        ("days95f_lag1_4", r"Days at or above $95^\circ$F, weeks 1--4"),
        ("heatwave_days_lag1_4", "Heatwave days, weeks 1--4"),
        ("precipitation_lag1_4", "Precipitation (mm), weeks 1--4"),
    ]
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule", r"Variable & N & Mean & SD & Min & Max \\", r"\midrule"]
    for variable, label in summary_variables:
        values = county_week[variable]
        lines.append(
            f"{label} & {int(values.count()):,} & {values.mean():,.3f} & "
            f"{values.std(ddof=1):,.3f} & {values.min():,.3f} & {values.max():,.3f} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    tex_table(tables / "TableJEEM1B_summary.tex", lines)

    state_model = gate25_models.loc[gate25_models.specification.eq("aggregate_incidence")].iloc[0]
    aggregate_lpm = gate25_models.loc[gate25_models.specification.eq("any_petition_lpm")].iloc[0]
    aggregate_ols = gate25_models.loc[gate25_models.specification.eq("petition_count_ols")].iloc[0]
    primary_model = gate25_models.loc[gate25_models.specification.eq("primary")].iloc[0]
    lines = [
        r"\begin{tabular}{@{}l*{4}{>{\centering\arraybackslash}p{0.90in}}@{}}", r"\toprule",
        r" & State-week PPML & Any-petition LPM & Count OLS & Conditional PPML \\",
        r"\midrule",
        f"P95 heat measure, weeks 1--4 & {state_model.b:.5f} & ${tex_scientific(aggregate_lpm.b)}$ & ${tex_scientific(aggregate_ols.b)}$ & {primary_model.b:.5f} \\\\",
        f"State-cluster standard error & ({state_model.se:.5f}) & ($ {tex_scientific(aggregate_lpm.se)} $) & ($ {tex_scientific(aggregate_ols.se)} $) & ({primary_model.se:.5f}) \\\\",
        r"County $\times$ month-of-year FE & No & No & No & Yes \\",
        r"State $\times$ exact-week FE & No & No & No & Yes \\",
        r"State $\times$ month-of-year FE & Yes & Yes & Yes & No \\",
        r"National exact-week FE & Yes & Yes & Yes & No \\",
        r"County FE & No & Yes & Yes & No \\",
        r"Lag-12-month employment offset & Yes & No & No & Yes \\",
        f"Observations & {int(state_model.N):,} & {int(aggregate_lpm.N):,} & {int(aggregate_ols.N):,} & {int(primary_model.N):,} \\\\",
        r"\bottomrule", r"\end{tabular}",
    ]
    tex_table(tables / "TableJEEM2_margins.tex", lines)

    county_year = identification.loc[identification.specification.eq("jeem_countyyear")].iloc[0]
    precipitation = identification.loc[
        identification.specification.eq("jeem_precipitation")
        & identification.variable.eq("p95_days_lag1_4")
    ].iloc[0]
    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r" & Primary & County $\times$ WOY & County $\times$ year & + Precipitation \\",
        r"\midrule",
        f"P95 heat days, weeks 1--4 & {primary.b:.5f} & {season.b:.5f} & {county_year.b:.5f} & {precipitation.b:.5f} \\\\",
        f"State-cluster standard error & ({primary.se:.5f}) & ({season.se:.5f}) & ({county_year.se:.5f}) & ({precipitation.se:.5f}) \\\\",
        r"County $\times$ month-of-year FE & Yes & No & Yes & Yes \\",
        r"County $\times$ week-of-year FE & No & Yes & No & No \\",
        r"County $\times$ year FE & No & No & Yes & No \\",
        r"State $\times$ exact-week FE & Yes & Yes & Yes & Yes \\",
        f"Observations & {int(primary.N):,} & {int(season.N):,} & {int(county_year.N):,} & {int(precipitation.N):,} \\\\",
        f"Petition events & {int(primary.petition_events):,} & {int(season.petition_events):,} & {int(county_year.petition_events):,} & {int(precipitation.petition_events):,} \\\\",
        f"Counties & {int(primary.counties):,} & {int(season.counties):,} & {int(county_year.counties):,} & {int(precipitation.counties):,} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    tex_table(tables / "TableJEEM3_identification.tex", lines)

    unrestricted = original_perm.loc[original_perm.design.eq("state_year_block")].iloc[0]
    lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Inference procedure & Coefficient & Standard error & Two-sided $p$ / tail probability \\",
        r"\midrule",
        f"State-cluster conventional, $t_{{47}}$ reference & {primary.b:.5f} & {primary.se:.5f} & 0.090 \\\\",
        f"State-cluster wild-score bootstrap (9,999) & {primary.b:.5f} & -- & {wild.two_sided_p:.3f} \\\\",
        f"Two-way clustered: state and exact calendar week & {two_way.b:.5f} & {two_way.se:.5f} & {two_way.p:.3f} \\\\",
        f"State-year-block permutation diagnostic (999) & -- & -- & {unrestricted.two_sided_p:.3f} \\\\",
        f"Secondary nearby-year-stratified sensitivity (999) & -- & -- & {trend_perm.two_sided_tail_probability:.3f} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    tex_table(tables / "TableJEEM4_inference.tex", lines)

    lines = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Fitted allocation quantity & Value \\",
        r"\midrule",
        f"Mean petition-equivalents per state-week & {metrics['mean_state_week_reallocation']:.4f} \\\\",
        f"Petition-equivalents per 100 observed petitions & {metrics['petition_equivalents_per_100_petitions']:.3f} \\\\",
        f"Top heat-dispersion decile: mean per state-week & {metrics['mean_top_decile_state_week_reallocation']:.4f} \\\\",
        f"Top heat-dispersion decile: per 100 petitions & {metrics['top_decile_petition_equivalents_per_100']:.3f} \\\\",
        f"Mean annual petition-equivalents, estimable support & {metrics['mean_annual_reallocation']:.2f} \\\\",
        f"Total petition-equivalents, 2011--2024, estimable support & {metrics['total_reallocation_2011_2024']:.2f} \\\\",
        f"Maximum fitted estimable-support state-week total discrepancy & {metrics['maximum_state_week_fitted_total_gap']:.6f} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    tex_table(tables / "TableJEEM5_magnitude.tex", lines)

    timing_labels = {
        "p95_days_lag13_16": "Pre-filing weeks 13--16",
        "p95_days_lag9_12": "Pre-filing weeks 9--12",
        "p95_days_lag5_8": "Pre-filing weeks 5--8",
        "p95_days_lag1_4": "Pre-filing weeks 1--4",
        "p95_days_future1_4": "Post-filing weeks 1--4",
        "p95_days_future5_8": "Post-filing weeks 5--8",
        "p95_days_future9_12": "Post-filing weeks 9--12",
        "p95_days_future13_16": "Post-filing weeks 13--16",
    }
    lines = [r"\begin{tabular}{lrrr}", r"\toprule", r"Block & Coefficient & Standard error & $p$-value \\", r"\midrule"]
    for variable, label in timing_labels.items():
        row = timing.loc[timing.variable.eq(variable)].iloc[0]
        coefficient_p = student_t_two_sided_p(row.b, row.se)
        lines.append(
            f"{label} & {row.b:.5f} & {row.se:.5f} & {coefficient_p:.3f} \\\\")
    lines.extend(
        [
            r"\midrule",
            f"Joint future-block Wald test & {joint_future.b:.3f} & -- & {joint_future.p:.3f} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
        ]
    )
    tex_table(tables / "TableJEEMA1_timing.tex", lines)

    lines = [r"\begin{tabular}{lrrrr}", r"\toprule", r"Scope group & Coefficient & Standard error & Observations & Events \\", r"\midrule"]
    for row in support.itertuples(index=False):
        label = str(row.group_name).replace("_", r"\_")
        lines.append(f"{label} & {row.b:.5f} & {row.se:.5f} & {int(row.N):,} & {int(row.petition_events):,} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    tex_table(tables / "TableJEEMA2_support.tex", lines)

    lines = [r"\begin{tabular}{lrrr}", r"\toprule", r"Heat-day bin & Coefficient & Standard error & $p$-value \\", r"\midrule"]
    dose_labels = {"heat_1_2": "1--2", "heat_3_4": "3--4", "heat_5_7": "5--7", "heat_8plus": "8 or more"}
    for row in dose.itertuples(index=False):
        coefficient_p = student_t_two_sided_p(row.b, row.se)
        lines.append(
            f"{dose_labels[row.variable]} & {row.b:.5f} & {row.se:.5f} & "
            f"{coefficient_p:.3f} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    tex_table(tables / "TableJEEMA3_dose.tex", lines)

    robustness_specs = [
        ("alternative_heat", "p90_days_lag1_4", "Local P90 heat days"),
        ("alternative_heat", "p95_days_lag1_4", "Local P95 heat days (primary)"),
        ("alternative_heat", "p99_days_lag1_4", "Local P99 heat days"),
        ("alternative_heat", "days90f_lag1_4", r"Days at or above $90^\circ$F"),
        ("alternative_heat", "days95f_lag1_4", r"Days at or above $95^\circ$F"),
        ("alternative_heat", "days100f_lag1_4", r"Days at or above $100^\circ$F"),
        ("alternative_heat", "excess_heat_c_lag1_4", "Degrees above local P95"),
        ("alternative_heat", "heatwave_days_lag1_4", "Heatwave days"),
        ("alternative_heat", "night_heat_lag1_4", "Night-heat days"),
        ("campaign_exclusion", "rc_count_excl_starbucks", "Exclude Starbucks"),
        ("campaign_exclusion", "rc_count_excl_starbucks_amazon", "Exclude Starbucks and Amazon"),
        ("campaign_exclusion", "rc_count_excl_top5", "Exclude five largest employers"),
        ("campaign_exclusion", "rc_count_excl_top10", "Exclude ten largest employers"),
        ("period_exclusion", "drop_2020_2021", "Exclude 2020--2021"),
        ("period_exclusion", "drop_2022_2024", "Exclude 2022--2024"),
    ]
    lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Sensitivity specification & Coefficient & Standard error & Observations \\",
        r"\midrule",
    ]
    for family, specification, label in robustness_specs:
        row = gate2_models.loc[
            gate2_models.family.eq(family)
            & gate2_models.specification.eq(specification)
        ].iloc[0]
        lines.append(
            f"{label} & {row.b:.5f} & {row.se:.5f} & {int(row.N):,} \\\\")
    loo_min = float(leave_one_state.b.min())
    loo_max = float(leave_one_state.b.max())
    loo_positive = int((leave_one_state.b > 0).sum())
    lines.extend(
        [
            r"\midrule",
            f"Leave-one-state-out range ({loo_positive}/48 positive) & "
            f"[{loo_min:.4f}, {loo_max:.4f}] & -- & -- \\\\",
            r"\bottomrule",
            r"\end{tabular}",
        ]
    )
    tex_table(tables / "TableJEEMA4_robustness.tex", lines)

if __name__ == "__main__":
    main()
