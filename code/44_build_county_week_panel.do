version 18.0

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc exit 111
    python set exec `"`python_exec'"'
}

python script "$CODE/44_build_county_week_panel.py", args("$ROOT")
confirm file "$GATE2/county_week_analysis_v1.parquet"
confirm file "$GATE2/county_week_analysis_v1.dta"
confirm file "$AUDIT/gate2_merge_audit.csv"
di as result "Gate 2 county-week analysis panel created."
