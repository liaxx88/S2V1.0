version 18.0
set more off
capture noisily python script "$CODE/76_union_allocation_audit.py", args("$ROOT")
local rc = _rc
if `rc' exit `rc'
confirm file "$PIVOT/union_allocation_gate_status.json"
