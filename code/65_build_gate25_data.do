version 18.0
set more off

python script "$CODE/65_build_gate25_data.py", args("$ROOT")
if _rc exit _rc

confirm file "$GATE25/gate25_data_manifest.json"
confirm file "$GATE25/state_week_incidence_v1.dta"
