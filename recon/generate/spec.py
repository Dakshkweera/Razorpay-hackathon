"""Declarative description of the synthetic dataset.

Every defect the reconciler is expected to find is planted here and nowhere else.
Keeping it declarative means the planted-case table in the PRD and the data on disk
cannot drift apart: :data:`CASES` is checked against what :mod:`recon.generate.build`
actually produced before ``truth.json`` is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

#: The contracted rate. A batch whose ``mdr_bps`` differs from this is drifting.
CONTRACT_MDR_BPS = 80
GST_BPS = 1800
MERCHANT_ID = "acct_MERCH9KP2"

#: Bank narration templates. Real statements vary format per row and per channel;
#: this is where the LLM earns its place in stage 2.
NARRATION_STYLES: dict[str, str] = {
    "neft_full": "NEFT-RAZORPAY SOFTWARE PVT-UTR{utr}-SETTLEMENT",
    "rzpy_short": "NEFT-RZPY-{utr} STTL",
    "star": "NEFT RAZORPAY*{utr}",
    "rtgs": "RTGS/RAZORPAYSOFTWARE/{utr}/SETTLEMENT",
    "imps": "IMPS-{utr}-RAZORPAY SOFTWARE PRIVATE LIMITED",
    "with_settlement_id": "NEFT CR-RATN0000088-RAZORPAY SOFTWARE PVT LTD-{settlement_id}-REF{utr_garbled}",
    "garbled": "NEFT-RZPY-{utr_garbled} STTL/CR",
    "bare": "NEFT CR RAZORPAY SOFTWARE PVT LTD SETTLEMENT",
}


def _utc(day: str, hhmm: str = "11:02") -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=timezone.utc)


@dataclass(frozen=True)
class BatchSpec:
    settlement_id: str
    utr: str
    settled_at: datetime
    window_start: date
    window_end: date

    payments: int
    refunds: int = 0
    adjustments: int = 0

    #: The rate actually charged on this batch. Differs from CONTRACT_MDR_BPS only
    #: where fee-rate drift is deliberately planted.
    mdr_bps: int = CONTRACT_MDR_BPS

    narration_style: str = "neft_full"
    #: Days between ``settled_at`` and the bank posting. Non-zero forces the matcher
    #: past the same-date rule R3 and onto the +/-2 day rule R4.
    bank_lag_days: int = 0
    emits_bank_line: bool = True

    #: This batch carries a refund row that belongs in the named batch's window, and
    #: whose value was deducted from that batch's payout rather than this one's.
    cross_cycle_for: str | None = None
    cross_cycle_amount: int = 0

    #: The bank truncates the payout to whole rupees, leaving a sub-rupee residue.
    round_payout_to_rupee: bool = False
    #: Money that simply does not arrive, with no cause anywhere in the inputs.
    unexplained: int = 0

    #: Amounts are copied from this batch so the two look identical to the matcher.
    clone_amounts_from: str | None = None

    cases: list[int] = field(default_factory=list)
    note: str = ""


BATCHES: tuple[BatchSpec, ...] = (
    BatchSpec(
        settlement_id="setl_A1F3",
        utr="402913847562",
        settled_at=_utc("2026-08-03"),
        window_start=date(2026, 7, 31),
        window_end=date(2026, 8, 2),
        payments=30,
        narration_style="neft_full",
        cases=[1],
        note="Clean batch. UTR present and readable; nothing but fees and GST to explain.",
    ),
    BatchSpec(
        settlement_id="setl_B2K7",
        utr="402913847999",
        settled_at=_utc("2026-08-05"),
        window_start=date(2026, 8, 3),
        window_end=date(2026, 8, 4),
        payments=32,
        refunds=3,
        narration_style="rzpy_short",
        round_payout_to_rupee=True,
        cases=[2, 7],
        note="Fees, GST and a sub-rupee payout truncation. A duplicate bank posting "
        "repeats this UTR and must be flagged rather than counted twice.",
    ),
    BatchSpec(
        settlement_id="setl_C3M9",
        utr="402914001233",
        settled_at=_utc("2026-08-06"),
        window_start=date(2026, 8, 5),
        window_end=date(2026, 8, 5),
        payments=28,
        refunds=2,
        narration_style="star",
        cases=[3],
        note="Short by a refund that belongs in this window but was documented in the "
        "next cycle's report.",
    ),
    BatchSpec(
        settlement_id="setl_D4P2",
        utr="402914118876",
        settled_at=_utc("2026-08-07"),
        window_start=date(2026, 8, 6),
        window_end=date(2026, 8, 6),
        payments=30,
        refunds=2,
        adjustments=1,
        narration_style="with_settlement_id",
        cross_cycle_for="setl_C3M9",
        cross_cycle_amount=394700,
        cases=[3],
        note="Carries the previous cycle's refund row. Its UTR is corrupted in the "
        "narration but the settlement id is printed verbatim, so R2 should fire.",
    ),
    BatchSpec(
        settlement_id="setl_E5R8",
        utr="402914203451",
        settled_at=_utc("2026-08-10"),
        window_start=date(2026, 8, 7),
        window_end=date(2026, 8, 9),
        payments=34,
        refunds=3,
        adjustments=1,
        mdr_bps=120,
        narration_style="rtgs",
        unexplained=180000,
        cases=[4, 10],
        note="The demo batch. Fee charged at 1.20% against a contracted 0.80%, an "
        "unlinked adjustment, and Rs 1,800 that nothing in any of the three "
        "files accounts for.",
    ),
    BatchSpec(
        settlement_id="setl_F6T1",
        utr="402914330098",
        settled_at=_utc("2026-08-12"),
        window_start=date(2026, 8, 10),
        window_end=date(2026, 8, 11),
        payments=28,
        refunds=2,
        narration_style="garbled",
        bank_lag_days=1,
        cases=[5],
        note="Narration mangled past the point where the UTR can be read, and the "
        "bank posted a day late. Only amount-within-two-days can reach it, so "
        "this batch is deliberately left free of any other discrepancy - a "
        "shifted credit would put it out of reach of every rule.",
    ),
    BatchSpec(
        settlement_id="setl_G7V4",
        utr="402914455512",
        settled_at=_utc("2026-08-13"),
        window_start=date(2026, 8, 12),
        window_end=date(2026, 8, 12),
        payments=24,
        refunds=1,
        narration_style="bare",
        cases=[6],
        note="Identical net amount and date to setl_H8X6, and neither bank line "
        "carries an identifier. Two candidates is not a match.",
    ),
    BatchSpec(
        settlement_id="setl_H8X6",
        utr="402914455513",
        settled_at=_utc("2026-08-13"),
        window_start=date(2026, 8, 12),
        window_end=date(2026, 8, 12),
        payments=24,
        refunds=1,
        narration_style="bare",
        clone_amounts_from="setl_G7V4",
        cases=[6],
        note="The twin of setl_G7V4.",
    ),
    BatchSpec(
        settlement_id="setl_J9Z0",
        utr="402914502277",
        settled_at=_utc("2026-08-14"),
        window_start=date(2026, 8, 13),
        window_end=date(2026, 8, 13),
        payments=26,
        refunds=2,
        emits_bank_line=False,
        cases=[9],
        note="Settled but never credited within the statement period. Almost certainly "
        "timing, but the system is not entitled to assume that.",
    ),
)


@dataclass(frozen=True)
class BankNoiseRow:
    """Non-Razorpay statement traffic, so narration parsing has something to reject."""

    ref: str
    day: date
    narration: str
    debit: int = 0
    credit: int = 0


BANK_NOISE: tuple[BankNoiseRow, ...] = (
    BankNoiseRow("N0029", date(2026, 8, 4), "NEFT DR-HDFC0000123-CLOUDSPEND TECHNOLOGIES-INVOICE 2291", debit=1849900),
    BankNoiseRow("N0036", date(2026, 8, 6), "UPI/DR/619283746152/AWS INDIA/HDFC/AMAZON WEB SERV", debit=942300),
    BankNoiseRow("N0044", date(2026, 8, 11), "NEFT CR-ICIC0000455-STRIPE PAYMENTS INDIA-UTR911002345678", credit=2210000),
    BankNoiseRow("N0051", date(2026, 8, 13), "SALARY DR AUG 2026 BULK TRANSFER 41 EMPLOYEES", debit=38400000),
)

#: A credit that looks like a settlement and reconciles to nothing at all.
ORPHAN_UTR = "402914777001"
ORPHAN_AMOUNT = 88015000
ORPHAN_DAY = date(2026, 8, 11)

OPENING_BALANCE = 891234000

#: The PRD's planted-case table, restated so it can be scored rather than asserted.
CASE_TABLE: tuple[tuple[int, str, str], ...] = (
    (1, "Clean batch, UTR matches", "matched by R1, residual 0"),
    (2, "Fees and GST only", "gap fully decomposed, residual 0"),
    (3, "Refund settled in next cycle", "found by adjacent-cycle search, both ends resolved"),
    (4, "Fee charged at 1.2% vs contracted 0.8%", "flagged as fee_rate_drift"),
    (5, "Garbled narration, UTR unreadable", "matched on amount within +/-2 days, lower confidence"),
    (6, "Two batches, identical amount, same day", "ambiguous - exception, not a guess"),
    (7, "Duplicate UTR across two bank lines", "flagged, not double-counted"),
    (8, "Bank credit with no settlement at all", "exception"),
    (9, "Settlement with no bank credit", "exception, marked likely timing"),
    (10, "Genuinely unexplainable Rs 1,800", "exception, no invented cause"),
)
