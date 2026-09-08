version 18.0

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc exit 111
    python set exec `"`python_exec'"'
}

python script "$CODE/41_clean_qcew.py", args("$ROOT")
confirm file "$QCEW_CLEAN/qcew_county_month_private.parquet"
confirm file "$AUDIT/qcew_county_month_audit.csv"
di as result "QCEW county-month denominators created."
