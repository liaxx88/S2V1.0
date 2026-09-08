version 18.0
set more off
capture noisily python script "$CODE/74_build_final_pivot_data.py", args("$ROOT")
local rc = _rc
if `rc' exit `rc'

confirm file "$PIVOT/final_pivot_data_manifest.json"
