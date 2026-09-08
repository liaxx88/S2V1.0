version 18.0
set more off

import delimited using "$AUDIT/union_allocation_data_gate.csv", clear varnames(1)
quietly count if metric == "organizer_allocation_gate" & value == "PASS"
if r(N) == 0 {
    di as result "Organizer allocation gate did not pass; estimation skipped by protocol."
    exit 0
}

confirm file "$PIVOT/union_allocation_risk_v1.dta"
use "$PIVOT/union_allocation_risk_v1.dta", clear
quietly ppmlhdfe union_petition_count p95_days_lag1_4,  absorb(union_state_month_fe county_month_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog

clear
set obs 1
generate str36 family = "union_county_week_ppml"
generate str48 specification = "union_state_month_allocation"
generate str40 variable = "p95_days_lag1_4"
generate double b = _b[p95_days_lag1_4]
generate double se = _se[p95_days_lag1_4]
generate double p = 2*normal(-abs(b/se))
generate double N = e(N)
generate double ci_low = b - invnormal(0.975)*se
generate double ci_high = b + invnormal(0.975)*se
save "$PIVOT/union_allocation_results.dta", replace
export delimited using "$AUDIT/union_allocation_model_results.csv", replace

di as result "Organizer allocation model completed after passing its data gate."
