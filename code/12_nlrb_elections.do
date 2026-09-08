version 18.0

local missing_years
forvalues year = $NLRB_FIRST_YEAR/$NLRB_LAST_YEAR {
    local input "$NLRB_RAW/nlrb_elections_`year'_raw.csv"
    capture confirm file `"`input'"'
    if _rc local missing_years "`missing_years' `year'"
}

if strtrim("`missing_years'") != "" {
    di as error "Missing annual official NLRB election files for:`missing_years'"
    di as error "Expected names: $NLRB_RAW/nlrb_elections_YYYY_raw.csv"
    exit 601
}

tempfile elections_stack
local first_file = 1

forvalues year = $NLRB_FIRST_YEAR/$NLRB_LAST_YEAR {
    local input "$NLRB_RAW/nlrb_elections_`year'_raw.csv"
    di as txt "Importing `input'"

    import delimited using `"`input'"', clear varnames(1) case(lower)  stringcols(_all) bindquotes(strict) maxquotedrows(unlimited)  encoding(UTF-8)

    foreach variable in  region casenumber casename status datefiled dateclosed reasonclosed  city statesterritories unitid ballottype tallytype tallydate  noofeligiblevoters voidballots laborunion1 votesforlaborunion1  laborunion2 votesforlaborunion2 laborunion3 votesforlaborunion3  votesagainst totalballotscounted runoffrequired challengedballots  challengesaredeterminative uniontocertify votingunitunita  votingunitunitb votingunitunitc votingunitunitd {
        capture confirm variable `variable'
        if _rc {
            di as error "Required column `variable' is missing from `input'."
            exit 111
        }
    }

    rename region                       region_raw
    rename casenumber                   case_number
    rename casename                     employer_name_raw
    rename status                       case_status
    rename datefiled                    date_filed_raw
    rename dateclosed                   date_closed_raw
    rename reasonclosed                 reason_closed
    rename statesterritories            state
    rename unitid                       unit_id
    rename ballottype                   ballot_type
    rename tallytype                    tally_type
    rename tallydate                    tally_date_raw
    rename noofeligiblevoters           eligible_voters_raw
    rename voidballots                  void_ballots_raw
    rename laborunion1                  labor_union_1
    rename votesforlaborunion1          votes_for_union_1_raw
    rename laborunion2                  labor_union_2
    rename votesforlaborunion2          votes_for_union_2_raw
    rename laborunion3                  labor_union_3
    rename votesforlaborunion3          votes_for_union_3_raw
    rename votesagainst                 votes_against_raw
    rename totalballotscounted          total_ballots_counted_raw
    rename runoffrequired               runoff_required
    rename challengedballots            challenged_ballots_raw
    rename challengesaredeterminative   challenges_determinative
    rename uniontocertify               union_to_certify
    rename votingunitunita              voting_unit_a
    rename votingunitunitb              voting_unit_b
    rename votingunitunitc              voting_unit_c
    rename votingunitunitd              voting_unit_d

    foreach text_variable in  region_raw case_number employer_name_raw case_status date_filed_raw  date_closed_raw reason_closed city state unit_id ballot_type  tally_type tally_date_raw eligible_voters_raw void_ballots_raw  labor_union_1 votes_for_union_1_raw labor_union_2  votes_for_union_2_raw labor_union_3 votes_for_union_3_raw  votes_against_raw total_ballots_counted_raw runoff_required  challenged_ballots_raw challenges_determinative union_to_certify  voting_unit_a voting_unit_b voting_unit_c voting_unit_d {
        replace `text_variable' = subinstr(`text_variable', char(13), " ", .)
        replace `text_variable' = subinstr(`text_variable', char(10), " ", .)
        replace `text_variable' = subinstr(`text_variable', char(9),  " ", .)
        replace `text_variable' = strtrim(itrim(`text_variable'))
    }

    replace case_number = upper(case_number)
    replace state       = upper(state)
    replace unit_id     = upper(unit_id)

    generate str8 case_subtype = ""
    replace case_subtype = regexs(1) if  regexm(case_number, "^[0-9][0-9]-([A-Z]+)-[0-9]+$")
    count if case_subtype == ""
    if r(N) > 0 {
        di as error "`r(N)' election case numbers could not be parsed in `input'."
        exit 459
    }

    generate date_filed  = daily(date_filed_raw, "MDY")
    generate date_closed = daily(date_closed_raw, "MDY")
    generate tally_date  = daily(tally_date_raw, "MDY")
    format date_filed date_closed tally_date %tdCCYY-NN-DD

    count if missing(date_filed)
    if r(N) > 0 {
        di as error "`r(N)' election rows have an invalid filing date in `input'."
        exit 459
    }

    generate eligible_voters = real(subinstr(eligible_voters_raw, ",", "", .))
    generate void_ballots = real(subinstr(void_ballots_raw, ",", "", .))
    generate votes_for_union_1 = real(subinstr(votes_for_union_1_raw, ",", "", .))
    generate votes_for_union_2 = real(subinstr(votes_for_union_2_raw, ",", "", .))
    generate votes_for_union_3 = real(subinstr(votes_for_union_3_raw, ",", "", .))
    generate votes_against = real(subinstr(votes_against_raw, ",", "", .))
    generate total_ballots_counted =  real(subinstr(total_ballots_counted_raw, ",", "", .))
    generate challenged_ballots =  real(subinstr(challenged_ballots_raw, ",", "", .))
    egen votes_for_union = rowtotal(votes_for_union_1  votes_for_union_2 votes_for_union_3), missing

    generate double union_vote_share =  votes_for_union / (votes_for_union + votes_against)  if !missing(votes_for_union, votes_against) &  votes_for_union + votes_against > 0
    generate byte union_win_simple = votes_for_union > votes_against  if !missing(votes_for_union, votes_against)
    generate byte certified_from_tally = strtrim(union_to_certify) != ""

    generate filing_year = year(date_filed)
    assert filing_year == `year'

    generate byte main_geo =  state != "" & !inlist(state, "AK", "HI", "PR", "GU", "VI", "AS", "MP")
    generate source_year = `year'
    generate str90 source_file = "nlrb_elections_`year'_raw.csv"

    order case_number case_subtype unit_id employer_name_raw date_filed  tally_date ballot_type tally_type eligible_voters votes_for_union  votes_against total_ballots_counted void_ballots challenged_ballots  union_vote_share union_win_simple certified_from_tally  union_to_certify voting_unit_a voting_unit_b voting_unit_c  voting_unit_d city state region_raw main_geo source_year source_file

    if `first_file' {
        save `elections_stack', replace
        local first_file = 0
    }
    else {
        append using `elections_stack'
        save `elections_stack', replace
    }
}

use `elections_stack', clear
sort case_number unit_id tally_date tally_type ballot_type source_year
by case_number unit_id tally_date tally_type ballot_type:  generate result_sequence = _n
generate str160 election_result_id =  case_number + "|" + cond(unit_id == "", "<MISSING>", unit_id) + "|" +  string(tally_date, "%tdCCYY-NN-DD") + "|" + tally_type + "|" +  ballot_type + "|" + string(result_sequence)
isid election_result_id
by case_number unit_id: generate case_unit_result_rows = _N
generate byte repeated_case_unit = case_unit_result_rows > 1
compress

save "$NLRB_CLEAN/nlrb_elections_master.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_elections_master.csv", replace

keep if case_subtype == "RC"
save "$NLRB_CLEAN/nlrb_elections_rc.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_elections_rc.csv", replace

di as result "NLRB election-result master files created successfully."
