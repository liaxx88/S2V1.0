version 18.0
set more off
python script "$CODE/72_summarize_gate3b.py", args("$ROOT")
if _rc exit _rc
confirm file "$TABLES/TableG3B_2.tex"
