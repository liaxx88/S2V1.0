version 18.0

foreach input in  "$RAW/census/geocoder/nlrb_census_batch_001_results_raw.csv"  "$RAW/census/geocoder/nlrb_census_batch_002_results_raw.csv"  "$NLRB_CLEAN/nlrb_geography_preliminary.csv" {
    capture confirm file `"`input'"'
    if _rc {
        di as error "Missing Census geocoding input: `input'"
        exit 601
    }
}

capture python query
if _rc {
    local python_exec "$PYTHON_EXE"
    capture confirm file `"`python_exec'"'
    if _rc {
        di as error "Python is not configured in Stata and the bundled runtime was not found."
        exit 111
    }
    python set exec `"`python_exec'"'
}

python script "$CODE/24_clean_census_geocoder.py", args(  "$RAW/census/geocoder"  "$NLRB_CLEAN/census_batch_input"  "$NLRB_CLEAN/nlrb_geography_preliminary.csv"  "$NLRB_CLEAN/census_geocoder_results_clean.csv"  "$NLRB_CLEAN/nlrb_geography_master.csv")

import delimited using "$NLRB_CLEAN/census_geocoder_results_clean.csv", clear  varnames(1) case(lower) stringcols(_all) bindquotes(strict)  maxquotedrows(unlimited) encoding(UTF-8)
replace case_number = upper(strtrim(case_number))
isid case_number
compress
save "$NLRB_CLEAN/census_geocoder_results_clean.dta", replace

import delimited using "$NLRB_CLEAN/nlrb_geography_master.csv", clear  varnames(1) case(lower) stringcols(_all) bindquotes(strict)  maxquotedrows(unlimited) encoding(UTF-8)
foreach variable in geocode_quality county_disagreement has_street_address  has_zip main_geo latitude longitude {
    destring `variable', replace force
}
replace case_number = upper(strtrim(case_number))
replace county_fips = strtrim(county_fips)
replace county_fips = substr("00000" + county_fips, -5, 5) if county_fips != ""
isid case_number
compress
save "$NLRB_CLEAN/nlrb_geography_master.dta", replace

tempfile geography
save `geography', replace
use "$NLRB_CLEAN/nlrb_petitions_master.dta", clear
merge 1:1 case_number using `geography', assert(match) nogenerate
sort case_number
isid case_number
compress
save "$NLRB_CLEAN/nlrb_petitions_geocoded.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_petitions_geocoded.csv", replace

count if main_geo == 1
local n_main = r(N)
count if main_geo == 1 & county_fips != ""
local n_county = r(N)
count if main_geo == 1 & geocode_quality == 1
local n_exact = r(N)
di as result "Final county match: `n_county' of `n_main' main-sample petitions."
di as result "Exact Census address matches: `n_exact' of `n_main'."
