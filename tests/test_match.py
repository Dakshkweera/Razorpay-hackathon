"""Matching, and the refusals that matter more than the matches.

The zero-AI baseline is asserted here so that the LLM stages, when they land, are
measured as a delta over a number that is written down rather than remembered.
"""

from __future__ import annotations

import pytest

from recon.evaluate.score import load_truth, score
from recon.generate.build import build
from recon.generate.writer import write_dataset
from recon.match.rules import MATCH_COMMIT_THRESHOLD, RULE_CONFIDENCE
from recon.narration.extract import extract
from recon.model import BankRow
from recon.money import Paise
from recon.pipeline import run
from recon.report import CaseStatus, ExceptionKind, LlmMode, MatchOrigin, MatchRule


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("matching")
    write_dataset(build(seed=42), directory)
    return directory


@pytest.fixture(scope="module")
def report(data_dir):
    # Explicit and offline: this suite is the zero-AI baseline, not whatever LlmMode
    # the ambient repo happens to auto-resolve to.
    return run(data_dir, llm_mode=LlmMode.STUB)


@pytest.fixture(scope="module")
def evaluation(report, data_dir):
    return score(report, load_truth(data_dir / "truth.json"))


@pytest.fixture(scope="module")
def batches(report):
    return {batch.settlement_id: batch for batch in report.batches}


# --------------------------------------------------------------------------- #
# The claim the whole submission rests on
# --------------------------------------------------------------------------- #

def test_no_false_matches(evaluation):
    assert evaluation.false_matches == 0


def test_no_false_cause_attributions(evaluation):
    assert evaluation.false_cause_attributions == 0


def test_no_case_fails(evaluation):
    failed = [case for case in evaluation.cases if case.status is CaseStatus.FAIL]
    assert failed == [], [f"case {case.number}: {case.actual}" for case in failed]


def test_the_baseline_is_below_a_hundred_percent(report):
    """A system claiming perfection invites disbelief, and would be lying here anyway."""
    assert 0 < report.scoreboard.matched_deterministic.pct < 100


def test_zero_ai_baseline_is_recorded(report):
    """The number stage 3 alone reaches. Update deliberately.

    This fixture runs with the LLM stub active (see the ``report`` fixture above),
    and the count still comes out identical to the no-AI baseline: every corrupted
    reference in this dataset is corrupted past what an honest model can recover
    (see ``test_a_mangled_reference_is_not_invented``), so nothing here should be
    matched by inference. If this assertion ever needs to change because a real
    inference match legitimately appears, that is the AI delta this project exists
    to measure - change it deliberately, with a reason.
    """
    assert report.scoreboard.matched_deterministic.n == 6
    assert report.scoreboard.matched_inference.n == 0
    assert report.scoreboard.unmatched.n == 3


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #

def test_every_batch_matched_by_the_rule_it_was_planted_for(report, data_dir):
    truth = load_truth(data_dir / "truth.json")
    planted = {batch.settlement_id: batch.expected_rule for batch in truth.batches}
    for batch in report.batches:
        expected = planted[batch.settlement_id]
        actual = None if batch.match.rule is MatchRule.NONE else batch.match.rule.value
        assert actual == expected, batch.settlement_id


def test_committed_matches_clear_the_threshold(report):
    for batch in report.batches:
        if batch.match.rule is not MatchRule.NONE:
            assert batch.match.confidence >= MATCH_COMMIT_THRESHOLD, batch.settlement_id


def test_rule_confidences_are_ordered(report):
    assert (
        RULE_CONFIDENCE[MatchRule.R1]
        >= RULE_CONFIDENCE[MatchRule.R3]
        > RULE_CONFIDENCE[MatchRule.R4]
    )
    assert RULE_CONFIDENCE[MatchRule.R4] == MATCH_COMMIT_THRESHOLD


def test_no_bank_line_is_claimed_twice(report):
    claimed = [batch.bank_ref for batch in report.batches if batch.bank_ref]
    assert len(claimed) == len(set(claimed))


def test_matched_batches_carry_the_credit_they_matched(report):
    for batch in report.batches:
        if batch.match.rule is MatchRule.NONE:
            assert batch.bank_credit is None
        else:
            assert batch.bank_credit is not None
            assert int(batch.headline_gap) == int(batch.orders_expected) - int(batch.bank_credit)


