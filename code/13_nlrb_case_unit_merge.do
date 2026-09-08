version 18.0

foreach input in  "$NLRB_CLEAN/nlrb_petitions_master.dta"  "$NLRB_CLEAN/nlrb_elections_rc.dta" {
    capture confirm file `"`input'"'
    if _rc {
        di as error "Missing required clean input: `input'"
        exit 601
    }
}

tempfile unit_summary case_summary

use "$NLRB_CLEAN/nlrb_elections_rc.dta", clear
generate double tally_date_sort = cond(missing(tally_date), -100000, tally_date)
sort case_number unit_id tally_date_sort tally_type ballot_type result_sequence

by case_number unit_id: generate election_result_rows = _N
by case_number unit_id: egen first_tally_date = min(tally_date)
by case_number unit_id: egen last_tally_date = max(tally_date)
format first_tally_date last_tally_date %tdCCYY-NN-DD
by case_number unit_id: generate byte latest_result = _n == _N
keep if latest_result

rename tally_date                  latest_tally_date
rename tally_type                  latest_tally_type
rename ballot_type                 latest_ballot_type
rename eligible_voters             latest_eligible_voters
rename votes_for_union             latest_votes_for_union
rename votes_against               latest_votes_against
rename total_ballots_counted       latest_total_ballots_counted
rename challenged_ballots          latest_challenged_ballots
rename void_ballots                latest_void_ballots
rename union_vote_share            latest_union_vote_share
rename union_win_simple            latest_union_win_simple
rename certified_from_tally        latest_certified_from_tally
rename union_to_certify            latest_union_to_certify

keep case_number unit_id election_result_rows first_tally_date  last_tally_date latest_tally_date latest_tally_type latest_ballot_type  latest_eligible_voters latest_votes_for_union latest_votes_against  latest_total_ballots_counted latest_challenged_ballots  latest_void_ballots latest_union_vote_share latest_union_win_simple  latest_certified_from_tally latest_union_to_certify voting_unit_a  voting_unit_b voting_unit_c voting_unit_d
isid case_number unit_id
save `unit_summary', replace

preserve
    generate byte one_unit = 1
    collapse (sum) election_unit_count=one_unit  election_result_rows latest_eligible_voters latest_votes_for_union  latest_votes_against latest_total_ballots_counted  latest_challenged_ballots latest_void_ballots  (min) first_tally_date  (max) last_tally_date latest_certified_from_tally, by(case_number)

    generate double union_vote_share = latest_votes_for_union /  (latest_votes_for_union + latest_votes_against)  if latest_votes_for_union + latest_votes_against > 0
    generate byte union_win_simple =  latest_votes_for_union > latest_votes_against  if !missing(latest_votes_for_union, latest_votes_against)
    rename latest_certified_from_tally certified
    isid case_number
    save `case_summary', replace
restore

use "$NLRB_CLEAN/nlrb_petitions_master.dta", clear
merge 1:m case_number using `unit_summary', keep(master match) generate(_merge_unit)
generate byte election_held = _merge_unit == 3
generate byte withdrawn = regexm(lower(reason_closed), "withdraw")
generate byte dismissed = regexm(lower(reason_closed), "dismiss")
generate days_to_election = first_tally_date - date_filed if election_held
format days_to_election %9.0g
drop _merge_unit
sort case_number unit_id
compress
save "$NLRB_CLEAN/nlrb_case_unit_master.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_case_unit_master.csv", replace

use "$NLRB_CLEAN/nlrb_petitions_master.dta", clear
merge 1:1 case_number using `case_summary', keep(master match) generate(_merge_case)
generate byte election_held = _merge_case == 3
generate byte withdrawn = regexm(lower(reason_closed), "withdraw")
generate byte dismissed = regexm(lower(reason_closed), "dismiss")
generate days_to_election = first_tally_date - date_filed if election_held
replace election_unit_count = 0 if !election_held
replace election_result_rows = 0 if !election_held
drop _merge_case
sort case_number
isid case_number
compress
save "$NLRB_CLEAN/nlrb_petition_progression.dta", replace
export delimited using "$NLRB_CLEAN/nlrb_petition_progression.csv", replace

count
local n_petitions = r(N)
count if election_held
local n_elections = r(N)
di as result "Matched `n_elections' of `n_petitions' RC petitions to an official election result."
di as result "NLRB petition progression and case-unit files created successfully."
