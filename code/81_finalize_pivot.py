from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

def fmt(value: float, digits: int = 5) -> str:
    return f"{value:.{digits}f}"

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

    dynamic = pd.read_csv(audit / "final_pivot_state_week_dynamic_results.csv")
    common = pd.read_csv(audit / "final_pivot_common_support_progression_results.csv")
    exposure = pd.read_csv(audit / "final_pivot_county_exposure_results.csv")
    union = pd.read_csv(audit / "union_allocation_model_results.csv").iloc[0]
    union_gate = pd.read_csv(audit / "union_allocation_data_gate.csv")
    ri = pd.read_csv(audit / "gate25_randomization_summary.csv")
    validation = pd.read_csv(audit / "ri_score_exact_validation_summary.csv")
    nearby_perm = pd.read_csv(
        audit / "jeem_trend_preserving_permutation_summary.csv"
    ).iloc[0]
    wild = pd.read_csv(audit / "state_cluster_wild_score_summary.csv").iloc[0]

    labels = {
        "h1_4": "Weeks 1--4",
        "h5_8": "Weeks 5--8",
        "h9_12": "Weeks 9--12",
        "h13_16": "Weeks 13--16",
        "h17_20": "Weeks 17--20",
        "h21_24": "Weeks 21--24",
        "coefficient_sum_1_24": "Coefficient sum, weeks 1--24",
    }
    lines = [r"\begin{tabular}{lrrr}", r"\toprule", r"Exposure block & Coefficient & Standard error & $p$-value \\", r"\midrule"]
    for variable, label in labels.items():
        row = dynamic.loc[dynamic.variable.eq(variable)].iloc[0]
        coefficient_p = student_t_two_sided_p(row.b, row.se)
        lines.append(
            f"{label} & {fmt(row.b)} & {fmt(row.se)} & {coefficient_p:.3f} \\\\")
    joint_lags = dynamic.loc[dynamic.variable.eq("joint_wald_all_zero")].iloc[0]
    lines += [
        r"\midrule",
        f"Joint significance of six lag coefficients & -- & -- & {joint_lags.p:.3f} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    (tables / "TablePivotA.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    outcome_labels = {
        "rc_petition_count": "All petitions",
        "election_180_count": "Election within 180 days",
        "certified_rep_365_count": "Representative certification within 365 days",
        "failed_180_count": "Withdrawal/dismissal within 180 days",
        "certified_tally_proxy_365_count": "Union-to-certify tally proxy within 365 days",
    }
    primary_common = common.loc[common.specification.eq("primary_common_support")]
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule", r"Outcome & Coefficient & Standard error & Observations & Outcome count \\", r"\midrule"]
    for outcome, label in outcome_labels.items():
        row = primary_common.loc[primary_common.outcome.eq(outcome)].iloc[0]
        lines.append(f"{label} & {fmt(row.b)} & {fmt(row.se)} & {int(row.N):,} & {int(row.outcome_count):,} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "TablePivotB.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    spec_labels = {
        "primary_nlra": ("NLRA-relevant predicted exposure", "hx_nlra"),
        "primary_controls": ("NLRA exposure + metro/size interactions", "hx_nlra"),
        "broad_private": ("Broad-private predicted exposure", "hx_broad"),
        "thermal_context": ("O*NET thermal context", "hx_thermal"),
        "naics3_published": ("Published-cell NAICS3 exposure", "hx_naics3"),
        "agriculture_placebo": ("Non-NLRA agriculture-share check", "hx_agriculture"),
    }
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule", r"Interaction & Coefficient & Standard error & $p$-value & Observations \\", r"\midrule"]
    for spec, (label, variable) in spec_labels.items():
        row = exposure.loc[exposure.specification.eq(spec) & exposure.variable.eq(variable)].iloc[0]
        coefficient_p = student_t_two_sided_p(row.b, row.se)
        lines.append(
            f"{label} & {fmt(row.b)} & {fmt(row.se)} & {coefficient_p:.3f} & "
            f"{int(row.N):,} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (tables / "TablePivotC.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    state_ri = ri.loc[ri.design.eq("state_year_block")].iloc[0]
    county_ri = ri.loc[ri.design.eq("county_year")].iloc[0]
    state_val = validation.loc[validation.design.eq("state_year_block")].iloc[0]
    county_val = validation.loc[validation.design.eq("county_year")].iloc[0]
    lines = [
        r"\begin{tabular}{lrr}", r"\toprule", r"Diagnostic & Estimate/statistic & Two-sided value \\", r"\midrule",
        f"Parent-union state-month allocation coefficient & {fmt(union.b)} ({fmt(union.se)}) & {union.p:.3f} \\\\",
        f"State-year-block permutation tail probability (999) & {state_ri.observed_score:.2f} & {state_ri.two_sided_p:.3f} \\\\",
        f"County-year raw-score tail probability (uncalibrated) & {county_ri.observed_score:.2f} & {county_ri.two_sided_p:.3f} \\\\",
        f"State-cluster wild-score bootstrap (9,999) & {wild.observed_score:.2f} & {wild.two_sided_p:.3f} \\\\",
        f"Exact/score Spearman, state blocks & {state_val.spearman_score_beta:.5f} & -- \\\\",
        f"Exact/score Spearman, county years & {county_val.spearman_score_beta:.5f} & -- \\\\",
        r"\bottomrule", r"\end{tabular}",
    ]

    

    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Specification & Coefficient & Standard error & $p$-value & Observations \\",
        r"\midrule",
        f"Parent-union state-month allocation & {fmt(union.b)} & {fmt(union.se)} & "
        f"{student_t_two_sided_p(union.b, union.se):.3f} & {int(union.N):,} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    (tables / "TablePivotD_parent_union.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    lines = [
        r"\begin{tabular}{lrrl}",
        r"\toprule",
        r"Mapping & Tail probability & Exact/score Spearman & Calibration status \\",
        r"\midrule",
        f"Unrestricted state-year blocks & {state_ri.two_sided_p:.3f} & {state_val.spearman_score_beta:.5f} & Validated (100 refits) \\\\",
        f"Nearby-year-stratified state blocks & {nearby_perm.two_sided_tail_probability:.3f} & -- & Score-based sensitivity \\\\",
        f"Independent county-year mapping & {county_ri.two_sided_p:.3f} & {county_val.spearman_score_beta:.5f} & Calibration failure \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    (tables / "TablePivotE_permutation.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

if __name__ == "__main__":
    main()
