version 18.0
clear all
set more off
global ROOT "`c(pwd)'"
capture confirm file "$ROOT/code/setup.do"
if _rc exit 601
do "$ROOT/code/setup.do"
python script "$CODE/00_reset_outputs.py", args("$ROOT")
local programs "10_nlrb_petitions.do 12_nlrb_elections.do 13_nlrb_case_unit_merge.do 20_nlrb_address_parser.do 21_nlrb_geography_preliminary.do 22_nlrb_geography_finalize.do 30_freeze_gate1_v1.do 41_clean_qcew.do 42_clean_noaa_daily.do 43_build_heat_exposure.do 44_build_county_week_panel.do 50_gate2_analysis.do 51a_gate2_state_influence.do 63_build_industry_heat_exposure.do 65_build_gate25_data.do 66_gate25_analysis.do 67_gate25_randomization.do 70_build_gate3b.do 71_gate3b_analysis.do 72_summarize_gate3b.do 74_build_final_pivot_data.do 75_final_pivot_core_analysis.do 76_union_allocation_audit.do 77_union_allocation_analysis.do 78_build_inference_validation.do 79_exact_refit_validation.do 80_summarize_inference_validation.do 82_jeem_identification_checks.do 84_build_jeem_extension.do 85_jeem_extension_analysis.do 86_jeem_trend_permutation.do 81_finalize_pivot.do 87_finalize_jeem_extension.do"
foreach program of local programs {
    capture noisily do "$CODE/`program'"
    if _rc exit _rc
}
python script "$CODE/99_finalize_outputs.py", args("$ROOT")
exit, clear
