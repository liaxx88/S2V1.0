version 18.0
set more off

confirm file "$GATE2/county_week_ppml_core_v1.dta"
capture which ppmlhdfe
if _rc exit 111

use "$GATE2/county_week_ppml_core_v1.dta", clear
quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
generate byte gate2_esample = e(sample)

tempname influence
postfile `influence' str2 excluded_state double b se p N rc  using "$GATE2/gate2_leave_one_state_out.dta", replace
levelsof state_fips if gate2_esample == 1, local(states)
foreach state of local states {
    capture quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if gate2_esample == 1 & state_fips != "`state'",  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-6) nolog
    local rc = _rc
    if `rc' {
        post `influence' ("`state'") (.) (.) (.) (.) (`rc')
    }
    else {
        local bb = _b[p95_days_lag1_4]
        local ss = _se[p95_days_lag1_4]
        post `influence' ("`state'") (`bb') (`ss')  (2*normal(-abs(`bb'/`ss'))) (e(N)) (0)
    }
    di as txt "Leave-one-state-out: excluded `state'"
}
postclose `influence'

preserve
    use "$GATE2/gate2_leave_one_state_out.dta", clear
    generate ci_low = b - invnormal(.975) * se
    generate ci_high = b + invnormal(.975) * se
    export delimited using "$AUDIT/gate2_leave_one_state_out.csv", replace
restore

di as result "Gate 2 leave-one-state-out influence audit completed."
