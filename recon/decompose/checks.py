"""Stage 4 - attributing the gap.

The gap this stage explains is ``orders_expected - bank_credit``: what the merchant's
own records say they earned, against what actually arrived. It decomposes exactly,
and the identity is worth stating because every check below is a consequence of it::

    headline_gap = fee + gst + unlinked_adjustments + settlement_residual

The first three terms are deductions the order book never knew about, and they are
arithmetic - recomputable from the settlement file and the contract, with no
searching. The fourth is the interesting one: money the settlement file itself says
should have arrived and did not. That is where the cross-cycle search and the
rounding bound do their work, and whatever survives them is reported as unexplained.

Five checks, deterministic, in order. The LLM is not in this file and has no
business being here: every number below is recomputed, not inferred.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from recon.model import Contract, OrderRow, RowType, SettlementRow
from recon.money import Paise, format_inr, mul_rate
from recon.report import (
    Attempt,
    BatchReport,
    ComponentKind,
    ComponentSource,
    ExceptionKind,
    ExceptionReport,
    GapComponent,
    RuledOut,
    TraceEntry,
)

#: Cycles to search either side for a refund that landed in the wrong report.
ADJACENT_CYCLES = 1

#: A payout truncated to whole rupees can lose at most this much.
_MAX_TRUNCATION_PAISE = 99


@dataclass
class _Working:
    """One batch's attribution as it is being built."""

    components: list[GapComponent] = field(default_factory=list)
    trace: list[TraceEntry] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    ruled_out: list[RuledOut] = field(default_factory=list)

    def attribute(
        self,
        kind: ComponentKind,
        amount: int,
        check: str,
        detail: str,
    ) -> None:
        if amount == 0:
            return
        self.components.append(
            GapComponent(
                kind=kind,
                amount=Paise(amount),
                source=ComponentSource.DETERMINISTIC,
                check=check,
                detail=detail,
            )
        )
        self.attempts.append(
            Attempt(check=check, outcome=detail, attributed=Paise(amount))
        )
        self.trace.append(
            TraceEntry(
                stage="decompose",
                action=check,
                detail=f"{format_inr(Paise(amount))} - {detail}",
            )
        )

    def nothing_found(self, check: str, outcome: str) -> None:
        self.attempts.append(Attempt(check=check, outcome=outcome))
        self.trace.append(TraceEntry(stage="decompose", action=check, detail=outcome))


def _check_fees(
    batch: BatchReport, rows: list[SettlementRow], contract: Contract, work: _Working
) -> None:
    """Check 1 - recompute every fee at the contracted rate and price the difference.

    Recomputed per row rather than on the batch total: rounding is applied per
    transaction in the real system, and comparing a total against a rate would
    manufacture a discrepancy of a few paise on every batch.
    """
    mdr_bps = contract.mdr_bps_on(batch.settled_at.date())
    payments = [row for row in rows if row.type is RowType.PAYMENT]
    at_contract = sum(int(mul_rate(row.amount, mdr_bps)) for row in payments)
    charged = int(batch.total_fee)

    work.attribute(
        ComponentKind.FEE,
        at_contract,
        "fee recompute",
        f"{mdr_bps / 100:.2f}% of settled payments, recomputed per row against the contract",
    )

    drift = charged - at_contract
    if drift == 0:
        work.nothing_found(
            "fee rate check",
            f"fees charged match the contracted {mdr_bps / 100:.2f}% exactly",
        )
        return

    gross_payments = sum(int(row.amount) for row in payments)
    effective_bps = round(10_000 * charged / gross_payments) if gross_payments else 0
    work.attribute(
        ComponentKind.FEE_RATE_DRIFT,
        drift,
        "fee rate check",
        f"charged {format_inr(Paise(charged))} against {format_inr(Paise(at_contract))} "
        f"at contract - an effective {effective_bps / 100:.2f}% versus the contracted "
        f"{mdr_bps / 100:.2f}%",
    )


