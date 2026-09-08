version 18.0

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc exit 111
    python set exec `"`python_exec'"'
}

python script "$CODE/42_clean_noaa_daily.py", args("$ROOT")
confirm file "$NOAA_CLEAN/noaa_county_daily_1981_2024.parquet"
confirm file "$AUDIT/weather_audit_by_year.csv"
di as result "NOAA county-day weather and Weather Audit created."
