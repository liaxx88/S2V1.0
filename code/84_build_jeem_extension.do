version 18.0
clear all
set more off

capture noisily python script "$CODE/84_build_jeem_extension.py", args("$ROOT")
local rc = _rc
if `rc' exit `rc'

confirm file "$JEEM_EXT/jeem_extension_county_week_v1.dta"
confirm file "$JEEM_EXT/jeem_extension_data_manifest.json"
di as result "JEEM extension data build completed."
