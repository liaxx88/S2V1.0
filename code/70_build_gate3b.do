version 18.0
set more off
python script "$CODE/70_build_gate3b.py", args("$ROOT")
if _rc exit _rc
confirm file "$GATE3B/gate3b_v1_manifest.json"
