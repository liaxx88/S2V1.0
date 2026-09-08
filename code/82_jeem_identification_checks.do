version 18.0
clear all
set more off

foreach input in  "$GATE2/county_week_ppml_core_v1.dta"  "$GATE2/county_week_analysis_v1.dta"  "$AUDIT/gate2_model_results.csv" {
    confirm file `"`input'"'
}

use "$GATE2/county_week_ppml_core_v1.dta", clear
assert ppml_core_sample == 1
egen long county_year_fe = group(county_id calendar_year)

tempname results
postfile `results' str32 specification str32 variable double b se p N  petition_events counties using "$JEEM/jeem_identification_results.dta", replace

preserve
    import delimited using "$AUDIT/gate2_model_results.csv", clear varnames(1)
    keep if family == "baseline" & specification == "g2_b4" & variable == "p95_days_lag1_4"
    assert _N == 1
    local primary_b = b[1]
    local primary_se = se[1]
    local primary_p = p[1]
    local primary_n = n[1]
restore
tempvar primary_county_tag
egen byte `primary_county_tag' = tag(county_id)
quietly count if `primary_county_tag'
local primary_counties = r(N)
quietly summarize rc_petition_count, meanonly
local primary_events = r(sum)
post `results' ("primary") ("p95_days_lag1_4")  (`primary_b') (`primary_se') (`primary_p') (`primary_n')  (`primary_events') (`primary_counties')

preserve
    bysort county_year_fe: egen double county_year_petitions = total(rc_petition_count)
    keep if county_year_petitions > 0
    drop county_year_petitions
    quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe county_year_fe state_yearweek_fe)  offset(log_private_emp_lag12) vce(cluster state_id) nolog
    tempvar esample county_tag
    generate byte `esample' = e(sample)
    egen byte `county_tag' = tag(county_id) if `esample'
    quietly count if `county_tag'
    local cy_counties = r(N)
    quietly summarize rc_petition_count if `esample', meanonly
    local cy_events = r(sum)
    local cy_b = _b[p95_days_lag1_4]
    local cy_se = _se[p95_days_lag1_4]
    local cy_p = 2 * normal(-abs(`cy_b' / `cy_se'))
    post `results' ("jeem_countyyear") ("p95_days_lag1_4")  (`cy_b') (`cy_se') (`cy_p') (e(N)) (`cy_events') (`cy_counties')
restore

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 precipitation_lag1_4,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
tempvar esample county_tag
generate byte `esample' = e(sample)
egen byte `county_tag' = tag(county_id) if `esample'
quietly count if `county_tag'
local precip_counties = r(N)
quietly summarize rc_petition_count if `esample', meanonly
local precip_events = r(sum)
local precip_heat_b = _b[p95_days_lag1_4]
local precip_heat_se = _se[p95_days_lag1_4]
local precip_heat_p = 2 * normal(-abs(`precip_heat_b' / `precip_heat_se'))
post `results' ("jeem_precipitation") ("p95_days_lag1_4")  (`precip_heat_b') (`precip_heat_se') (`precip_heat_p') (e(N))  (`precip_events') (`precip_counties')
local precip_b = _b[precipitation_lag1_4]
local precip_se = _se[precipitation_lag1_4]
local precip_p = 2 * normal(-abs(`precip_b' / `precip_se'))
post `results' ("jeem_precipitation") ("precipitation_lag1_4")  (`precip_b') (`precip_se') (`precip_p') (e(N))  (`precip_events') (`precip_counties')
postclose `results'

preserve
    use "$JEEM/jeem_identification_results.dta", clear
    generate ci_low = b - invnormal(0.975) * se
    generate ci_high = b + invnormal(0.975) * se
    export delimited using "$AUDIT/jeem_identification_results.csv", replace
restore
