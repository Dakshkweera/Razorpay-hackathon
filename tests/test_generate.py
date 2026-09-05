"""The generator is the measuring stick, so it gets tested before anything it measures.

Each planted case from the PRD's table is asserted to actually exist in the data with
the shape the reconciler will later be scored against. A case that quietly stopped
being planted would otherwise show up as a suspiciously good match rate.
"""

from __future__ import annotations

import pytest

from recon.generate.build import build
from recon.generate.spec import CASE_TABLE, CONTRACT_MDR_BPS, GST_BPS
from recon.generate.writer import render_bank, render_orders, render_settlements
from recon.model import RowType
from recon.money import mul_rate
from recon.report import ComponentKind


@pytest.fixture(scope="module")
def data():
    return build(seed=42)


@pytest.fixture(scope="module")
def truth(data):
    return data.truth


@pytest.fixture(scope="module")
def batches(truth):
    return {batch.settlement_id: batch for batch in truth.batches}


# --------------------------------------------------------------------------- #
# Scale and internal consistency
# --------------------------------------------------------------------------- #

def test_clears_the_fifty_record_bar_several_times_over(truth):
    assert truth.settlement_rows >= 250
    assert 6 <= len(truth.batches) <= 10


def test_every_planted_component_sums_to_its_planted_gap(truth):
    for batch in truth.batches:
        if batch.expected_gap is None:
            assert not batch.components, f"{batch.settlement_id} has no credit but lists causes"
            continue
        total = sum(int(component.amount) for component in batch.components)
        assert total == int(batch.expected_gap), batch.settlement_id


def test_amounts_are_whole_paise(data):
    for row in data.settlements:
        assert isinstance(int(row.amount), int)
        assert int(row.fee) >= 0
        assert int(row.tax) >= 0


def test_fee_and_tax_are_charged_on_payments_only(data):
    for row in data.settlements:
        if row.type is not RowType.PAYMENT:
            assert int(row.fee) == 0 and int(row.tax) == 0, row.payment_id


def test_gst_is_exactly_the_contracted_percentage_of_fee(data):
    for row in data.settlements:
        if row.type is RowType.PAYMENT:
            assert int(row.tax) == int(mul_rate(row.fee, GST_BPS)), row.payment_id


def test_all_planted_cases_are_located(truth):
    assert len(truth.cases) == len(CASE_TABLE) == 11
    for case in truth.cases:
        # Case 11 is a fact about the bank file's header row, not about any one
        # settlement or bank line - there is nothing for it to point at.
        if case.number == 11:
            continue
        assert case.settlement_ids or case.bank_refs, f"case {case.number} points at nothing"


# --------------------------------------------------------------------------- #
# The planted cases, one test each
# --------------------------------------------------------------------------- #

def test_case_1_clean_batch_has_only_fee_and_gst(batches):
    batch = batches["setl_A1F3"]
    assert {c.kind for c in batch.components} == {ComponentKind.FEE, ComponentKind.GST_ON_FEE}
    assert batch.expected_rule == "R1"


def test_case_2_fees_gst_and_a_sub_rupee_truncation(batches):
    batch = batches["setl_B2K7"]
    rounding = [c for c in batch.components if c.kind is ComponentKind.ROUNDING]
    assert len(rounding) == 1
    assert 0 < int(rounding[0].amount) < 100, "rounding must stay under one rupee"


def test_case_3_refund_is_documented_one_cycle_away_from_where_it_was_deducted(data, batches):
    short = batches["setl_C3M9"]
    holder = batches["setl_D4P2"]
    shortfall = next(c for c in short.components if c.kind is ComponentKind.CROSS_CYCLE_REFUND)
    excess = next(c for c in holder.components if c.kind is ComponentKind.CROSS_CYCLE_REFUND)
    assert int(shortfall.amount) == -int(excess.amount), "the two ends must cancel"

    # The row lives in D4P2's report but is dated inside C3M9's window. That date is
    # the only trace of where it belongs, and it is what the adjacent-cycle search finds.
    stray = [
        row
        for row in data.settlements
        if row.settlement_id == "setl_D4P2"
        and row.type is RowType.REFUND
        and row.settled_at.date() <= short.window_end
    ]
    assert len(stray) == 1
    assert short.window_start <= stray[0].settled_at.date() <= short.window_end


