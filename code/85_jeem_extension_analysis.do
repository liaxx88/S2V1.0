version 18.0
clear all
set more off

confirm file "$JEEM_EXT/jeem_extension_county_week_v1.dta"
capture which ppmlhdfe
if _rc exit 111

tempname main timing dose support
postfile `main' str40 family str48 specification str40 variable  double b se p N petition_events counties using  "$JEEM_EXT/jeem_extension_main_results.dta", replace
postfile `timing' str40 specification str40 variable double b se p N  petition_events counties using "$JEEM_EXT/jeem_extension_timing_results.dta", replace
postfile `dose' str40 specification str40 variable double b se p N  petition_events counties using "$JEEM_EXT/jeem_extension_dose_results.dta", replace
postfile `support' str40 dimension str40 group_name double b se p N  petition_events counties using "$JEEM_EXT/jeem_extension_support_results.dta", replace

use "$JEEM_EXT/jeem_extension_county_week_v1.dta", clear
keep if analysis_sample == 1
bysort county_woy_fe: egen double county_woy_petitions = total(rc_petition_count)
keep if county_woy_petitions > 0
bysort state_yearweek_fe: egen double state_week_petitions = total(rc_petition_count)
keep if state_week_petitions > 0
quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_woy_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
quietly summarize rc_petition_count if e(sample), meanonly
local woy_events = r(sum)
egen byte woy_county_tag = tag(county_id) if e(sample)
quietly count if woy_county_tag
local woy_counties = r(N)
drop woy_county_tag
post `main' ("seasonality") ("county_by_week_of_year") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`woy_events') (`woy_counties')