def _check_tax(
    batch: BatchReport, rows: list[SettlementRow], contract: Contract, work: _Working
) -> None:
    """Check 2 - verify GST is the contracted percentage of the fee actually charged."""
    expected = sum(
        int(mul_rate(row.fee, contract.gst_bps))
        for row in rows
        if row.type is RowType.PAYMENT
    )
    charged = int(batch.total_tax)

    work.attribute(
        ComponentKind.GST_ON_FEE,
        charged,
        "gst verification",
        f"{contract.gst_bps / 100:.0f}% of fees charged"
        if charged == expected
        else f"{format_inr(Paise(charged))} charged where "
        f"{contract.gst_bps / 100:.0f}% of fees is {format_inr(Paise(expected))}",
    )
    if charged != expected:
        work.trace.append(
            TraceEntry(
                stage="decompose",
                action="gst verification",
                detail=f"GST is off by {format_inr(Paise(charged - expected))}; the "
                "difference is left in the residual rather than absorbed here",
            )
        )


def _check_cross_cycle(
    batch: BatchReport,
    rows: list[SettlementRow],
    neighbours: list[tuple[BatchReport, list[SettlementRow]]],
    work: _Working,
) -> None:
    """Check 3 - refunds documented in one cycle's report but taken out of another's payout.

    Every row in a settlement report normally carries that settlement's own timestamp.
    A refund stamped with a *different, earlier* time is the anomaly worth chasing: it
    was taken out of an earlier payout and only written down here. That mismatch is the
    signal, not the date alone — a batch's own same-cycle refunds are dated on its
    settlement day too, and treating those as misfiled would find a cross-cycle refund
    in almost every batch.

    Both ends are found here, which is why the component can be negative: the cycle that
    was short reports a positive amount, the cycle holding the paperwork a negative one.
    """

    def out_of_cycle(row: SettlementRow, owner: BatchReport) -> bool:
        return row.type is RowType.REFUND and row.settled_at != owner.settled_at

    owed_to_us = 0
    owed_details: list[str] = []
    for neighbour, neighbour_rows in neighbours:
        for row in neighbour_rows:
            if not out_of_cycle(row, neighbour):
                continue
            if batch.window_start <= row.settled_at.date() <= batch.window_end:
                owed_to_us += -int(row.amount)
                owed_details.append(
                    f"{row.payment_id} in {neighbour.settlement_id}, dated "
                    f"{row.settled_at.date().isoformat()} inside this window rather than "
                    f"on {neighbour.settled_at.date().isoformat()} with the rest of that report"
                )

    documented_here = 0
    here_details: list[str] = []
    for row in rows:
        if not out_of_cycle(row, batch):
            continue
        for neighbour, _ in neighbours:
            if neighbour.window_start <= row.settled_at.date() <= neighbour.window_end:
                documented_here += -int(row.amount)
                here_details.append(
                    f"{row.payment_id} dated {row.settled_at.date().isoformat()}, inside "
                    f"{neighbour.settlement_id}'s window"
                )
                break

    net = owed_to_us - documented_here
    if net == 0:
        work.nothing_found(
            f"adjacent cycles +/-{ADJACENT_CYCLES} searched",
            f"no refund in {', '.join(n.settlement_id for n, _ in neighbours) or 'any neighbour'} "
            f"is dated inside this window, and none of this batch's own refunds belong "
            f"to a neighbour",
        )
        return

    if owed_to_us:
        detail = (
            f"deducted from this payout but documented next cycle: {'; '.join(owed_details)}"
        )
    else:
        detail = f"documented here but already deducted elsewhere: {'; '.join(here_details)}"
    work.attribute(
        ComponentKind.CROSS_CYCLE_REFUND,
        net,
        f"adjacent cycles +/-{ADJACENT_CYCLES} searched",
        detail,
    )


def _check_adjustments(
    rows: list[SettlementRow], orders_by_id: dict[str, OrderRow], work: _Working
) -> None:
    """Check 4 - adjustment rows with no order behind them.

    The order book has no record of these at all, so they never appear in what the
    merchant expected, and they reduce the payout in full.
    """
    unlinked = [
        row
        for row in rows
        if row.type is RowType.ADJUSTMENT
        and (not row.order_id or row.order_id not in orders_by_id)
    ]
    linked = [
        row
        for row in rows
        if row.type is RowType.ADJUSTMENT and row.order_id and row.order_id in orders_by_id
    ]

    if linked:
        # Deliberately not attributed: an adjustment that does point at an order is a
        # different question, and guessing at it here would be an invented cause.
        work.nothing_found(
            "unlinked adjustments",
            f"{len(linked)} adjustment rows do link to an order and are left for review",
        )

    if not unlinked:
        work.nothing_found("unlinked adjustments", "no adjustment rows without an order")
        return

    total = sum(-int(row.amount) for row in unlinked)
    work.attribute(
        ComponentKind.UNLINKED_ADJUSTMENT,
        total,
        "unlinked adjustments",
        f"{len(unlinked)} adjustment row{'s' if len(unlinked) != 1 else ''} "
        f"({', '.join(row.payment_id for row in unlinked)}) with no order to link against",
    )