def test_case_4_fee_rate_drift_is_the_excess_over_the_contracted_rate(data, batches):
    batch = batches["setl_E5R8"]
    drift = next(c for c in batch.components if c.kind is ComponentKind.FEE_RATE_DRIFT)
    contracted = next(c for c in batch.components if c.kind is ComponentKind.FEE)
    charged = sum(
        int(row.fee) for row in data.settlements if row.settlement_id == "setl_E5R8"
    )
    assert int(contracted.amount) + int(drift.amount) == charged
    assert int(drift.amount) > 0


def test_case_5_narration_is_glyph_corrupted_but_fully_recoverable(data, batches):
    """The UTR is masked with lookalike glyphs, not deleted digits.

    A regex sees a run of digits broken up by letters and finds nothing - but nothing
    was actually lost. Reversing the exact three substitutions the generator applied
    (O/I/S back to 0/1/5) recovers the real UTR byte for byte, which is what lets a
    model - and the offline stub, which implements the same reversal - match this
    batch by R1 instead of falling back to amount and date.
    """
    batch = batches["setl_F6T1"]
    line = next(row for row in data.bank if int(row.credit) == int(batch.bank_credit))
    assert batch.utr not in line.narration, "a directly readable UTR would make this trivial"
    recovered = line.narration.translate(str.maketrans({"O": "0", "I": "1", "S": "5"}))
    assert batch.utr in recovered, "reversing the substitution must recover the exact UTR"

    # The safety net: if the AI layer is off entirely, amount-and-date must still reach
    # this batch, so nothing else may disturb its credit and it must post late.
    implied = int(batch.gross_settled) - int(batch.total_fee) - int(batch.total_tax)
    assert implied == int(batch.bank_credit)
    assert line.date > batch.settled_at.date(), "posted late, so R4 is the fallback route"


def test_case_6_twins_are_genuinely_indistinguishable(data, batches):
    left, right = batches["setl_G7V4"], batches["setl_H8X6"]
    assert int(left.bank_credit) == int(right.bank_credit)
    assert left.settled_at.date() == right.settled_at.date()

    lines = [row for row in data.bank if int(row.credit) == int(left.bank_credit)]
    assert len(lines) == 2
    for line in lines:
        assert left.utr not in line.narration and right.utr not in line.narration
        assert "setl_" not in line.narration
    assert left.expected_rule is None and right.expected_rule is None


def test_case_7_duplicate_posting_repeats_a_utr_across_two_lines(data, truth):
    case = next(c for c in truth.cases if c.number == 7)
    assert len(case.bank_refs) == 2
    rows = [row for row in data.bank if row.ref in case.bank_refs]
    assert len({row.narration for row in rows}) == 1
    assert len({int(row.credit) for row in rows}) == 1


def test_case_8_orphan_credit_matches_no_settlement(data, truth):
    case = next(c for c in truth.cases if c.number == 8)
    orphan = next(row for row in data.bank if row.ref == case.bank_refs[0])
    utrs = {batch.utr for batch in truth.batches}
    assert not any(utr in orphan.narration for utr in utrs)


def test_case_9_settlement_was_never_credited(batches):
    batch = batches["setl_J9Z0"]
    assert batch.bank_credit is None
    assert batch.expected_gap is None


def test_case_10_the_unexplainable_amount_is_marked_undetectable(batches):
    batch = batches["setl_E5R8"]
    unexplained = next(c for c in batch.components if c.kind is ComponentKind.UNEXPLAINED)
    assert int(unexplained.amount) == 180_000  # Rs 1,800.00
    assert unexplained.detectable is False


def test_only_the_unexplainable_component_is_undetectable(truth):
    undetectable = [
        (batch.settlement_id, component)
        for batch in truth.batches
        for component in batch.components
        if not component.detectable
    ]
    assert len(undetectable) == 1
    assert undetectable[0][1].kind is ComponentKind.UNEXPLAINED


def test_contract_rate_is_the_one_the_clean_batches_were_charged_at(data, batches):
    contract = data.contract
    batch = batches["setl_A1F3"]
    assert contract.mdr_bps_on(batch.settled_at.date()) == CONTRACT_MDR_BPS
    for row in data.settlements:
        if row.settlement_id == "setl_A1F3" and row.type is RowType.PAYMENT:
            assert int(row.fee) == int(mul_rate(row.amount, CONTRACT_MDR_BPS))


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #

def test_same_seed_regenerates_byte_identical_files():
    first, second = build(seed=42), build(seed=42)
    assert render_settlements(first.settlements) == render_settlements(second.settlements)
    assert render_orders(first.orders) == render_orders(second.orders)
    assert render_bank(first.bank) == render_bank(second.bank)


def test_a_different_seed_produces_different_data():
    assert render_settlements(build(seed=42).settlements) != render_settlements(
        build(seed=43).settlements
    )