use "$JEEM_EXT/jeem_extension_county_week_v1.dta", clear
keep if primary_esample == 1
assert _N == 192690
quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) d(jeem_fe_sum) nolog
local primary_b = _b[p95_days_lag1_4]
local primary_se = _se[p95_days_lag1_4]
quietly summarize rc_petition_count if e(sample), meanonly
local primary_events = r(sum)
egen byte primary_county_tag = tag(county_id) if e(sample)
quietly count if primary_county_tag
local primary_counties = r(N)
drop primary_county_tag
post `main' ("inference") ("state_cluster") ("p95_days_lag1_4")  (`primary_b') (`primary_se') (2*normal(-abs(`primary_b'/`primary_se')))  (e(N)) (`primary_events') (`primary_counties')

predict double jeem_muhat if e(sample), mu
generate double jeem_base = jeem_muhat / exp(`primary_b' * p95_days_lag1_4)
bysort state_yearweek_fe: egen double sw_muhat = total(jeem_muhat)
bysort state_yearweek_fe: egen double sw_petitions = total(rc_petition_count)
generate double fit_gap = abs(sw_muhat - sw_petitions)
quietly summarize fit_gap, meanonly
local max_fit_gap = r(max)
assert `max_fit_gap' < 0.002

generate double emp_heat = private_emp_lag12 * p95_days_lag1_4
bysort state_yearweek_fe: egen double sw_emp = total(private_emp_lag12)
bysort state_yearweek_fe: egen double sw_emp_heat = total(emp_heat)
generate double sw_heat_mean = sw_emp_heat / sw_emp
generate double emp_heat_sq = private_emp_lag12 * (p95_days_lag1_4 - sw_heat_mean)^2
bysort state_yearweek_fe: egen double sw_emp_heat_sq = total(emp_heat_sq)
generate double sw_heat_sd = sqrt(sw_emp_heat_sq / sw_emp)

generate double cf_muhat = jeem_base * exp(`primary_b' * sw_heat_mean)
bysort state_yearweek_fe: egen double sw_cf_muhat = total(cf_muhat)
generate double p_observed = jeem_muhat / sw_muhat
generate double p_equal_heat = cf_muhat / sw_cf_muhat
generate double abs_share_gap = abs(p_observed - p_equal_heat)
bysort state_yearweek_fe: egen double sw_abs_share_gap = total(abs_share_gap)
generate double reallocation_equiv = 0.5 * sw_petitions * sw_abs_share_gap

keep state_yearweek_fe state_id week_start calendar_year sw_petitions  sw_heat_mean sw_heat_sd reallocation_equiv
bysort state_yearweek_fe: keep if _n == 1
isid state_yearweek_fe
xtile heat_dispersion_decile = sw_heat_sd, nq(10)
generate byte top_heat_dispersion_decile = heat_dispersion_decile == 10
save "$JEEM_EXT/jeem_extension_reallocation_state_week.dta", replace
export delimited using "$AUDIT/jeem_extension_reallocation_state_week.csv", replace

quietly summarize reallocation_equiv, meanonly
local mean_r = r(mean)
local total_r = r(sum)
quietly summarize sw_petitions, meanonly
local total_n = r(sum)
local per100 = 100 * `total_r' / `total_n'
quietly summarize reallocation_equiv if top_heat_dispersion_decile == 1, meanonly
local mean_top_r = r(mean)
quietly summarize sw_petitions if top_heat_dispersion_decile == 1, meanonly
local top_n = r(sum)
quietly summarize reallocation_equiv if top_heat_dispersion_decile == 1, meanonly
local top_r = r(sum)
local top_per100 = 100 * `top_r' / `top_n'
local annual_mean_r = `total_r' / 14

preserve
    collapse (sum) reallocation_equiv sw_petitions, by(calendar_year)
    generate reallocation_per_100 = 100 * reallocation_equiv / sw_petitions
    save "$JEEM_EXT/jeem_extension_reallocation_annual.dta", replace
    export delimited using "$AUDIT/jeem_extension_reallocation_annual.csv", replace
    graph bar (sum) reallocation_equiv, over(calendar_year, label(angle(45)))  ytitle("Petition-equivalents")  title("Fitted reallocation associated with within-state heat dispersion")  subtitle("State-week totals held fixed")  graphregion(color(white)) plotregion(color(white))
    graph export "$FIGURES/FigureJEEM4_reallocation.pdf", replace
restore

preserve
    clear
    set obs 7
    generate str48 metric = ""
    generate double value = .
    replace metric = "mean_state_week_reallocation" in 1
    replace value = `mean_r' in 1
    replace metric = "petition_equivalents_per_100_petitions" in 2
    replace value = `per100' in 2
    replace metric = "mean_top_decile_state_week_reallocation" in 3
    replace value = `mean_top_r' in 3
    replace metric = "top_decile_petition_equivalents_per_100" in 4
    replace value = `top_per100' in 4
    replace metric = "mean_annual_reallocation" in 5
    replace value = `annual_mean_r' in 5
    replace metric = "total_reallocation_2011_2024" in 6
    replace value = `total_r' in 6
    replace metric = "maximum_state_week_fitted_total_gap" in 7
    replace value = `max_fit_gap' in 7
    save "$JEEM_EXT/jeem_extension_reallocation_summary.dta", replace
    export delimited using "$AUDIT/jeem_extension_reallocation_summary.csv", replace
restore

use "$JEEM_EXT/jeem_extension_county_week_v1.dta", clear
keep if primary_esample == 1
quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id week_index) separation(fe) tolerance(1e-8) nolog
quietly summarize rc_petition_count if e(sample), meanonly
local tw_events = r(sum)
egen byte tw_county_tag = tag(county_id) if e(sample)
quietly count if tw_county_tag
local tw_counties = r(N)
drop tw_county_tag
post `main' ("inference") ("state_week_two_way_cluster") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`tw_events') (`tw_counties')

use "$JEEM_EXT/jeem_extension_county_week_v1.dta", clear
local pre p95_days_lag13_16 p95_days_lag9_12 p95_days_lag5_8 p95_days_lag1_4
local future p95_days_future1_4 p95_days_future5_8  p95_days_future9_12 p95_days_future13_16
quietly ppmlhdfe rc_petition_count `pre' `future'  if ppml_core_sample == 1 & !missing(p95_days_future13_16),  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
quietly summarize rc_petition_count if e(sample), meanonly
local timing_events = r(sum)
egen byte timing_county_tag = tag(county_id) if e(sample)
quietly count if timing_county_tag
local timing_counties = r(N)
drop timing_county_tag
foreach variable of local pre {
    post `timing' ("joint_leads_lags") ("`variable'")  (_b[`variable']) (_se[`variable'])  (2*normal(-abs(_b[`variable']/_se[`variable'])))  (e(N)) (`timing_events') (`timing_counties')
}
foreach variable of local future {
    post `timing' ("joint_leads_lags") ("`variable'")  (_b[`variable']) (_se[`variable'])  (2*normal(-abs(_b[`variable']/_se[`variable'])))  (e(N)) (`timing_events') (`timing_counties')
}
quietly test `future'
post `timing' ("joint_leads_lags") ("joint_future_wald")  (r(chi2)) (.) (r(p)) (e(N)) (`timing_events') (`timing_counties')

use "$JEEM_EXT/jeem_extension_county_week_v1.dta", clear
keep if primary_esample == 1
generate byte heat_1_2 = inrange(p95_days_lag1_4, 1, 2)
generate byte heat_3_4 = inrange(p95_days_lag1_4, 3, 4)
generate byte heat_5_7 = inrange(p95_days_lag1_4, 5, 7)
generate byte heat_8plus = p95_days_lag1_4 >= 8
quietly ppmlhdfe rc_petition_count heat_1_2 heat_3_4 heat_5_7 heat_8plus,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
quietly summarize rc_petition_count if e(sample), meanonly
local dose_events = r(sum)
egen byte dose_county_tag = tag(county_id) if e(sample)
quietly count if dose_county_tag
local dose_counties = r(N)
drop dose_county_tag
foreach variable in heat_1_2 heat_3_4 heat_5_7 heat_8plus {
    post `dose' ("primary_esample") ("`variable'")  (_b[`variable']) (_se[`variable'])  (2*normal(-abs(_b[`variable']/_se[`variable'])))  (e(N)) (`dose_events') (`dose_counties')
}

