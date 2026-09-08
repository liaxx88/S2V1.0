from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

def main() -> None:
    root = Path(sys.argv[1]).resolve()
    audit = root / "data" / "clean" / "results"
    scores = pd.read_csv(audit / "ri_validation_scores.csv")
    exact = pd.read_csv(audit / "ri_exact_refit_validation_results.csv")
    merged = scores.merge(exact, on=["design", "repetition"], validate="one_to_one")
    merged.to_csv(audit / "ri_score_exact_validation_merged.csv", index=False, lineterminator="\n")
    rows = []
    for design, part in merged.groupby("design"):
        valid = part.loc[part.rc.eq(0) & part.b.notna()]

        
        rho = valid.score.rank(method="average").corr(valid.b.rank(method="average"))
        if rho >= 0.90:
            status = "VALIDATED"
        elif rho >= 0.75:
            status = "VALIDATED_WITH_CAVEAT"
        else:
            status = "EXACT_999_REQUIRED"
        exact_extreme = int((valid.b.abs() >= valid.observed_b.abs()).sum())
        rows.append({
            "design": design,
            "requested_refits": len(part),
            "valid_refits": len(valid),
            "spearman_score_beta": rho,
            "validation_status": status,
            "validation_exact_two_sided_extreme": exact_extreme,
            "validation_exact_two_sided_p": (exact_extreme + 1) / (len(valid) + 1),
        })
    summary = pd.DataFrame(rows)
    summary.to_csv(audit / "ri_score_exact_validation_summary.csv", index=False, lineterminator="\n")
    print(summary.to_string(index=False))

if __name__ == "__main__":
    main()
