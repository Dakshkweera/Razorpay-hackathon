"""Gap attribution, and the refusal to attribute what cannot be explained.

The decomposition identity is asserted directly: for every matched batch, the
attributed components plus the residual must equal the gap exactly. Nothing here
is allowed to be approximately right.
"""

from __future__ import annotations

import pytest

from recon.decompose.checks import ADJACENT_CYCLES
from recon.evaluate.score import load_truth, score
from recon.generate.build import build
from recon.generate.spec import CONTRACT_MDR_BPS, GST_BPS
from recon.generate.writer import write_dataset
from recon.money import mul_rate
from recon.pipeline import group_rows, load, run
from recon.model import RowType
from recon.report import CaseStatus, ComponentKind, ExceptionKind, LlmMode, Verdict


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    directory = tmp_path_factory.mktemp("decompose")
    write_dataset(build(seed=42), directory)
    return directory


@pytest.fixture(scope="module")
def report(data_dir):
    # Explicit and offline: this suite tests the deterministic engine, not whatever
    # LlmMode the ambient repo happens to auto-resolve to.
    return run(data_dir, llm_mode=LlmMode.STUB)


@pytest.fixture(scope="module")
def evaluation(report, data_dir):
    return score(report, load_truth(data_dir / "truth.json"))


@pytest.fixture(scope="module")
def batches(report):
    return {batch.settlement_id: batch for batch in report.batches}


def components(batch, kind: ComponentKind):
    return [component for component in batch.components if component.kind is kind]


# --------------------------------------------------------------------------- #
# The identity everything rests on
# --------------------------------------------------------------------------- #

def test_components_plus_residual_equal_the_gap_exactly(report):
    for batch in report.batches:
        if batch.bank_credit is None:
            continue
        total = sum(int(component.amount) for component in batch.components)
        assert total == int(batch.headline_gap), batch.settlement_id


def test_explained_excludes_the_residue(report):
    for batch in report.batches:
        if batch.bank_credit is None:
            continue
        assert int(batch.explained) + int(batch.residual) == int(batch.headline_gap)


def test_an_uncredited_batch_gets_no_components(batches):
    batch = batches["setl_J9Z0"]
    assert batch.bank_credit is None
    assert batch.components == []


# --------------------------------------------------------------------------- #
# The five checks
# --------------------------------------------------------------------------- #

def test_fee_is_recomputed_per_row_not_on_the_total(data_dir, batches):
    """Rates round per transaction; comparing totals invents a few paise every batch."""
    rows = group_rows(load(data_dir))["setl_A1F3"]
    per_row = sum(
        int(mul_rate(row.amount, CONTRACT_MDR_BPS))
        for row in rows
        if row.type is RowType.PAYMENT
    )
    on_total = int(
        mul_rate(sum(int(row.amount) for row in rows if row.type is RowType.PAYMENT), CONTRACT_MDR_BPS)
    )
    reported = int(components(batches["setl_A1F3"], ComponentKind.FEE)[0].amount)
    assert reported == per_row
    if per_row != on_total:
        assert reported != on_total


def test_fee_rate_drift_is_the_excess_over_contract(data_dir, batches):
    batch = batches["setl_E5R8"]
    rows = group_rows(load(data_dir))["setl_E5R8"]
    charged = sum(int(row.fee) for row in rows)
    at_contract = int(components(batch, ComponentKind.FEE)[0].amount)
    drift = int(components(batch, ComponentKind.FEE_RATE_DRIFT)[0].amount)
    assert at_contract + drift == charged
    assert "1.20%" in components(batch, ComponentKind.FEE_RATE_DRIFT)[0].detail


def test_batches_charged_at_contract_report_no_drift(batches):
    for settlement_id in ("setl_A1F3", "setl_B2K7", "setl_C3M9", "setl_F6T1"):
        assert components(batches[settlement_id], ComponentKind.FEE_RATE_DRIFT) == []


def test_gst_is_verified_against_the_fee_actually_charged(data_dir, batches):
    for settlement_id, batch in batches.items():
        if batch.bank_credit is None:
            continue
        rows = group_rows(load(data_dir))[settlement_id]
        expected = sum(
            int(mul_rate(row.fee, GST_BPS)) for row in rows if row.type is RowType.PAYMENT
        )
        reported = int(components(batch, ComponentKind.GST_ON_FEE)[0].amount)
        assert reported == expected, settlement_id