def _check_rounding(batch: BatchReport, remaining: int, work: _Working) -> int:
    """Check 5 - sub-rupee loss, bounded rather than assumed.

    The bound is what makes this honest: per-row fee rounding can move at most one
    paise per payment, and a payout truncated to whole rupees can lose at most 99.
    Anything inside that is rounding; anything outside it is not, and saying so is how
    rounding gets *ruled out* on the batches where it does not apply.
    """
    bound = batch.payment_count + _MAX_TRUNCATION_PAISE
    if remaining == 0:
        work.nothing_found("rounding", "nothing left to account for")
        return 0
    if abs(remaining) > bound:
        work.ruled_out.append(
            RuledOut(
                check="rounding",
                reason=f"at most {format_inr(Paise(bound))} is reachable "
                f"({batch.payment_count} payments at one paise each, plus up to "
                f"{format_inr(Paise(_MAX_TRUNCATION_PAISE))} of payout truncation), and "
                f"{format_inr(Paise(abs(remaining)))} remains",
            )
        )
        work.nothing_found(
            "rounding",
            f"ruled out - maximum possible is {format_inr(Paise(bound))}",
        )
        return 0

    work.attribute(
        ComponentKind.ROUNDING,
        remaining,
        "rounding",
        f"within the {format_inr(Paise(bound))} reachable by per-row fee rounding and "
        f"whole-rupee payout truncation",
    )
    return remaining


def decompose(
    batch: BatchReport,
    rows: list[SettlementRow],
    orders_by_id: dict[str, OrderRow],
    contract: Contract,
    neighbours: list[tuple[BatchReport, list[SettlementRow]]],
) -> ExceptionReport | None:
    """Attribute one batch's gap, and raise an exception for anything left over."""
    if batch.bank_credit is None:
        return None  # nothing arrived; there is no gap to decompose

    work = _Working()
    _check_fees(batch, rows, contract, work)
    _check_tax(batch, rows, contract, work)
    _check_adjustments(rows, orders_by_id, work)
    _check_cross_cycle(batch, rows, neighbours, work)

    attributed = sum(int(component.amount) for component in work.components)
    remaining = int(batch.headline_gap) - attributed
    _check_rounding(batch, remaining, work)

    attributed = sum(int(component.amount) for component in work.components)
    residual = int(batch.headline_gap) - attributed

    batch.components = work.components
    batch.explained = Paise(attributed)
    batch.residual = Paise(residual)
    batch.trace.extend(work.trace)

    if residual == 0:
        batch.trace.append(
            TraceEntry(
                stage="decompose",
                action="complete",
                detail=f"{format_inr(batch.headline_gap)} fully attributed",
            )
        )
        return None

    # Reported as its own component so the residue is visible in the decomposition
    # rather than only in the exception list. It is an admission, not a cause.
    batch.components.append(
        GapComponent(
            kind=ComponentKind.UNEXPLAINED,
            amount=Paise(residual),
            source=ComponentSource.DETERMINISTIC,
            check="residual",
            detail="no deterministic check accounts for this",
            attributed=False,
        )
    )
    batch.trace.append(
        TraceEntry(
            stage="decompose",
            action="residual",
            detail=f"{format_inr(Paise(residual))} unattributed after all five checks",
        )
    )

    return ExceptionReport(
        id="",
        kind=ExceptionKind.UNEXPLAINED_RESIDUE,
        amount=Paise(residual),
        settlement_id=batch.settlement_id,
        what=f"{format_inr(Paise(residual))} of {batch.settlement_id}'s "
        f"{format_inr(batch.headline_gap)} gap is not accounted for by fees, GST, "
        f"adjustments, adjacent-cycle refunds or rounding.",
        tried=work.attempts,
        ruled_out=work.ruled_out,
        needs="the payout advice for this settlement, or a Razorpay adjustment ledger "
        "covering this window",
    )
