version 18.0
set more off

do "$CODE/67_prepare_gate25_ri.do"
capture noisily python script "$CODE/67_gate25_randomization.py", args("$ROOT" "--repetitions" "999")
confirm file "$AUDIT/gate25_randomization_summary.csv"
confirm file "$GATE25/gate25_randomization_manifest.json"

preserve
    import delimited using "$AUDIT/gate25_randomization_inference.csv", clear varnames(1)
    quietly summarize observed_score, meanonly
    local observed = r(mean)
    histogram score if design == "county_year", fraction color(navy%65)  xline(`observed', lcolor(maroon) lwidth(medthick))  xtitle("Null PPML score") ytitle("Fraction")  title("County-year blocks") name(ri_county, replace) graphregion(color(white))
    histogram score if design == "state_year_block", fraction color(forest_green%65)  xline(`observed', lcolor(maroon) lwidth(medthick))  xtitle("Null PPML score") ytitle("Fraction")  title("State-year-block diagnostic") subtitle("Two-sided tail probability = 0.145")  name(ri_state, replace) graphregion(color(white))
    graph export "$FIGURES/FigureG25_1_state_randomization.pdf", replace
    graph combine ri_county ri_state, rows(1)  title("Complete year-block permutation diagnostic") graphregion(color(white))
    graph export "$FIGURES/FigureG25_1_randomization.pdf", replace
restore
