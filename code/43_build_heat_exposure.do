version 18.0

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc exit 111
    python set exec `"`python_exec'"'
}

python script "$CODE/43_build_heat_exposure.py", args("$ROOT")
confirm file "$NOAA_CLEAN/noaa_heat_thresholds_1981_2010.parquet"
confirm file "$NOAA_CLEAN/noaa_county_week_heat_2010_2024.parquet"
confirm file "$AUDIT/heat_measure_audit.csv"
di as result "Heat thresholds and county-week exposures created."
