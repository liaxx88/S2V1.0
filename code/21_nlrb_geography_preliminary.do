version 18.0

local place_zip "$RAW/census/cartographic_2024/cb_2024_us_place_500k.zip"
local county_zip "$RAW/census/cartographic_2024/cb_2024_us_county_500k.zip"
local zcta_file "$RAW/census/relationships_2020/tab20_zcta520_county20_natl.txt"
foreach input in `"`place_zip'"' `"`county_zip'"' `"`zcta_file'"' {
    capture confirm file `"`input'"'
    if _rc {
        di as error "Missing official Census geography input: `input'"
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

python script "$CODE/21_census_place_county_crosswalk.py", args(  `"`place_zip'"' `"`county_zip'"' `"`zcta_file'"'  "$NLRB_CLEAN/census_place_county_crosswalk.csv"  "$NLRB_CLEAN/census_zip_county_crosswalk.csv"  "$NLRB_CLEAN/nlrb_address_candidates.csv")

python script "$CODE/22_nlrb_geography_preliminary.py", args(  "$NLRB_CLEAN/nlrb_address_candidates.csv"  "$NLRB_CLEAN/census_place_county_crosswalk.csv"  "$NLRB_CLEAN/census_zip_county_crosswalk.csv"  "$NLRB_CLEAN/nlrb_geography_preliminary.csv")

import delimited using "$NLRB_CLEAN/nlrb_geography_preliminary.csv", clear  varnames(1) case(lower) stringcols(_all) bindquotes(strict)  maxquotedrows(unlimited) encoding(UTF-8)
foreach variable in geocode_quality has_street_address has_zip main_geo {
    destring `variable', replace force
}
replace case_number = upper(strtrim(case_number))
replace county_fips = strtrim(county_fips)
replace county_fips = substr("00000" + county_fips, -5, 5) if county_fips != ""
isid case_number
compress
save "$NLRB_CLEAN/nlrb_geography_preliminary.dta", replace

count if main_geo == 1
local n_main = r(N)
count if main_geo == 1 & county_fips != ""
local n_county = r(N)
count if main_geo == 1 & (has_street_address == 1 | inrange(geocode_quality, 1, 3))
local n_location = r(N)
di as result "Preliminary county match: `n_county' of `n_main' main-sample petitions."
di as result "Street address or unambiguous Census location: `n_location' of `n_main'."
