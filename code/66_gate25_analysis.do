version 18.0
set more off

foreach input in  "$GATE2/county_week_analysis_v1.dta"  "$GATE2/county_week_ppml_core_v1.dta"  "$GATE25/state_week_incidence_v1.dta" {
    confirm file `"`input'"'
}
capture which ppmlhdfe
if _rc exit 111
capture which reghdfe
if _rc exit 111

tempname stages decomposition results
postfile `stages' byte stage_order str64 specification double initial_n retained_n  retained_pct positive_outcome_rows petition_count counties  using "$GATE25/gate25_separation_stages.dta", replace
postfile `decomposition' byte step_order str64 exclusion_reason double excluded_n  using "$GATE25/gate25_separation_decomposition.dta", replace
postfile `results' str36 family str48 specification str32 outcome str40 variable  double b se p N positive_outcome_rows counties using "$GATE25/gate25_model_results.dta", replace

use "$GATE2/county_week_analysis_v1.dta", clear
keep if analysis_sample == 1
local initial_n = _N
assert `initial_n' == 2260083

quietly ppmlhdfe rc_petition_count p95_days_lag1_4, vce(cluster state_id) nolog
generate byte esample_heatonly = e(sample)
quietly count if esample_heatonly
local n1 = r(N)
quietly count if esample_heatonly & rc_petition_count > 0
local pos1 = r(N)
quietly summarize rc_petition_count if esample_heatonly, meanonly
local petitions1 = r(sum)
egen byte county_tag1 = tag(county_id) if esample_heatonly
quietly count if county_tag1
local counties1 = r(N)
post `stages' (1) ("Analysis panel / heat only") (`initial_n') (`n1')  (100*`n1'/`initial_n') (`pos1') (`petitions1') (`counties1')

quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe) vce(cluster state_id) nolog
generate byte esample_cm = e(sample)
quietly count if esample_cm
local n2 = r(N)
quietly count if esample_cm & rc_petition_count > 0
local pos2 = r(N)
quietly summarize rc_petition_count if esample_cm, meanonly
local petitions2 = r(sum)
egen byte county_tag2 = tag(county_id) if esample_cm
quietly count if county_tag2
local counties2 = r(N)
post `stages' (2) ("County x month-of-year FE") (`initial_n') (`n2')  (100*`n2'/`initial_n') (`pos2') (`petitions2') (`counties2')
local drop_cm = `n1' - `n2'

use "$GATE2/county_week_ppml_core_v1.dta", clear
local prefilter_n = _N
bysort county_month_fe: generate long county_month_core_n = _N
bysort state_yearweek_fe: generate long state_week_core_n = _N
generate byte singleton_candidate = county_month_core_n == 1 | state_week_core_n == 1

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) vce(cluster state_id)  separation(fe) tolerance(1e-8) nolog
generate byte esample_twofe = e(sample)
local n3 = e(N)
quietly count if esample_twofe & rc_petition_count > 0
local pos3 = r(N)
quietly summarize rc_petition_count if esample_twofe, meanonly
local petitions3 = r(sum)
egen byte county_tag3 = tag(county_id) if esample_twofe
quietly count if county_tag3
local counties3 = r(N)
quietly count if !esample_twofe & singleton_candidate
local singleton_removed = r(N)
quietly count if !esample_twofe & !singleton_candidate
local numerical_removed = r(N)
post `stages' (3) ("Plus state x exact-week FE") (`initial_n') (`n3')  (100*`n3'/`initial_n') (`pos3') (`petitions3') (`counties3')

preserve
    keep if esample_twofe
    keep county_fips week_start
    isid county_fips week_start
    save "$GATE25/gate25_final_esample_keys.dta", replace
    export delimited using "$AUDIT/gate25_final_esample_keys.csv", replace
restore

quietly ppmlhdfe rc_petition_count p95_days_lag1_4 if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
generate byte esample_offset = e(sample)
local n4 = e(N)
quietly count if esample_offset & rc_petition_count > 0
local pos4 = r(N)
quietly summarize rc_petition_count if esample_offset, meanonly
local petitions4 = r(sum)
egen byte county_tag4 = tag(county_id) if esample_offset
quietly count if county_tag4
local counties4 = r(N)
post `stages' (4) ("Plus lag-12-month employment offset") (`initial_n') (`n4')  (100*`n4'/`initial_n') (`pos4') (`petitions4') (`counties4')

local drop_sw = `n2' - `prefilter_n'
post `decomposition' (1) ("All-zero county x month-of-year groups") (`drop_cm')
post `decomposition' (2) ("All-zero state x exact-week groups after county support") (`drop_sw')
post `decomposition' (3) ("Singleton observations removed by PPMLHDFE") (`singleton_removed')
post `decomposition' (4) ("Additional numerical separation") (`numerical_removed')

post `results' ("county_week_ppml") ("primary") ("rc_petition_count")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (e(N))  (`pos4') (`counties4')
estimates store g25_primary

