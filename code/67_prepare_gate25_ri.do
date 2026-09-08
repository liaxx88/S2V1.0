version 18.0
set more off

use "$GATE2/county_week_ppml_core_v1.dta", clear
quietly ppmlhdfe rc_petition_count if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  separation(fe) tolerance(1e-8) d(ri_absorbed_fe) nolog
generate byte ri_esample = e(sample)
predict double ri_mu if ri_esample, mu
generate double ri_residual = rc_petition_count - ri_mu if ri_esample

keep if ri_esample
keep county_id state_id county_fips state_fips week_start calendar_year  p95_days_lag1_4 ri_mu ri_residual rc_petition_count
isid county_id week_start
save "$GATE25/gate25_ri_null_score_sample.dta", replace

quietly summarize ri_residual, meanonly
assert abs(r(sum)) < 1e-2
di as result "Gate 2.5 null-score sample saved with " _N " observations."
