from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

OUTCOME_LABELS = {
    "rc_petition_count": "All RC petitions",
    "election_180_count": "Election $\\leq$180 days",
    "certified_rep_365_count": "Representative certification $\\leq$365 days",
    "failed_180_count": "Withdraw/dismiss $\\leq$180 days",
}

def tex_number(value: float) -> str:
    if value != 0 and abs(value) < 0.0001:
        exponent = math.floor(math.log10(abs(value)))
        mantissa = value / (10 ** exponent)
        return rf"${mantissa:.2f}\times 10^{{{exponent}}}$"
    return f"{value:.5f}"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    audit = root / "data" / "clean" / "results"
    tables = root / "tables"

    results = pd.read_csv(audit / "gate3b_model_results.csv")
    table_lines = [
        r"\begin{tabular}{lccc}",
        r"\toprule",
        r"Outcome & County-week PPML & State-week PPML & Full-panel count OLS \\",
        r"\midrule",
    ]
    for outcome, label in OUTCOME_LABELS.items():
        rows = results.loc[results.outcome.eq(outcome)].set_index("family")
        table_lines.append(
            f"{label} & {rows.loc['county_week_ppml','b']:.5f} & "
            f"{rows.loc['state_week_ppml','b']:.5f} & "
            f"{tex_number(rows.loc['full_panel_ols','b'])} \\\\"
        )
        table_lines.append(
            f"\\quad State-cluster SE & ({rows.loc['county_week_ppml','se']:.5f}) & "
            f"({rows.loc['state_week_ppml','se']:.5f}) & "
            f"({tex_number(rows.loc['full_panel_ols','se'])}) \\\\"
        )
        table_lines.append(
            f"\\quad Observations & {int(rows.loc['county_week_ppml','N']):,} & "
            f"{int(rows.loc['state_week_ppml','N']):,} & {int(rows.loc['full_panel_ols','N']):,} \\\\"
        )
    table_lines.extend([r"\bottomrule", r"\end{tabular}"])
    (tables / "TableG3B_2.tex").write_text("\n".join(table_lines) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
