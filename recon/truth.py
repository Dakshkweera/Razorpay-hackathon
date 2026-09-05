"""Planted ground truth.

The generator writes this alongside the three CSVs. The reconciler never reads it;
only ``recon.evaluate`` does, after the run is finished. That separation is the
entire basis for claiming a measured match rate rather than an asserted one.

If you find yourself importing this module anywhere under ``recon.ingest``,
``recon.match``, ``recon.decompose`` or ``recon.classify``, something has gone
wrong and the numbers stop meaning anything.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from recon.money import Paise
from recon.report import ComponentKind


class TruthComponent(BaseModel):
    """One planted contributor to a batch's headline gap."""

    kind: ComponentKind
    amount: Paise
    #: False for the deliberately unexplainable residue. A system that "explains" a
    #: component marked undetectable has hallucinated a cause, which is the single
    #: worst outcome this project measures.
    detectable: bool = True
    note: str = ""


class TruthBatch(BaseModel):
    settlement_id: str
    utr: str
    settled_at: datetime
    window_start: date
    window_end: date

    gross_settled: Paise
    total_fee: Paise
    total_tax: Paise
    orders_expected: Paise

    bank_ref: str | None = None
    bank_credit: Paise | None = None

    #: ``None`` when no credit arrived at all. A batch that was never paid has no gap
    #: to decompose; the correct output is an exception, not an attribution.
    expected_gap: Paise | None = None
    components: list[TruthComponent] = Field(default_factory=list)

    #: What matching should conclude. ``None`` means no match is the correct answer.
    expected_rule: str | None = None
    expected_outcome: str = ""
    #: Planted case numbers exercised by this batch, per the PRD's table.
    cases: list[int] = Field(default_factory=list)


class TruthCase(BaseModel):
    """One row of the PRD's planted-case table, made machine-checkable."""

    number: int
    name: str
    expected: str
    settlement_ids: list[str] = Field(default_factory=list)
    bank_refs: list[str] = Field(default_factory=list)


class Truth(BaseModel):
    seed: int
    contract_file: str
    settlement_rows: int
    order_rows: int
    bank_rows: int
    total_expected_gap: Paise
    total_detectable: Paise
    total_undetectable: Paise
    batches: list[TruthBatch] = Field(default_factory=list)
    cases: list[TruthCase] = Field(default_factory=list)
