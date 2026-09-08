version 18.0
set more off
capture noisily python script "$CODE/78_build_inference_validation.py", args("$ROOT")
local rc = _rc
if `rc' exit `rc'
confirm file "$PIVOT/ri_validation_permutations_v1.dta"
