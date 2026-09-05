"""Builds the synthetic dataset and the planted truth that measures it.

Every number the reconciler will later be scored against is decided here, and the
builder asserts its own arithmetic before writing anything: for each batch, the
planted components must sum exactly to the planted gap. A generator that quietly
disagrees with its own truth file would make the whole scoreboard meaningless.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from recon.generate.spec import (
    BANK_NOISE,
    BATCHES,
    CASE_TABLE,
    CONTRACT_MDR_BPS,
    GST_BPS,
    MERCHANT_ID,
    NARRATION_STYLES,
    OPENING_BALANCE,
    ORPHAN_AMOUNT,
    ORPHAN_DAY,
    ORPHAN_UTR,
    BatchSpec,
)
from recon.model import BankRow, Contract, MdrPeriod, OrderRow, RowType, SettlementRow
from recon.money import Paise, mul_rate
from recon.report import ComponentKind
from recon.truth import Truth, TruthBatch, TruthCase, TruthComponent

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789"

#: Payment sizes, in paise. Whole rupees, which is what a real order book looks
#: like — and which still leaves a fractional fee on almost every row.
_MIN_PAYMENT = 19_900
_MAX_PAYMENT = 899_900


def _token(rng: random.Random, length: int = 10) -> str:
    return "".join(rng.choice(_ALPHABET) for _ in range(length))


def _garble(utr: str) -> str:
    """Corrupt a UTR the way a bad statement export does: lookalike glyphs, lost tail."""
    swapped = utr.translate(str.maketrans({"0": "O", "1": "I", "5": "S"}))
    return swapped[:-4] + "####"


@dataclass
class _Batch:
    """Working state for one settlement batch while it is being assembled."""

    spec: BatchSpec
    rows: list[SettlementRow] = field(default_factory=list)
    orders: list[OrderRow] = field(default_factory=list)
    payment_amounts: list[Paise] = field(default_factory=list)
    #: Positions of the orders refunded in-cycle. Cloned along with the amounts so a
    #: twin batch is identical in value, not merely in its payment list.
    refund_indices: list[int] = field(default_factory=list)
    #: Paid to us but deducted from a *different* batch's payout.
    owed_elsewhere: int = 0
    #: Deducted from our payout but documented in a different batch's report.
    held_here: int = 0

    @property
    def gross(self) -> int:
        return sum(int(row.amount) for row in self.rows)

    @property
    def total_fee(self) -> int:
        return sum(int(row.fee) for row in self.rows)

    @property
    def total_tax(self) -> int:
        return sum(int(row.tax) for row in self.rows)

    @property
    def fee_at_contract(self) -> int:
        """What the fee would have been at the contracted rate, recomputed per row."""
        return sum(
            int(mul_rate(row.amount, CONTRACT_MDR_BPS))
            for row in self.rows
            if row.type is RowType.PAYMENT
        )

    @property
    def unlinked_adjustments(self) -> int:
        return sum(-int(row.amount) for row in self.rows if row.type is RowType.ADJUSTMENT)


@dataclass
class GeneratedData:
    settlements: list[SettlementRow]
    orders: list[OrderRow]
    bank: list[BankRow]
    contract: Contract
    truth: Truth


def build_contract() -> Contract:
    return Contract(
        merchant_id=MERCHANT_ID,
        gst_bps=GST_BPS,
        mdr_schedule=(
            MdrPeriod(
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                mdr_bps=CONTRACT_MDR_BPS,
                label="Standard domestic MDR, calendar year 2026",
            ),
        ),
    )


def _random_datetime_in(rng: random.Random, start: date, end: date) -> datetime:
    span_days = (end - start).days
    day = start + timedelta(days=rng.randint(0, span_days))
    return datetime(
        day.year, day.month, day.day, rng.randint(6, 22), rng.randint(0, 59), tzinfo=timezone.utc
    )


def _build_batch(
    spec: BatchSpec,
    rng: random.Random,
    order_counter: list[int],
    built: dict[str, _Batch],
) -> _Batch:
    batch = _Batch(spec=spec)

    if spec.clone_amounts_from:
        # The twin: identical amounts *and* identical refunds, so the two batches net
        # to the same rupee on the same day. Anything less and the ambiguity case 6
        # tests would not actually be ambiguous.
        source = built[spec.clone_amounts_from]
        batch.payment_amounts = list(source.payment_amounts)
        batch.refund_indices = list(source.refund_indices)
    else:
        batch.payment_amounts = [
            Paise(rng.randrange(_MIN_PAYMENT, _MAX_PAYMENT + 1, 100)) for _ in range(spec.payments)
        ]
        batch.refund_indices = sorted(rng.sample(range(spec.payments), spec.refunds))

    for amount in batch.payment_amounts:
        order_counter[0] += 1
        order_id = f"ORD-{order_counter[0]:05d}"
        payment_id = f"pay_{_token(rng)}"
        fee = mul_rate(amount, spec.mdr_bps)
        tax = mul_rate(fee, GST_BPS)
        batch.rows.append(
            SettlementRow(
                settlement_id=spec.settlement_id,
                payment_id=payment_id,
                order_id=order_id,
                type=RowType.PAYMENT,
                amount=amount,
                fee=fee,
                tax=tax,
                settled_at=spec.settled_at,
                utr=spec.utr,
            )
        )
        # The order file links back inconsistently on purpose: a payment id, a bare
        # UTR, or nothing at all.
        draw = rng.random()
        if draw < 0.60:
            payment_ref = payment_id
        elif draw < 0.85:
            payment_ref = spec.utr
        else:
            payment_ref = ""
        batch.orders.append(
            OrderRow(
                order_id=order_id,
                order_amount=amount,
                status="paid",
                created_at=_random_datetime_in(rng, spec.window_start, spec.window_end),
                refunded_amount=Paise(0),
                payment_ref=payment_ref,
            )
        )

    # Same-cycle refunds: an order paid and returned inside the same window.
    for index in batch.refund_indices:
        order = batch.orders[index]
        batch.orders[index] = order.model_copy(
            update={"status": "refunded", "refunded_amount": order.order_amount}
        )
        batch.rows.append(
            SettlementRow(
                settlement_id=spec.settlement_id,
                payment_id=f"rfnd_{_token(rng)}",
                order_id=order.order_id,
                type=RowType.REFUND,
                amount=Paise(-int(order.order_amount)),
                settled_at=spec.settled_at,
                utr=spec.utr,
            )
        )

    for _ in range(spec.adjustments):
        batch.rows.append(
            SettlementRow(
                settlement_id=spec.settlement_id,
                payment_id=f"adj_{_token(rng)}",
                order_id="",
                type=RowType.ADJUSTMENT,
                amount=Paise(-rng.randrange(50_000, 300_001, 100)),
                settled_at=spec.settled_at,
                utr=spec.utr,
            )
        )

    # A refund belonging to an earlier cycle, documented here. Its value was taken
    # out of that cycle's payout, not this one's.
    if spec.cross_cycle_for:
        target = built[spec.cross_cycle_for]
        victim_index, victim = max(
            enumerate(target.orders), key=lambda pair: (int(pair[1].order_amount), pair[1].order_id)
        )
        if int(victim.order_amount) < spec.cross_cycle_amount:
            raise ValueError(
                f"{spec.settlement_id}: no order in {spec.cross_cycle_for} is large enough "
                f"to carry a {spec.cross_cycle_amount} paise cross-cycle refund"
            )
        target.orders[victim_index] = victim.model_copy(
            update={
                "status": "partially_refunded",
                "refunded_amount": Paise(spec.cross_cycle_amount),
            }
        )
        # Dated inside the *previous* batch's window. That date is the only trace of
        # where this row really belongs, and it is what the adjacent-cycle search finds.
        boundary = datetime(
            target.spec.window_end.year,
            target.spec.window_end.month,
            target.spec.window_end.day,
            18,
            30,
            tzinfo=timezone.utc,
        )
        batch.rows.append(
            SettlementRow(
                settlement_id=spec.settlement_id,
                payment_id=f"rfnd_{_token(rng)}",
                order_id=victim.order_id,
                type=RowType.REFUND,
                amount=Paise(-spec.cross_cycle_amount),
                settled_at=boundary,
                utr=spec.utr,
            )
        )
        batch.owed_elsewhere = spec.cross_cycle_amount
        target.held_here = spec.cross_cycle_amount

    return batch


def _orders_expected(batch: _Batch, orders_by_id: dict[str, OrderRow]) -> int:
    """What the merchant's own records say should arrive, before Razorpay touches it.

    Defined strictly by the settlement rows: an order counts as revenue when a payment
    row references it, and as a deduction when a refund row references it. Anchoring on
    the settlement rows rather than on order dates is what makes a refund documented in
    the wrong cycle show up as a discrepancy instead of quietly cancelling out.
    """
    total = 0
    for row in batch.rows:
        if row.type is RowType.PAYMENT:
            total += int(orders_by_id[row.order_id].order_amount)
        elif row.type is RowType.REFUND:
            total -= -int(row.amount)
    return total


def build(seed: int = 42) -> GeneratedData:
    contract = build_contract()
    order_counter = [0]
    built: dict[str, _Batch] = {}

    for spec in BATCHES:
        # Seeding per batch keeps batches independent: resizing one does not shift the
        # amounts in any other, so the dataset stays reviewable as it evolves.
        rng = random.Random(f"{seed}|{spec.settlement_id}")
        built[spec.settlement_id] = _build_batch(spec, rng, order_counter, built)

    settlements: list[SettlementRow] = []
    orders: list[OrderRow] = []
    for spec in BATCHES:
        settlements.extend(built[spec.settlement_id].rows)
        orders.extend(built[spec.settlement_id].orders)
    orders_by_id = {order.order_id: order for order in orders}

    truth_batches: list[TruthBatch] = []
    bank_drafts: list[tuple[date, str, int, int, str]] = []  # day, narration, debit, credit, tag

    for spec in BATCHES:
        batch = built[spec.settlement_id]
        gross = batch.gross
        fee = batch.total_fee
        tax = batch.total_tax
        settlement_expected = gross - fee - tax

        # What actually lands: our own payout, plus anything a later cycle deducted on
        # our behalf, minus anything deducted from us and documented elsewhere.
        credit = settlement_expected + batch.owed_elsewhere - batch.held_here
        rounding = 0
        if spec.round_payout_to_rupee:
            rounding = credit % 100
            credit -= rounding
        credit -= spec.unexplained

        orders_expected = _orders_expected(batch, orders_by_id)
        gap = orders_expected - credit if spec.emits_bank_line else None

        components: list[TruthComponent] = []
        fee_at_contract = batch.fee_at_contract
        drift = fee - fee_at_contract
        if fee_at_contract:
            components.append(
                TruthComponent(
                    kind=ComponentKind.FEE,
                    amount=Paise(fee_at_contract),
                    note=f"{CONTRACT_MDR_BPS / 100:.2f}% of settled payments, per contract",
                )
            )
        if drift:
            components.append(
                TruthComponent(
                    kind=ComponentKind.FEE_RATE_DRIFT,
                    amount=Paise(drift),
                    note=f"charged at {spec.mdr_bps / 100:.2f}% against a contracted "
                    f"{CONTRACT_MDR_BPS / 100:.2f}%",
                )
            )
        if tax:
            components.append(
                TruthComponent(
                    kind=ComponentKind.GST_ON_FEE,
                    amount=Paise(tax),
                    note=f"{GST_BPS / 100:.0f}% GST on fees charged",
                )
            )
        if batch.unlinked_adjustments:
            components.append(
                TruthComponent(
                    kind=ComponentKind.UNLINKED_ADJUSTMENT,
                    amount=Paise(batch.unlinked_adjustments),
                    note="adjustment rows with no order to link against",
                )
            )
        cross_cycle = batch.held_here - batch.owed_elsewhere
        if cross_cycle:
            direction = (
                "deducted here, documented in the next cycle"
                if cross_cycle > 0
                else "documented here, already deducted in the previous cycle"
            )
            components.append(
                TruthComponent(
                    kind=ComponentKind.CROSS_CYCLE_REFUND,
                    amount=Paise(cross_cycle),
                    note=direction,
                )
            )
        if rounding:
            components.append(
                TruthComponent(
                    kind=ComponentKind.ROUNDING,
                    amount=Paise(rounding),
                    note="payout truncated to whole rupees by the remitting bank",
                )
            )
        if spec.unexplained:
            components.append(
                TruthComponent(
                    kind=ComponentKind.UNEXPLAINED,
                    amount=Paise(spec.unexplained),
                    detectable=False,
                    note="no cause exists in any of the three files - the correct output "
                    "is an exception, not an explanation",
                )
            )

        if spec.emits_bank_line:
            planted = sum(int(component.amount) for component in components)
            if planted != gap:
                raise AssertionError(
                    f"{spec.settlement_id}: planted components sum to {planted} "
                    f"but the gap is {gap}"
                )
            day = (spec.settled_at + timedelta(days=spec.bank_lag_days)).date()
            narration = NARRATION_STYLES[spec.narration_style].format(
                utr=spec.utr,
                settlement_id=spec.settlement_id,
                utr_garbled=_garble(spec.utr),
            )
            bank_drafts.append((day, narration, 0, credit, spec.settlement_id))
            if 7 in spec.cases:  # noqa: PLR2004 - the PRD's case number, not a magic value
                # The same payout posted twice by the bank. Same UTR, same value, a
                # different reference - it must be recognised, not counted.
                bank_drafts.append((day, narration, 0, credit, f"{spec.settlement_id}~dup"))
        else:
            # Nothing arrived, so there is nothing to attribute. Listing fees here
            # would be describing a gap that does not exist yet.
            components = []

        truth_batches.append(
            TruthBatch(
                settlement_id=spec.settlement_id,
                utr=spec.utr,
                settled_at=spec.settled_at,
                window_start=spec.window_start,
                window_end=spec.window_end,
                gross_settled=Paise(gross),
                total_fee=Paise(fee),
                total_tax=Paise(tax),
                orders_expected=Paise(orders_expected),
                bank_credit=Paise(credit) if spec.emits_bank_line else None,
                expected_gap=Paise(gap) if gap is not None else None,
                components=components,
                expected_rule=_expected_rule(spec),
                expected_outcome=spec.note,
                cases=list(spec.cases),
            )
        )

    bank_drafts.append(
        (
            ORPHAN_DAY,
            NARRATION_STYLES["neft_full"].format(utr=ORPHAN_UTR),
            0,
            ORPHAN_AMOUNT,
            "orphan",
        )
    )
    for noise in BANK_NOISE:
        bank_drafts.append((noise.day, noise.narration, noise.debit, noise.credit, noise.ref))

    bank, ref_by_tag = _finalise_bank(bank_drafts)

    # Bank references are only known once the statement is ordered, so the truth records
    # point at them here. This is what lets the evaluator distinguish "matched" from
    # "matched to the right line" - without it, a false match would be invisible.
    for truth_batch in truth_batches:
        truth_batch.bank_ref = ref_by_tag.get(truth_batch.settlement_id)

    truth = Truth(
        seed=seed,
        contract_file="contract.json",
        settlement_rows=len(settlements),
        order_rows=len(orders),
        bank_rows=len(bank),
        total_expected_gap=Paise(
            sum(int(b.expected_gap) for b in truth_batches if b.expected_gap is not None)
        ),
        total_detectable=Paise(
            sum(int(c.amount) for b in truth_batches for c in b.components if c.detectable)
        ),
        total_undetectable=Paise(
            sum(int(c.amount) for b in truth_batches for c in b.components if not c.detectable)
        ),
        batches=truth_batches,
        cases=_build_cases(ref_by_tag),
    )

    return GeneratedData(
        settlements=settlements, orders=orders, bank=bank, contract=contract, truth=truth
    )


def _expected_rule(spec: BatchSpec) -> str | None:
    if not spec.emits_bank_line:
        return None
    if spec.narration_style == "bare":
        return None  # ambiguous by construction
    if spec.narration_style == "with_settlement_id":
        return "R2"
    if spec.narration_style == "garbled":
        return "R4" if spec.bank_lag_days else "R3"
    return "R1"


def _finalise_bank(
    drafts: list[tuple[date, str, int, int, str]],
) -> tuple[list[BankRow], dict[str, str]]:
    """Order the statement by date, assign references, and carry a running balance.

    Returns the rows alongside a map from planted tag to the reference the row ended
    up with, so the truth file can name exact bank lines without having to recognise
    them by content — the case-6 twins are deliberately indistinguishable by content.
    """
    ordered = sorted(drafts, key=lambda draft: (draft[0], draft[4]))
    balance = OPENING_BALANCE
    rows: list[BankRow] = []
    ref_by_tag: dict[str, str] = {}
    for index, (day, narration, debit, credit, tag) in enumerate(ordered, start=1):
        balance += credit - debit
        ref = f"N{index:04d}"
        ref_by_tag[tag] = ref
        rows.append(
            BankRow(
                date=day,
                narration=narration,
                debit=Paise(debit),
                credit=Paise(credit),
                balance=Paise(balance),
                ref=ref,
            )
        )
    return rows, ref_by_tag


def _build_cases(ref_by_tag: dict[str, str]) -> list[TruthCase]:
    by_case: dict[int, list[str]] = {}
    for spec in BATCHES:
        for case in spec.cases:
            by_case.setdefault(case, []).append(spec.settlement_id)

    duplicate_refs = sorted(
        ref for tag, ref in ref_by_tag.items() if tag.endswith("~dup") or f"{tag}~dup" in ref_by_tag
    )

    cases: list[TruthCase] = []
    for number, name, expected in CASE_TABLE:
        if number == 7:
            bank_refs = duplicate_refs
        elif number == 8:
            bank_refs = [ref_by_tag["orphan"]]
        else:
            bank_refs = []
        cases.append(
            TruthCase(
                number=number,
                name=name,
                expected=expected,
                settlement_ids=by_case.get(number, []),
                bank_refs=bank_refs,
            )
        )
    return cases
