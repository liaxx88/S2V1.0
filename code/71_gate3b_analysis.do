version 18.0
set more off

foreach input in  "$GATE3B/county_week_progression_ppml_core_v1.dta"  "$GATE3B/county_week_progression_v1.dta"  "$GATE3B/state_week_progression_v1.dta" {
    confirm file `"`input'"'
}

tempname results
postfile `results' str28 family str36 specification str36 outcome str40 variable  double b se p N positive_outcome_rows outcome_count units  using "$GATE3B/gate3b_model_results.dta", replace

local outcomes rc_petition_count election_180_count certified_rep_365_count failed_180_count

use "$GATE3B/county_week_progression_ppml_core_v1.dta", clear
estimates clear
local model_number = 0
foreach outcome of local outcomes {
    local ++model_number
    local flag "core_`outcome'"
    quietly ppmlhdfe `outcome' p95_days_lag1_4 if `flag' == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    estimates store g3b_c`model_number'
    quietly count if e(sample) & `outcome' > 0
    local pos = r(N)
    quietly summarize `outcome' if e(sample), meanonly
    local total = r(sum)
    egen byte unit_tag = tag(county_id) if e(sample)
    quietly count if unit_tag
    local units = r(N)
    drop unit_tag
    post `results' ("county_week_ppml") ("primary_design") ("`outcome'")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`pos') (`total') (`units')
}

use "$GATE3B/state_week_progression_v1.dta", clear
rename state_p95_days_lag1_4 p95_days_lag1_4
local model_number = 0
foreach outcome of local outcomes {
    local ++model_number
    quietly ppmlhdfe `outcome' p95_days_lag1_4,  absorb(state_month_fe national_week_fe) offset(log_state_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    estimates store g3b_s`model_number'
    quietly count if e(sample) & `outcome' > 0
    local pos = r(N)
    quietly summarize `outcome' if e(sample), meanonly
    local total = r(sum)
    egen byte unit_tag = tag(state_id) if e(sample)
    quietly count if unit_tag
    local units = r(N)
    drop unit_tag
    post `results' ("state_week_ppml") ("aggregate_incidence") ("`outcome'")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`pos') (`total') (`units')
}

use "$GATE3B/county_week_progression_v1.dta", clear
keep if analysis_sample == 1
egen long national_week_fe = group(week_start)
egen long state_month_fe = group(state_id calendar_month)
local model_number = 0
foreach outcome of local outcomes {
    local ++model_number
    quietly reghdfe `outcome' p95_days_lag1_4,  absorb(county_id national_week_fe state_month_fe) vce(cluster state_id) compact
    estimates store g3b_o`model_number'
    quietly count if e(sample) & `outcome' > 0
    local pos = r(N)
    quietly summarize `outcome' if e(sample), meanonly
    local total = r(sum)
    egen byte unit_tag = tag(county_id) if e(sample)
    quietly count if unit_tag
    local units = r(N)
    drop unit_tag
    post `results' ("full_panel_ols") ("count_ols_diagnostic") ("`outcome'")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`pos') (`total') (`units')
}

postclose `results'

preserve
    use "$GATE3B/gate3b_model_results.dta", clear
    generate ci_low = b - invnormal(0.975)*se
    generate ci_high = b + invnormal(0.975)*se
    export delimited using "$AUDIT/gate3b_model_results.csv", replace

restore

di as result "Gate 3B institutional-persistence analyses completed."
