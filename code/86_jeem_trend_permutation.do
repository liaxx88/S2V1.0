version 18.0
clear all
set more off

capture noisily python script "$CODE/86_jeem_trend_permutation.py", args("$ROOT" "--repetitions" "999")
if _rc exit _rc

confirm file "$JEEM_EXT/jeem_trend_preserving_permutation.parquet"
confirm file "$AUDIT/jeem_trend_preserving_permutation_summary.csv"
confirm file "$JEEM_EXT/jeem_trend_preserving_permutation_manifest.json"
di as result "Trend-preserving state-year-block permutation diagnostic completed."
