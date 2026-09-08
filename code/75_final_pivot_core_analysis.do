version 18.0
set more off

foreach input in  "$PIVOT/state_week_dynamic_v1.dta"  "$PIVOT/progression_common_support_v1.dta"  "$PIVOT/county_week_exposure_ppml_core_v1.dta" {
    confirm file `"`input'"'
}
capture which ppmlhdfe
if _rc exit 111

tempname dyn common exposure
postfile `dyn' str40 family str48 specification str40 variable  double b se p N outcome_count units using "$PIVOT/state_week_dynamic_results.dta", replace
postfile `common' str40 family str48 specification str40 outcome  double b se p N outcome_count units using "$PIVOT/common_support_progression_results.dta", replace
postfile `exposure' str40 family str48 specification str40 variable  double b se p N outcome_count counties using "$PIVOT/county_exposure_results.dta", replace

use "$PIVOT/state_week_dynamic_v1.dta", clear
rename state_p95_days_lag1_4 h1_4
rename state_p95_days_lag5_8 h5_8
rename state_p95_days_lag9_12 h9_12
rename state_p95_days_lag13_16 h13_16
rename state_p95_days_lag17_20 h17_20
rename state_p95_days_lag21_24 h21_24

quietly ppmlhdfe rc_petition_count h1_4 h5_8 h9_12 h13_16 h17_20 h21_24,  absorb(state_month_fe national_week_fe) offset(log_state_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
estimates store pivot_state_dynamic
local state_N = e(N)
quietly summarize rc_petition_count if e(sample), meanonly
local state_total = r(sum)
egen byte state_tag = tag(state_id) if e(sample)
quietly count if state_tag
local state_units = r(N)
drop state_tag
foreach variable in h1_4 h5_8 h9_12 h13_16 h17_20 h21_24 {
    post `dyn' ("state_week_ppml") ("distributed_lag_1_24") ("`variable'")  (_b[`variable']) (_se[`variable'])  (2*normal(-abs(_b[`variable']/_se[`variable'])))  (`state_N') (`state_total') (`state_units')
}
quietly lincom h1_4 + h5_8 + h9_12 + h13_16 + h17_20 + h21_24
post `dyn' ("state_week_ppml") ("distributed_lag_1_24") ("coefficient_sum_1_24")  (r(estimate)) (r(se)) (r(p)) (`state_N') (`state_total') (`state_units')
quietly test h1_4 h5_8 h9_12 h13_16 h17_20 h21_24
post `dyn' ("state_week_ppml") ("distributed_lag_1_24") ("joint_wald_all_zero")  (r(chi2)) (.) (r(p)) (`state_N') (`state_total') (`state_units')

use "$PIVOT/progression_common_support_v1.dta", clear
local primary_outcomes rc_petition_count election_180_count certified_rep_365_count failed_180_count
foreach outcome of local primary_outcomes {
    quietly ppmlhdfe `outcome' p95_days_lag1_4 if common_progression_support == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    local outcome_N = e(N)
    quietly summarize `outcome' if e(sample), meanonly
    local outcome_total = r(sum)
    egen byte county_tag = tag(county_id) if e(sample)
    quietly count if county_tag
    local outcome_units = r(N)
    drop county_tag
    post `common' ("county_week_ppml") ("primary_common_support") ("`outcome'")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (`outcome_N') (`outcome_total') (`outcome_units')
}

quietly ppmlhdfe certified_tally_proxy_365_count p95_days_lag1_4  if common_progression_support == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
local tally_common_N = e(N)
quietly summarize certified_tally_proxy_365_count if e(sample), meanonly
local tally_common_total = r(sum)
egen byte county_tag = tag(county_id) if e(sample)
quietly count if county_tag
local tally_common_units = r(N)
drop county_tag
post `common' ("county_week_ppml") ("primary_common_support")  ("certified_tally_proxy_365_count") (_b[p95_days_lag1_4])  (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (`tally_common_N') (`tally_common_total') (`tally_common_units')

quietly ppmlhdfe certified_tally_proxy_365_count p95_days_lag1_4 if tally_support == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
local tally_own_N = e(N)
quietly summarize certified_tally_proxy_365_count if e(sample), meanonly
local tally_own_total = r(sum)
egen byte county_tag = tag(county_id) if e(sample)
quietly count if county_tag
local tally_own_units = r(N)
drop county_tag
post `common' ("county_week_ppml") ("tally_own_support")  ("certified_tally_proxy_365_count") (_b[p95_days_lag1_4])  (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (`tally_own_N') (`tally_own_total') (`tally_own_units')

use "$PIVOT/county_week_exposure_ppml_core_v1.dta", clear
generate double hx_nlra = p95_days_lag1_4 * z_pred_heat_nlra_2010
generate double hx_broad = p95_days_lag1_4 * z_pred_heat_broad_2010
generate double hx_thermal = p95_days_lag1_4 * z_pred_thermal_nlra_2010
generate double hx_naics3 = p95_days_lag1_4 * z_pred_heat_naics3_2010
generate double hx_agriculture = p95_days_lag1_4 * z_agriculture_share_2010
generate double hx_logemp2010 = p95_days_lag1_4 * z_log_private_emp_2010
generate double hx_metro = p95_days_lag1_4 * metro2013

local specifications  primary_nlra  primary_controls  broad_private  thermal_context  naics3_published  agriculture_placebo
foreach specification of local specifications {
    if "`specification'" == "primary_nlra" {
        local rhs p95_days_lag1_4 hx_nlra
        local mainvar hx_nlra
        local condition exposure_primary_eligible == 1
    }
    else if "`specification'" == "primary_controls" {
        local rhs p95_days_lag1_4 hx_nlra hx_metro hx_logemp2010
        local mainvar hx_nlra
        local condition exposure_primary_eligible == 1 & !missing(metro2013)
    }
    else if "`specification'" == "broad_private" {
        local rhs p95_days_lag1_4 hx_broad
        local mainvar hx_broad
        local condition exposure_primary_eligible == 1
    }
    else if "`specification'" == "thermal_context" {
        local rhs p95_days_lag1_4 hx_thermal
        local mainvar hx_thermal
        local condition exposure_primary_eligible == 1
    }
    else if "`specification'" == "naics3_published" {
        local rhs p95_days_lag1_4 hx_naics3
        local mainvar hx_naics3
        local condition exposure_naics3_eligible == 1
    }
    else if "`specification'" == "agriculture_placebo" {
        local rhs p95_days_lag1_4 hx_agriculture hx_metro hx_logemp2010
        local mainvar hx_agriculture
        local condition exposure_primary_eligible == 1 & !missing(metro2013)
    }
    quietly ppmlhdfe rc_petition_count `rhs' if `condition',  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    local exp_N = e(N)
    quietly summarize rc_petition_count if e(sample), meanonly
    local exp_total = r(sum)
    egen byte county_tag = tag(county_id) if e(sample)
    quietly count if county_tag
    local exp_counties = r(N)
    drop county_tag
    foreach variable of local rhs {
        post `exposure' ("county_week_ppml") ("`specification'") ("`variable'")  (_b[`variable']) (_se[`variable'])  (2*normal(-abs(_b[`variable']/_se[`variable'])))  (`exp_N') (`exp_total') (`exp_counties')
    }
}

postclose `dyn'
postclose `common'
postclose `exposure'

foreach file in state_week_dynamic_results common_support_progression_results county_exposure_results {
    preserve
        use "$PIVOT/`file'.dta", clear
        generate ci_low = b - invnormal(0.975)*se if !missing(se)
        generate ci_high = b + invnormal(0.975)*se if !missing(se)
        export delimited using "$AUDIT/final_pivot_`file'.csv", replace
    restore
}

use "$PIVOT/state_week_dynamic_results.dta", clear
keep if inlist(variable, "h1_4", "h5_8", "h9_12", "h13_16", "h17_20", "h21_24")
generate byte order = _n
generate ci_low = b - invttail(47, 0.025)*se
generate ci_high = b + invttail(47, 0.025)*se
twoway (rcap ci_low ci_high order, lcolor(maroon))  (scatter b order, mcolor(maroon) msymbol(O)),  yline(0, lcolor(gs8)) xlabel(1 "1--4" 2 "5--8" 3 "9--12"  4 "13--16" 5 "17--20" 6 "21--24")  xtitle("Weeks before filing") ytitle("State-week PPML coefficient")  title("Aggregate state-week distributed lags") legend(off) graphregion(color(white))
graph export "$FIGURES/FigurePivotA_state_week_dynamics.pdf", replace

di as result "Final-pivot stages A--C completed."
