version 18.0
if "$ROOT" == "" global ROOT "`c(pwd)'"
global CODE "$ROOT/code"
global DATA "$ROOT/data"
global RAW "$DATA/raw"
global CLEAN "$DATA/clean"
global NLRB_RAW "$RAW/nlrb"
global NLRB_CLEAN "$CLEAN/nlrb"
global GATE1 "$CLEAN/gate1"
global AUDIT "$CLEAN/results"
global NOAA_RAW "$RAW/noaa/nclimgrid_daily"
global NOAA_CLEAN "$CLEAN/noaa"
global QCEW_RAW "$RAW/qcew"
global QCEW_CLEAN "$CLEAN/qcew"
global GATE2 "$CLEAN/gate2"
global GATE3 "$CLEAN/gate3"
global GATE25 "$CLEAN/gate25"
global GATE3B "$CLEAN/gate3b"
global PIVOT "$CLEAN/final_pivot"
global JEEM "$CLEAN/jeem"
global JEEM_EXT "$CLEAN/jeem_extension"
global USDA_RAW "$RAW/usda"
global TABLES "$ROOT/tables"
global FIGURES "$ROOT/figures"
global ADO "$CODE/vendor/stata"
global PYTHON_VENDOR "$CODE/vendor/python"
global PYTHON_EXE "$CODE/vendor/python_runtime/python.exe"
global NLRB_FIRST_YEAR 2011
global NLRB_LAST_YEAR 2024
foreach folder in "$CLEAN" "$NLRB_CLEAN" "$GATE1" "$AUDIT" "$NOAA_CLEAN" "$QCEW_CLEAN" "$GATE2" "$GATE3" "$GATE25" "$GATE3B" "$PIVOT" "$JEEM" "$JEEM_EXT" "$TABLES" "$FIGURES" {
    capture mkdir `"`folder'"'
}
adopath ++ "$ADO"
capture python query
if _rc python set exec "$PYTHON_EXE"
python set userpath "$PYTHON_VENDOR"
set more off
set varabbrev off
set type double