def test_cross_cycle_refund_is_found_at_both_ends(batches):
    short = components(batches["setl_C3M9"], ComponentKind.CROSS_CYCLE_REFUND)[0]
    holder = components(batches["setl_D4P2"], ComponentKind.CROSS_CYCLE_REFUND)[0]
    assert int(short.amount) > 0, "the cycle that was short reports a positive amount"
    assert int(holder.amount) == -int(short.amount)
    assert f"+/-{ADJACENT_CYCLES}" in short.check


def test_same_cycle_refunds_are_not_mistaken_for_misfiled_ones(batches):
    """Every row carries the settlement timestamp, so the date alone proves nothing."""
    for settlement_id in ("setl_A1F3", "setl_B2K7", "setl_E5R8", "setl_F6T1"):
        assert components(batches[settlement_id], ComponentKind.CROSS_CYCLE_REFUND) == [], (
            settlement_id
        )


def test_unlinked_adjustments_are_attributed_and_named(data_dir, batches):
    batch = batches["setl_D4P2"]
    adjustment = components(batch, ComponentKind.UNLINKED_ADJUSTMENT)[0]
    rows = group_rows(load(data_dir))["setl_D4P2"]
    planted = sum(-int(row.amount) for row in rows if row.type is RowType.ADJUSTMENT)
    assert int(adjustment.amount) == planted
    assert "adj_" in adjustment.detail


def test_rounding_is_attributed_only_within_its_bound(batches):
    rounding = components(batches["setl_B2K7"], ComponentKind.ROUNDING)
    assert len(rounding) == 1
    assert 0 < int(rounding[0].amount) < 100


def test_rounding_is_ruled_out_where_it_cannot_reach(report):
    """The residue exception must say why rounding was excluded, with the number."""
    residue = next(
        exception
        for exception in report.exceptions
        if exception.kind is ExceptionKind.UNEXPLAINED_RESIDUE
    )
    ruled = [entry for entry in residue.ruled_out if entry.check == "rounding"]
    assert len(ruled) == 1
    assert "at most" in ruled[0].reason


# --------------------------------------------------------------------------- #
# The refusal
# --------------------------------------------------------------------------- #

def test_the_unexplainable_amount_stays_unexplained(batches):
    batch = batches["setl_E5R8"]
    assert int(batch.residual) == 180_000  # Rs 1,800.00
    residue = components(batch, ComponentKind.UNEXPLAINED)
    assert len(residue) == 1
    assert residue[0].attributed is False, "no cause was committed to"


def test_exactly_one_batch_has_a_residue(report):
    with_residue = [
        batch
        for batch in report.batches
        if batch.bank_credit is not None and int(batch.residual) != 0
    ]
    assert [batch.settlement_id for batch in with_residue] == ["setl_E5R8"]


def test_the_residue_exception_lists_every_check_it_ran(report):
    residue = next(
        exception
        for exception in report.exceptions
        if exception.kind is ExceptionKind.UNEXPLAINED_RESIDUE
    )
    checks = " ".join(attempt.check for attempt in residue.tried)
    for expected in ("fee recompute", "gst verification", "unlinked adjustments",
                     "adjacent cycles", "rounding"):
        assert expected in checks, expected
    assert residue.needs


def test_no_cause_is_invented_for_the_undetectable_amount(evaluation):
    for batch in evaluation.batches:
        for component in batch.components:
            assert component.verdict is not Verdict.FALSE_CAUSE, batch.settlement_id


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def test_all_ten_planted_cases_pass(evaluation):
    failed = [case for case in evaluation.cases if case.status is not CaseStatus.PASS]
    assert failed == [], [f"case {case.number}: {case.actual}" for case in failed]


def test_the_two_headline_counters_are_zero(evaluation):
    assert evaluation.false_matches == 0
    assert evaluation.false_cause_attributions == 0


def test_accuracy_is_honestly_below_a_hundred(evaluation):
    """The two ambiguous batches are never matched, so their gaps are never explained."""
    assert 80 < evaluation.gap_accuracy_pct < 100


def test_unexplained_total_is_exactly_what_was_planted(report, data_dir):
    truth = load_truth(data_dir / "truth.json")
    assert int(report.scoreboard.gap_unexplained) == int(truth.total_undetectable)
