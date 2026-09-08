version 18.0
clear all
set more off

capture noisily python script "$CODE/87_finalize_jeem_extension.py", args("$ROOT")
if _rc exit _rc
confirm file "$TABLES/TableJEEM3_identification.tex"
confirm file "$TABLES/TableJEEM4_inference.tex"
confirm file "$TABLES/TableJEEM5_magnitude.tex"
di as result "JEEM extension gate decision and tables completed."