def test_all_matches_are_deterministic_on_this_dataset(report):
    """See ``test_zero_ai_baseline_is_recorded``: the LLM stub is active here too."""
    for batch in report.batches:
        if batch.match.rule is not MatchRule.NONE:
            assert batch.match.origin is MatchOrigin.DETERMINISTIC


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #

def test_ambiguity_produces_one_exception_per_batch_not_one_per_rule(report):
    """A batch refused by R3 and again by R4 is one problem, not two."""
    ambiguous = [
        exception
        for exception in report.exceptions
        if exception.kind is ExceptionKind.AMBIGUOUS_MATCH
    ]
    assert len(ambiguous) == 2
    assert len({exception.settlement_id for exception in ambiguous}) == 2
    for exception in ambiguous:
        assert len(exception.candidates) == 2
        # All four rules must be shown as attempted, or the refusal is not defensible.
        assert len(exception.tried) == 4


def test_an_ambiguous_credit_is_not_also_reported_as_an_orphan(report):
    contested = {
        ref
        for exception in report.exceptions
        if exception.kind is ExceptionKind.AMBIGUOUS_MATCH
        for ref in exception.candidates
    }
    orphans = {
        exception.bank_ref
        for exception in report.exceptions
        if exception.kind is ExceptionKind.UNMATCHED_BANK_CREDIT
    }
    assert contested & orphans == set()


def test_duplicate_posting_is_flagged_and_counted_once(report):
    duplicates = [
        exception
        for exception in report.exceptions
        if exception.kind is ExceptionKind.DUPLICATE_UTR
    ]
    assert len(duplicates) == 1
    dropped = set(duplicates[0].bank_ref.split(", "))
    assert not dropped & {batch.bank_ref for batch in report.batches}


def test_another_gateways_credit_is_not_raised_as_a_missing_settlement(report):
    """A twelve-digit reference is not evidence of a Razorpay payout."""
    stripe = [
        row for row in report.unmatched_bank_rows if "STRIPE" in row.narration.upper()
    ]
    assert len(stripe) == 1
    raised = {exception.bank_ref for exception in report.exceptions}
    assert stripe[0].ref not in raised


def test_every_exception_says_what_it_tried_and_what_it_needs(report):
    for exception in report.exceptions:
        assert exception.tried, exception.id
        assert exception.needs, exception.id
        assert exception.what, exception.id


def test_exception_ids_are_unique_and_sequential(report):
    ids = [exception.id for exception in report.exceptions]
    assert ids == [f"EXC-{index:02d}" for index in range(1, len(ids) + 1)]


# --------------------------------------------------------------------------- #
# Narration reading
# --------------------------------------------------------------------------- #

def _bank_row(narration: str) -> BankRow:
    from datetime import date

    return BankRow(
        date=date(2026, 8, 3),
        narration=narration,
        credit=Paise(100),
        balance=Paise(100),
        ref="N0001",
    )


@pytest.mark.parametrize(
    "narration,expected",
    [
        ("NEFT-RAZORPAY SOFTWARE PVT-UTR402913847562-SETTLEMENT", "402913847562"),
        ("NEFT-RZPY-402913847999 STTL", "402913847999"),
        ("NEFT RAZORPAY*402914001233", "402914001233"),
        ("RTGS/RAZORPAYSOFTWARE/402914203451/SETTLEMENT", "402914203451"),
    ],
)
def test_readable_references_are_read(narration, expected):
    assert expected in extract(_bank_row(narration)).utrs


def test_a_mangled_reference_is_not_invented(report):
    """The garbled line must yield nothing rather than a plausible guess."""
    garbled = next(read for read in report.narrations if "#" in read.raw)
    assert garbled.utrs == []
    assert "no readable reference in narration" in garbled.notes


def test_an_ifsc_fragment_is_not_mistaken_for_a_reference():
    read = extract(_bank_row("NEFT CR-RATN0000088-RAZORPAY SOFTWARE PVT LTD-setl_D4P2"))
    assert read.utrs == ()


def test_counterparty_is_identified_where_it_can_be():
    assert extract(_bank_row("NEFT-RZPY-402913847999 STTL")).counterparty == "razorpay"
    assert (
        extract(_bank_row("NEFT CR-ICIC0000455-STRIPE PAYMENTS INDIA-UTR911002345678")).counterparty
        == "stripe"
    )
