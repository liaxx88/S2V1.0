import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
table_names = {
    "TableJEEM1A_merge.tex", "TableJEEM1B_summary.tex", "TableJEEM2_margins.tex",
    "TableJEEM3_identification.tex", "TableJEEM4_inference.tex", "TableJEEM5_magnitude.tex",
    "TableG3B_2.tex", "TablePivotA.tex", "TablePivotB.tex", "TablePivotC.tex",
    "TablePivotD_parent_union.tex", "TablePivotE_permutation.tex", "TableJEEMA1_timing.tex",
    "TableJEEMA2_support.tex", "TableJEEMA3_dose.tex", "TableJEEMA4_robustness.tex",
}
figure_names = {
    "FigurePivotA_state_week_dynamics.pdf", "FigureJEEM2_leads_lags.pdf",
    "FigureG25_1_randomization.pdf", "FigureJEEM3_dose_response.pdf",
    "FigureJEEM4_reallocation.pdf",
}
result_names = {
    "final_pivot_common_support_progression_results.csv", "final_pivot_county_exposure_results.csv",
    "final_pivot_data_audit.csv", "final_pivot_state_week_dynamic_results.csv",
    "gate2_leave_one_state_out.csv", "gate2_merge_audit.csv", "gate2_model_results.csv",
    "gate25_model_results.csv", "gate25_randomization_summary.csv", "gate3b_model_results.csv",
    "gate3b_outcome_audit.csv", "jeem_extension_dose_results.csv", "jeem_extension_main_results.csv",
    "jeem_extension_reallocation_summary.csv", "jeem_extension_support_results.csv",
    "jeem_extension_timing_results.csv", "jeem_identification_results.csv",
    "jeem_trend_preserving_permutation_summary.csv", "ri_score_exact_validation_summary.csv",
    "state_cluster_wild_score_summary.csv", "union_allocation_data_gate.csv",
    "union_allocation_model_results.csv", "union_exact_week_data_gate.csv",
}
clean_names = {
    Path("gate1/nlrb_petitions_gate1_v1.parquet"),
    Path("gate1/nlrb_elections_gate1_v1.parquet"),
    Path("gate1/nlrb_case_election_gate1_v1.parquet"),
    Path("gate1/nlrb_geocode_gate1_v1.parquet"),
    Path("gate2/county_week_analysis_v1.parquet"),
    Path("gate3/industry_heat_exposure_2019.parquet"),
    Path("final_pivot/progression_common_support_v1.parquet"),
    Path("final_pivot/county_predicted_heat_exposure_2010_v1.parquet"),
    Path("jeem_extension/jeem_extension_county_week_v1.parquet"),
}
for path in (root / "tables").glob("*"):
    if path.name not in table_names:
        path.unlink()
for path in (root / "figures").glob("*"):
    if path.name not in figure_names:
        path.unlink()
results = root / "data" / "clean" / "results"
for path in results.glob("*"):
    if path.name not in result_names:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
for path in (root / "data" / "clean").rglob("*"):
    if path.is_file() and "results" not in path.parts:
        relative = path.relative_to(root / "data" / "clean")
        if relative not in clean_names:
            path.unlink()
for path in sorted((root / "data" / "clean").rglob("*"), reverse=True):
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
if {p.name for p in (root / "tables").iterdir()} != table_names:
    raise RuntimeError("table inventory")
if {p.name for p in (root / "figures").iterdir()} != figure_names:
    raise RuntimeError("figure inventory")
