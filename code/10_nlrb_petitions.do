version 18.0

local missing_years
forvalues year = $NLRB_FIRST_YEAR/$NLRB_LAST_YEAR {
    local input "$NLRB_RAW/nlrb_r_cases_`year'_raw.csv"
    capture confirm file `"`input'"'
    if _rc local missing_years "`missing_years' `year'"
}

if strtrim("`missing_years'") != "" {
    di as error "Missing annual official NLRB R-case files for:`missing_years'"
    di as error "Expected names: $NLRB_RAW/nlrb_r_cases_YYYY_raw.csv"
    exit 601
}

tempfile petitions_stack
local first_file = 1

forvalues year = $NLRB_FIRST_YEAR/$NLRB_LAST_YEAR {
    local input "$NLRB_RAW/nlrb_r_cases_`year'_raw.csv"
    di as txt "Importing `input'"

    import delimited using `"`input'"', clear varnames(1) case(lower)  stringcols(_all) bindquotes(strict) maxquotedrows(unlimited)  encoding(UTF-8)

    foreach variable in  casetype region casenumber casename status datefiled dateclosed  reasonclosed city statesterritories employeesonchargepetition  participants union unitsought voters {
        capture confirm variable `variable'
        if _rc {
            di as error "Required column `variable' is missing from `input'."
            exit 111
        }
    }

    rename casetype                    case_group
    rename region                      region_raw
    rename casenumber                  case_number
    rename casename                    employer_name_raw
    rename status                      case_status
    rename datefiled                   date_filed_raw
    rename dateclosed                  date_closed_raw
    rename reasonclosed                reason_closed
    rename statesterritories           state
    rename employeesonchargepetition  employees_on_petition_raw
    rename participants                participants_raw
    rename union                       union_name_raw
    rename unitsought                  unit_sought_raw
    rename voters                      voters_raw

    replace case_number = upper(strtrim(case_number))
    replace case_group  = upper(strtrim(case_group))
    replace state       = upper(strtrim(state))
    replace city        = strtrim(city)

    generate str8 case_subtype = ""
    replace case_subtype = regexs(1) if  regexm(case_number, "^[0-9][0-9]-([A-Z]+)-[0-9]+$")

    count if case_subtype == ""
    if r(N) > 0 {
        di as error "`r(N)' case numbers could not be parsed in `input'."
        exit 459
    }

    keep if case_subtype == "RC"

    generate date_filed  = daily(strtrim(date_filed_raw), "MDY")
    generate date_closed = daily(strtrim(date_closed_raw), "MDY")
    format date_filed date_closed %tdCCYY-NN-DD

    count if missing(date_filed)
    if r(N) > 0 {
        di as error "`r(N)' RC petitions have an invalid filing date in `input'."
        exit 459
    }

    generate employees_on_petition =  real(subinstr(strtrim(employees_on_petition_raw), ",", "", .))
    generate voters = real(subinstr(strtrim(voters_raw), ",", "", .))

    foreach text_variable in  case_group region_raw case_number employer_name_raw case_status  date_filed_raw date_closed_raw reason_closed city state  employees_on_petition_raw participants_raw union_name_raw  unit_sought_raw voters_raw case_subtype {
        replace `text_variable' = subinstr(`text_variable', char(13), " ", .)
        replace `text_variable' = subinstr(`text_variable', char(10), " ", .)
        replace `text_variable' = subinstr(`text_variable', char(9),  " ", .)
        replace `text_variable' = strtrim(itrim(`text_variable'))
    }

    generate filing_year = year(date_filed)
    assert filing_year == `year'

    generate byte main_geo =  state != "" & !inlist(state, "AK", "HI", "PR", "GU", "VI", "AS", "MP")
    label variable main_geo "Contiguous 48 states plus DC"

    generate source_year = `year'
    generate str80 source_file = "nlrb_r_cases_`year'_raw.csv"

    order case_number case_group case_subtype employer_name_raw  date_filed date_closed case_status reason_closed city state  region_raw employees_on_petition participants_raw union_name_raw  unit_sought_raw voters main_geo source_year source_file

    if `first_file' {
        save `petitions_stack', replace
        local first_file = 0
    }
    else {
        append using `petitions_stack'
        save `petitions_stack', replace
    }
}

use `petitions_stack', clear
sort case_number
isid case_number
compress

save "$NLRB_CLEAN/nlrb_petitions_master.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_petitions_master.csv",  replace

keep if main_geo == 1
save "$NLRB_CLEAN/nlrb_petitions_main_sample.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_petitions_main_sample.csv",  replace

di as result "NLRB RC petition master files created successfully."
