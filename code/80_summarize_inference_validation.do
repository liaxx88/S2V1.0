version 18.0
set more off
capture noisily python script "$CODE/80_summarize_inference_validation.py", args("$ROOT")
local rc = _rc
if `rc' exit `rc'
