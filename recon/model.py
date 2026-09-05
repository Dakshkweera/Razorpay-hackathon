"""Typed records for the three input files.

These mirror the source CSVs as closely as possible, including their
inconsistencies. Normalisation into a canonical shape happens in ``recon.ingest``;
this module is deliberately faithful to what is on disk.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from recon.money import Paise


class RowType(StrEnum):
    PAYMENT = "payment"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class SettlementRow(BaseModel):
    """One line of the Razorpay settlement report.

    ``amount`` is signed: payments positive, refunds and adjustments negative.
    ``fee`` and ``tax`` are always non-negative deductions and are charged on
    payments only.
    """

    model_config = ConfigDict(frozen=True)

    settlement_id: str
    payment_id: str
    order_id: str = ""
    type: RowType
    amount: Paise
    fee: Paise = Field(default=0)
    tax: Paise = Field(default=0)
    settled_at: datetime
    utr: str


class OrderRow(BaseModel):
    """One line of the merchant's own order records.

    ``payment_ref`` is deliberately unreliable: some rows carry a ``pay_*`` id, some
    carry a bare UTR, and some are empty. Resolving that is part of the work.
    """

    model_config = ConfigDict(frozen=True)

    order_id: str
    order_amount: Paise
    status: str
    created_at: datetime
    refunded_amount: Paise = Field(default=0)
    payment_ref: str = ""


class BankRow(BaseModel):
    """One line of the bank statement. Narration format varies per row by design."""

    model_config = ConfigDict(frozen=True)

    date: date
    narration: str
    debit: Paise = Field(default=0)
    credit: Paise = Field(default=0)
    balance: Paise = Field(default=0)
    ref: str


class MdrPeriod(BaseModel):
    """A contracted merchant discount rate, valid over a date range."""

    model_config = ConfigDict(frozen=True)

    effective_from: date
    effective_to: date
    mdr_bps: int
    label: str = ""


class Contract(BaseModel):
    """The merchant's pricing contract — an input file, not a hardcoded constant.

    Keeping this as data is what makes a fee-rate-drift finding checkable: the system
    can point at the clause it was recomputing against instead of asserting a number.
    """

    model_config = ConfigDict(frozen=True)

    merchant_id: str
    gst_bps: int
    mdr_schedule: tuple[MdrPeriod, ...]

    def mdr_bps_on(self, when: date) -> int:
        for period in self.mdr_schedule:
            if period.effective_from <= when <= period.effective_to:
                return period.mdr_bps
        raise LookupError(f"no contracted MDR covers {when.isoformat()}")
