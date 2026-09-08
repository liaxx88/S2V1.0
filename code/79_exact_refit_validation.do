version 18.0
set more off
clear
clear matrix
clear mata
set maxvar 12000

use "$GATE2/county_week_ppml_core_v1.dta", clear
merge 1:1 county_id week_start using "$PIVOT/ri_validation_permutations_v1.dta",  keep(match) nogen
assert _N == 192690

quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  separation(fe) tolerance(1e-7) nolog
scalar observed_beta_validation = _b[p95_days_lag1_4]

tempname results
postfile `results' str24 design int repetition double b N rc observed_b  using "$PIVOT/ri_exact_refit_validation_results.dta", replace

foreach design in county_year state_year_block {
    local prefix = cond("`design'" == "county_year", "cy", "sy")
    forvalues repetition = 1/100 {
        local suffix = string(`repetition', "%03.0f")
        local treatment "`prefix'`suffix'"
        capture quietly ppmlhdfe rc_petition_count `treatment',  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  separation(fe) tolerance(1e-7) nolog
        local rc = _rc
        if `rc' {
            post `results' ("`design'") (`repetition') (.) (.) (`rc')  (scalar(observed_beta_validation))
        }
        else {
            post `results' ("`design'") (`repetition') (_b[`treatment'])  (e(N)) (0) (scalar(observed_beta_validation))
        }
        if mod(`repetition', 10) == 0 {
            di as txt "Exact-refit validation `design': `repetition'/100"
        }
    }
}
postclose `results'

use "$PIVOT/ri_exact_refit_validation_results.dta", clear
export delimited using "$AUDIT/ri_exact_refit_validation_results.csv", replace
di as result "Exact-refit RI validation completed."
