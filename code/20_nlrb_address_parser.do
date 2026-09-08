version 18.0

capture confirm file "$NLRB_CLEAN/nlrb_case_unit_master.csv"
if _rc {
    di as error "Run code/13_nlrb_case_unit_merge.do first."
    exit 601
}

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc {
        di as error "Python is not configured in Stata and the bundled runtime was not found."
        di as error "Configure Stata's Python integration before running the address parser."
        exit 111
    }
    python set exec `"`python_exec'"'
}

python script "$CODE/20_nlrb_address_parser.py", args(  "$NLRB_CLEAN/nlrb_case_unit_master.csv"  "$NLRB_CLEAN/nlrb_address_candidates.csv")

python script "$CODE/23_prepare_census_geocoder_batches.py", args(  "$NLRB_CLEAN/nlrb_address_candidates.csv"  "$NLRB_CLEAN/census_batch_input"  "$NLRB_CLEAN/census_batch_input/manifest.json")

import delimited using "$NLRB_CLEAN/nlrb_address_candidates.csv", clear  varnames(1) case(lower) stringcols(_all) bindquotes(strict)  maxquotedrows(unlimited) encoding(UTF-8)

foreach variable in has_street_address has_zip address_candidate_count  source_priority main_geo {
    destring `variable', replace force
}

replace case_number = upper(strtrim(case_number))
replace geocode_state = upper(strtrim(geocode_state))
isid case_number
compress
save "$NLRB_CLEAN/nlrb_address_candidates.dta", replace

count if main_geo == 1
local n_main = r(N)
count if main_geo == 1 & has_street_address == 1
local n_street = r(N)
count if main_geo == 1 & has_zip == 1
local n_zip = r(N)
di as result "Parsed a street-address candidate for `n_street' of `n_main' main-sample petitions."
di as result "Parsed a ZIP code for `n_zip' of `n_main' main-sample petitions."