use "$JEEM_EXT/jeem_extension_county_week_v1.dta", clear
foreach metro in 0 1 {
    quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if ppml_core_sample == 1 & metro2013 == `metro',  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    quietly summarize rc_petition_count if e(sample), meanonly
    local subgroup_events = r(sum)
    egen byte subgroup_county_tag = tag(county_id) if e(sample)
    quietly count if subgroup_county_tag
    local subgroup_counties = r(N)
    drop subgroup_county_tag
    local label = cond(`metro' == 1, "Metro", "Nonmetro")
    post `support' ("metro2013") ("`label'")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`subgroup_events') (`subgroup_counties')
}
forvalues q = 1/4 {
    quietly ppmlhdfe rc_petition_count p95_days_lag1_4  if ppml_core_sample == 1 & private_emp_2010_q == `q',  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    quietly summarize rc_petition_count if e(sample), meanonly
    local subgroup_events = r(sum)
    egen byte subgroup_county_tag = tag(county_id) if e(sample)
    quietly count if subgroup_county_tag
    local subgroup_counties = r(N)
    drop subgroup_county_tag
    post `support' ("private_emp_2010_quartile") ("Q`q'")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (e(N)) (`subgroup_events') (`subgroup_counties')
}

postclose `main'
postclose `timing'
postclose `dose'
postclose `support'

foreach file in main timing dose support {
    preserve
        use "$JEEM_EXT/jeem_extension_`file'_results.dta", clear
        generate double ci_low = b - invnormal(0.975) * se if !missing(se)
        generate double ci_high = b + invnormal(0.975) * se if !missing(se)
        export delimited using "$AUDIT/jeem_extension_`file'_results.csv", replace
    restore
}

use "$JEEM_EXT/jeem_extension_timing_results.dta", clear
drop if variable == "joint_future_wald"
generate byte order = .
replace order = 1 if variable == "p95_days_lag13_16"
replace order = 2 if variable == "p95_days_lag9_12"
replace order = 3 if variable == "p95_days_lag5_8"
replace order = 4 if variable == "p95_days_lag1_4"
replace order = 5 if variable == "p95_days_future1_4"
replace order = 6 if variable == "p95_days_future5_8"
replace order = 7 if variable == "p95_days_future9_12"
replace order = 8 if variable == "p95_days_future13_16"
generate double ci_low = b - invttail(47, 0.025) * se
generate double ci_high = b + invttail(47, 0.025) * se
sort order
twoway (rcap ci_low ci_high order, lcolor(navy))  (scatter b order, mcolor(navy) msymbol(O)),  xline(4.5, lcolor(gs10) lpattern(dash)) yline(0, lcolor(gs8))  xlabel(1 "-16--13" 2 "-12--9" 3 "-8--5" 4 "-4--1"  5 "+1--4" 6 "+5--8" 7 "+9--12" 8 "+13--16", angle(35))  xtitle("Weeks relative to filing week") ytitle("Conditional PPML coefficient")  title("Pre- and post-filing heat timing")  subtitle("Week zero excluded; 95% state-clustered CI, t(47) reference")  legend(off) graphregion(color(white)) plotregion(color(white))
graph export "$FIGURES/FigureJEEM2_leads_lags.pdf", replace

use "$JEEM_EXT/jeem_extension_dose_results.dta", clear
generate byte order = _n
generate double ci_low = b - invttail(47, 0.025) * se
generate double ci_high = b + invttail(47, 0.025) * se
twoway (rcap ci_low ci_high order, lcolor(forest_green))  (scatter b order, mcolor(forest_green) msymbol(O)),  yline(0, lcolor(gs8)) xlabel(1 "1--2" 2 "3--4" 3 "5--7" 4 "8+")  xtitle("P95 heat days in weeks 1--4 (reference: 0)")  ytitle("Conditional PPML coefficient") title("Heat dose response")  subtitle("Primary PPML support; 95% state-clustered CI, t(47) reference")  legend(off) graphregion(color(white)) plotregion(color(white))
graph export "$FIGURES/FigureJEEM3_dose_response.pdf", replace

clear
set obs 1
generate str32 method = "Conley spatial HAC"
generate str24 status = "NOT IMPLEMENTED"
generate str160 reason = "No project-local nonlinear HDFE Conley estimator that preserves the primary point estimate and sample; state/week two-way clustering is reported."
export delimited using "$AUDIT/jeem_extension_spatial_hac_status.csv", replace

di as result "Bounded JEEM extension estimates and fitted magnitudes completed."
