version 18.0
set more off

confirm file "$GATE2/county_week_analysis_v1.dta"
confirm file "$GATE2/county_week_ppml_core_v1.dta"
capture which ppmlhdfe
if _rc {
    di as error "Run code/45_prepare_ppmlhdfe.do first."
    exit 111
}

use "$GATE2/county_week_analysis_v1.dta", clear
isid county_fips week_start
assert inrange(week_start, td(03jan2011), td(30dec2024))

estimates clear
quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if analysis_sample == 1,  vce(cluster state_id) nolog
estimates store g2_b1

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if analysis_sample == 1,  absorb(county_month_fe) vce(cluster state_id) nolog
estimates store g2_b2

use "$GATE2/county_week_ppml_core_v1.dta", clear
assert rc_petition_count >= 0

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) vce(cluster state_id) nolog
estimates store g2_b3

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
estimates store g2_b4

quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if ppml_core_sample == 1 & !missing(log_nlra_proxy_partial_lag12),  absorb(county_month_fe state_yearweek_fe) offset(log_nlra_proxy_partial_lag12)  vce(cluster state_id) nolog
estimates store g2_b5

tempname results
postfile `results' str40 family str48 specification str40 variable  double b se p N using "$GATE2/gate2_model_results.dta", replace

foreach model in g2_b1 g2_b2 g2_b3 g2_b4 g2_b5 {
    estimates restore `model'
    local bb = _b[p95_days_lag1_4]
    local ss = _se[p95_days_lag1_4]
    local pp = 2 * normal(-abs(`bb' / `ss'))
    post `results' ("baseline") ("`model'") ("p95_days_lag1_4") (`bb') (`ss') (`pp') (e(N))
}

quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if ppml_core_sample == 1 & !missing(log_nlra_proxy_emp_lag12),  absorb(county_month_fe state_yearweek_fe) offset(log_nlra_proxy_emp_lag12)  vce(cluster state_id) nolog
post `results' ("denominator") ("nlra_proxy_exact_subset") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (e(N))

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 p95_days_lag5_8  p95_days_lag9_12 p95_days_lag13_16 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
estimates store g2_dynamic16
foreach variable in p95_days_lag1_4 p95_days_lag5_8 p95_days_lag9_12 p95_days_lag13_16 {
    local bb = _b[`variable']
    local ss = _se[`variable']
    local pp = 2 * normal(-abs(`bb' / `ss'))
    post `results' ("dynamic") ("dynamic16") ("`variable'") (`bb') (`ss') (`pp') (e(N))
}
quietly lincom p95_days_lag1_4 + p95_days_lag5_8 + p95_days_lag9_12 + p95_days_lag13_16
post `results' ("cumulative") ("dynamic16") ("sum_beta_1_16")  (r(estimate)) (r(se)) (r(p)) (e(N))

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 p95_days_lag5_8  p95_days_lag9_12 p95_days_lag13_16 p95_days_lag17_20 p95_days_lag21_24  if ppml_core_sample == 1 & !missing(p95_days_lag21_24),  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
quietly lincom p95_days_lag1_4 + p95_days_lag5_8 + p95_days_lag9_12 +  p95_days_lag13_16 + p95_days_lag17_20 + p95_days_lag21_24
post `results' ("cumulative") ("dynamic24") ("sum_beta_1_24")  (r(estimate)) (r(se)) (r(p)) (e(N))

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 p95_days_lag5_8  p95_days_lag9_12 p95_days_lag13_16 p95_days_future9_16  if ppml_core_sample == 1 & !missing(p95_days_future9_16),  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
foreach variable in p95_days_lag1_4 p95_days_future9_16 {
    local bb = _b[`variable']
    local ss = _se[`variable']
    local pp = 2 * normal(-abs(`bb' / `ss'))
    post `results' ("placebo") ("future9_16") ("`variable'") (`bb') (`ss') (`pp') (e(N))
}

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 p95_days_next_year  if ppml_core_sample == 1 & !missing(p95_days_next_year),  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
foreach variable in p95_days_lag1_4 p95_days_next_year {
    local bb = _b[`variable']
    local ss = _se[`variable']
    local pp = 2 * normal(-abs(`bb' / `ss'))
    post `results' ("placebo") ("next_year") ("`variable'") (`bb') (`ss') (`pp') (e(N))
}

local altvars p90_days_lag1_4 p95_days_lag1_4 p99_days_lag1_4  days90f_lag1_4 days95f_lag1_4 days100f_lag1_4 excess_heat_c_lag1_4  heatwave_days_lag1_4 night_heat_lag1_4
foreach variable of local altvars {
    quietly ppmlhdfe rc_petition_count `variable' if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
    local bb = _b[`variable']
    local ss = _se[`variable']
    local pp = 2 * normal(-abs(`bb' / `ss'))
    post `results' ("alternative_heat") ("`variable'") ("`variable'")  (`bb') (`ss') (`pp') (e(N))
}

foreach outcome in rc_count_excl_starbucks rc_count_excl_starbucks_amazon  rc_count_excl_top1 rc_count_excl_top5 rc_count_excl_top10 {
    quietly ppmlhdfe `outcome' p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
    local bb = _b[p95_days_lag1_4]
    local ss = _se[p95_days_lag1_4]
    local pp = 2 * normal(-abs(`bb' / `ss'))
    post `results' ("campaign_exclusion") ("`outcome'") ("p95_days_lag1_4")  (`bb') (`ss') (`pp') (e(N))
}

quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if ppml_core_sample == 1 & !inrange(calendar_year, 2020, 2021),  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
post `results' ("period_exclusion") ("drop_2020_2021") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (e(N))

quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if ppml_core_sample == 1 & calendar_year <= 2021,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) nolog
post `results' ("period_exclusion") ("drop_2022_2024") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (e(N))

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster county_id) nolog
post `results' ("inference") ("county_cluster") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (e(N))

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster county_id week_index) nolog
post `results' ("inference") ("county_week_twoway") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (e(N))

postclose `results'

preserve
    use "$GATE2/gate2_model_results.dta", clear
    generate ci_low = b - invnormal(0.975) * se
    generate ci_high = b + invnormal(0.975) * se
    export delimited using "$AUDIT/gate2_model_results.csv", replace

restore

di as result "Gate 2 main estimation, dynamics, placebos, and first robustness set completed."
