version 18.0
set more off

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc exit 111
    python set exec `"`python_exec'"'
}

python script "$CODE/63_build_industry_heat_exposure.py", args("$ROOT")
