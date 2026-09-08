version 18.0
set more off
capture noisily python script "$CODE/81_finalize_pivot.py", args("$ROOT")
local rc = _rc
if `rc' exit `rc'
confirm file "$TABLES/TablePivotA.tex"