foreach window in 1_16 1_24 {
    local variable "p95_days_cumulative_`window'"
    quietly ppmlhdfe rc_petition_count `variable' if ppml_core_sample == 1,  absorb(county_month_fe state_yearweek_fe) offset(log_private_emp_lag12)  vce(cluster state_id) separation(fe) tolerance(1e-8) nolog
    quietly count if e(sample) & rc_petition_count > 0
    local pos = r(N)
    egen byte county_tag_window = tag(county_id) if e(sample)
    quietly count if county_tag_window
    local ncounty = r(N)
    drop county_tag_window
    post `results' ("single_window_ppml") ("window_`window'") ("rc_petition_count")  ("`variable'") (_b[`variable']) (_se[`variable'])  (2*normal(-abs(_b[`variable']/_se[`variable']))) (e(N)) (`pos') (`ncounty')
    estimates store g25_window_`window'
}

use "$GATE25/state_week_incidence_v1.dta", clear
rename state_p95_days_lag1_4 p95_days_lag1_4
quietly ppmlhdfe rc_petition_count p95_days_lag1_4,  absorb(state_month_fe national_week_fe) offset(log_state_private_emp_lag12)  vce(cluster state_id) nolog
local state_n = e(N)
quietly count if e(sample) & rc_petition_count > 0
local state_pos = r(N)
egen byte state_tag = tag(state_id) if e(sample)
quietly count if state_tag
local nstates = r(N)
post `results' ("state_week_ppml") ("aggregate_incidence") ("rc_petition_count")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (`state_n')  (`state_pos') (`nstates')
estimates store g25_stateweek

use "$GATE2/county_week_analysis_v1.dta", clear
keep if analysis_sample == 1
egen long national_week_fe = group(week_start)
egen long state_month_fe = group(state_id calendar_month)

quietly reghdfe any_rc_petition p95_days_lag1_4,  absorb(county_id national_week_fe state_month_fe) vce(cluster state_id) compact
local lpm_n = e(N)
quietly count if e(sample) & any_rc_petition > 0
local lpm_pos = r(N)
egen byte county_tag_lpm = tag(county_id) if e(sample)
quietly count if county_tag_lpm
local lpm_counties = r(N)
post `results' ("full_panel_linear") ("any_petition_lpm") ("any_rc_petition")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (`lpm_n')  (`lpm_pos') (`lpm_counties')
estimates store g25_lpm

quietly reghdfe rc_petition_count p95_days_lag1_4,  absorb(county_id national_week_fe state_month_fe) vce(cluster state_id) compact
local ols_n = e(N)
quietly count if e(sample) & rc_petition_count > 0
local ols_pos = r(N)
egen byte county_tag_ols = tag(county_id) if e(sample)
quietly count if county_tag_ols
local ols_counties = r(N)
post `results' ("full_panel_linear") ("petition_count_ols") ("rc_petition_count")  ("p95_days_lag1_4") (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4]))) (`ols_n')  (`ols_pos') (`ols_counties')
estimates store g25_ols

quietly reghdfe any_rc_petition p95_days_lag1_4,  absorb(county_month_fe state_yearweek_fe) vce(cluster state_id)  keepsingletons compact
assert e(N) == 2260083
local samefe_lpm_n = e(N)
quietly count if e(sample) & any_rc_petition > 0
local samefe_lpm_pos = r(N)
egen byte county_tag_samefe_lpm = tag(county_id) if e(sample)
quietly count if county_tag_samefe_lpm
local samefe_lpm_counties = r(N)
drop county_tag_samefe_lpm
post `results' ("full_panel_same_fe_linear") ("any_petition_lpm_same_fe")  ("any_rc_petition") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (`samefe_lpm_n') (`samefe_lpm_pos') (`samefe_lpm_counties')
estimates store g25_samefe_lpm

quietly reghdfe rc_petition_count p95_days_lag1_4,  absorb(county_month_fe state_yearweek_fe) vce(cluster state_id)  keepsingletons compact
assert e(N) == 2260083
local samefe_ols_n = e(N)
quietly count if e(sample) & rc_petition_count > 0
local samefe_ols_pos = r(N)
egen byte county_tag_samefe_ols = tag(county_id) if e(sample)
quietly count if county_tag_samefe_ols
local samefe_ols_counties = r(N)
drop county_tag_samefe_ols
post `results' ("full_panel_same_fe_linear") ("petition_count_ols_same_fe")  ("rc_petition_count") ("p95_days_lag1_4")  (_b[p95_days_lag1_4]) (_se[p95_days_lag1_4])  (2*normal(-abs(_b[p95_days_lag1_4]/_se[p95_days_lag1_4])))  (`samefe_ols_n') (`samefe_ols_pos') (`samefe_ols_counties')
estimates store g25_samefe_ols

postclose `stages'
postclose `decomposition'
postclose `results'

preserve
    use "$GATE25/gate25_separation_stages.dta", clear
    export delimited using "$AUDIT/gate25_separation_audit.csv", replace
    file open table using "$TABLES/TableG25_1.tex", write replace text
    file write table "\begin{tabular}{lrrrrr}" _n "\toprule" _n
    file write table "Specification & Retained N & Retained (\%) & Positive weeks & Petition events & Counties \\" _n
    file write table "\midrule" _n
    forvalues i=1/`=_N' {
        file write table `"`=specification[`i']' & `=string(retained_n[`i'],"%12.0fc")' & "'  `"`=string(retained_pct[`i'],"%6.2f")' & `=string(positive_outcome_rows[`i'],"%10.0fc")' & "'  `"`=string(petition_count[`i'],"%10.0fc")' & `=string(counties[`i'],"%8.0fc")' \\"' _n
    }
    file write table "\bottomrule" _n "\end{tabular}" _n
    file close table
restore

preserve
    use "$GATE25/gate25_separation_decomposition.dta", clear
    export delimited using "$AUDIT/gate25_separation_decomposition.csv", replace
restore

preserve
    use "$GATE25/gate25_model_results.dta", clear
    generate ci_low = b - invnormal(0.975)*se
    generate ci_high = b + invnormal(0.975)*se
    export delimited using "$AUDIT/gate25_model_results.csv", replace
restore

estimates restore g25_primary
estadd local CountyMOY "Yes", replace
estadd local StateWeek "Yes", replace
estadd local StateMOY "No", replace
estadd local NationalWeek "No", replace
estadd local CountyFE "No", replace
estadd local EmpOffset "Yes", replace

di as result "Gate 2.5 separation, incidence, full-panel, and window analyses completed."
