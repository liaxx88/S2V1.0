version 18.0

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc {
        di as error "Python is not configured and the bundled runtime was not found."
        exit 111
    }
    python set exec `"`python_exec'"'
}

python script "$CODE/30_freeze_gate1_v1.py", args("$ROOT")

foreach frozen_file in  "$GATE1/nlrb_petitions_gate1_v1.parquet"  "$GATE1/nlrb_elections_gate1_v1.parquet"  "$GATE1/nlrb_case_election_gate1_v1.parquet"  "$GATE1/nlrb_geocode_gate1_v1.parquet"  "$GATE1/gate1_v1_manifest.json"  "$AUDIT/gate1_summary.csv"  "$AUDIT/gate1_by_year.csv"  "$AUDIT/gate1_by_state.csv"  "$AUDIT/gate1_geocode_quality.csv"  "$AUDIT/gate1_election_merge.csv" {
    confirm file `"`frozen_file'"'
}

di as result "Gate 1 V1 is present and passed immutable hash verification."
