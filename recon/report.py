"""The report contract.

Everything the pipeline learns ends up in these models, and the UI's TypeScript
types are generated from their JSON Schema. That makes this file the single point
where the engine and the screen agree: rename a field here and the UI stops
compiling, rather than silently rendering ``undefined`` during a demo.

The shape is complete from day one even though the later stages do not populate it
yet. Fields fill in; the structure does not move.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from recon.money import Paise

SCHEMA_VERSION = "1.0.0"


# --------------------------------------------------------------------------- #
# Stage 1 - ingest
# --------------------------------------------------------------------------- #

class MappingMethod(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    LLM = "llm"


class ColumnMapping(BaseModel):
    source: str
    canonical: str
    method: MappingMethod
    confidence: float = 1.0


class NormaliseReport(BaseModel):
    file: str
    rows_read: int
    rows_rejected: int
    rejections: list[str] = Field(default_factory=list)
    columns_mapped: list[ColumnMapping] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Stage 3 - matching
# --------------------------------------------------------------------------- #

class MatchRule(StrEnum):
    R1 = "R1"  # settlement UTR equals the UTR read off the bank line
    R2 = "R2"  # settlement id appears verbatim in the narration
    R3 = "R3"  # exact net amount, same date
    R4 = "R4"  # exact net amount, within +/- 2 days
    NONE = "none"


class MatchOrigin(StrEnum):
    #: Reachable with no model in the loop at all.
    DETERMINISTIC = "deterministic"
    #: Reachable only because the LLM recovered an identifier from a narration.
    #: This distinction is what makes the AI's contribution a measured delta.
    INFERENCE = "inference"
    NONE = "none"


class Match(BaseModel):
    rule: MatchRule = MatchRule.NONE
    origin: MatchOrigin = MatchOrigin.NONE
    confidence: float = 0.0
    basis: str = ""
    bank_ref: str | None = None
    candidates_considered: int = 0
    rejected_reason: str | None = None


# --------------------------------------------------------------------------- #
# Stage 4 - gap decomposition
# --------------------------------------------------------------------------- #

class ComponentKind(StrEnum):
    FEE = "fee"
    GST_ON_FEE = "gst_on_fee"
    FEE_RATE_DRIFT = "fee_rate_drift"
    CROSS_CYCLE_REFUND = "cross_cycle_refund"
    UNLINKED_ADJUSTMENT = "unlinked_adjustment"
    ROUNDING = "rounding"
    UNEXPLAINED = "unexplained"


class ComponentSource(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"


class GapComponent(BaseModel):
    kind: ComponentKind
    amount: Paise
    source: ComponentSource
    check: str
    detail: str = ""
    confidence: float | None = None
    #: False when a proposed cause scored below threshold. The component is still
    #: reported - refusing to attribute is a result, not an absence of one.
    attributed: bool = True


class TraceEntry(BaseModel):
    """One recorded step. Every conclusion traces back to one of these."""

    stage: str
    action: str
    detail: str = ""


class NarrationRead(BaseModel):
    """What was read off one bank line, and by what.

    ``source`` is the point of this record: it distinguishes what a regular expression
    could see from what a model was needed for, which is how the AI's contribution
    stops being a claim and becomes a number.
    """

    ref: str
    raw: str
    utrs: list[str] = Field(default_factory=list)
    counterparty: str | None = None
    kind: str = "unknown"
    confidence: float = 0.0
    source: str = "regex"
    notes: list[str] = Field(default_factory=list)
    matched_settlement_id: str | None = None


# --------------------------------------------------------------------------- #
# Batches
# --------------------------------------------------------------------------- #

class BatchReport(BaseModel):
    settlement_id: str
    utr: str
    settled_at: datetime
    window_start: date
    window_end: date

    row_count: int = 0
    payment_count: int = 0
    refund_count: int = 0
    adjustment_count: int = 0

    #: Sum of signed settlement amounts, before fee and tax.
    gross_settled: Paise = 0
    total_fee: Paise = 0
    total_tax: Paise = 0
    #: What the settlement file itself implies should arrive: gross - fee - tax.
    settlement_expected_credit: Paise = 0
    #: What the merchant's own order records imply should arrive. The two disagree,
    #: and the difference is what this whole system exists to explain.
    orders_expected: Paise = 0

    bank_ref: str | None = None
    bank_credit: Paise | None = None
    bank_narration: str | None = None
    bank_date: date | None = None

    match: Match = Field(default_factory=Match)

    #: orders_expected - bank_credit. The number a merchant actually stares at.
    headline_gap: Paise = 0
    #: settlement_expected_credit - bank_credit. Zero unless something is genuinely
    #: wrong with the settlement itself.
    settlement_residual: Paise = 0

    components: list[GapComponent] = Field(default_factory=list)
    explained: Paise = 0
    residual: Paise = 0

    trace: list[TraceEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #

class ExceptionKind(StrEnum):
    AMBIGUOUS_MATCH = "ambiguous_match"
    DUPLICATE_UTR = "duplicate_utr"
    UNMATCHED_BANK_CREDIT = "unmatched_bank_credit"
    UNMATCHED_SETTLEMENT = "unmatched_settlement"
    UNEXPLAINED_RESIDUE = "unexplained_residue"


class Attempt(BaseModel):
    check: str
    outcome: str
    attributed: Paise | None = None


class RuledOut(BaseModel):
    check: str
    reason: str


class ExceptionReport(BaseModel):
    """An honest exception, built to be actionable rather than a dump.

    ``tried`` and ``ruled_out`` are what separate "we could not explain this" from
    "we did not look". A finance team can act on the first and cannot act on the
    second.
    """

    id: str
    kind: ExceptionKind
    amount: Paise
    settlement_id: str | None = None
    bank_ref: str | None = None
    what: str
    tried: list[Attempt] = Field(default_factory=list)
    ruled_out: list[RuledOut] = Field(default_factory=list)
    needs: str = ""
    confidence: float | None = None
    threshold: float | None = None
    candidates: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Scoreboard
# --------------------------------------------------------------------------- #

class Count(BaseModel):
    n: int = 0
    pct: float = 0.0


class Scoreboard(BaseModel):
    records_processed: int = 0
    settlement_rows: int = 0
    order_rows: int = 0
    bank_rows: int = 0
    settlement_batches: int = 0
    runtime_ms: int = 0

    matched_deterministic: Count = Field(default_factory=Count)
    matched_inference: Count = Field(default_factory=Count)
    unmatched: Count = Field(default_factory=Count)

    gap_total: Paise = 0
    gap_explained: Paise = 0
    gap_unexplained: Paise = 0
    gap_explained_pct: float = 0.0
    gap_unexplained_pct: float = 0.0

    #: The two numbers the submission actually rests on.
    false_matches: int = 0
    false_cause_attributions: int = 0


# --------------------------------------------------------------------------- #
# Evaluation against planted truth
# --------------------------------------------------------------------------- #

class Verdict(StrEnum):
    CORRECT = "correct"
    MISSED = "missed"
    OVER_ATTRIBUTED = "over_attributed"
    FALSE_CAUSE = "false_cause"


class EvalComponent(BaseModel):
    kind: ComponentKind
    truth_amount: Paise
    reported_amount: Paise
    verdict: Verdict


class EvalBatch(BaseModel):
    settlement_id: str
    truth_gap: Paise
    reported_gap: Paise
    components: list[EvalComponent] = Field(default_factory=list)
    passed: bool = False


class CaseStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    #: The stage that would decide this case is not built yet. Reported as its own
    #: state rather than as a failure, so a partial build cannot be read as a broken one.
    PENDING = "pending"


class EvalCase(BaseModel):
    """One of the planted cases from the PRD's table, scored explicitly."""

    number: int
    name: str
    expected: str
    actual: str
    status: CaseStatus


class EvalReport(BaseModel):
    batches: list[EvalBatch] = Field(default_factory=list)
    cases: list[EvalCase] = Field(default_factory=list)
    cases_passed: int = 0
    cases_failed: int = 0
    cases_pending: int = 0
    cases_total: int = 0
    false_matches: int = 0
    false_cause_attributions: int = 0
    gap_accuracy_pct: float = 0.0


# --------------------------------------------------------------------------- #
# Top level
# --------------------------------------------------------------------------- #

class LlmMode(StrEnum):
    STUB = "stub"
    CACHE = "cache"
    LIVE = "live"
    OFF = "off"


class RunMeta(BaseModel):
    schema_version: str = SCHEMA_VERSION
    seed: int = 0
    data_dir: str = ""
    #: Volatile. Excluded from ``deterministic_hash`` because wall-clock time is not
    #: a property of the reconciliation.
    run_at: datetime | None = None
    runtime_ms: int = 0
    llm_provider: str = "none"
    llm_mode: LlmMode = LlmMode.OFF
    llm_calls: int = 0
    llm_cache_hits: int = 0
    #: SHA-256 over the report with volatile fields stripped. Two runs on the same
    #: input must produce the same value.
    deterministic_hash: str = ""


class UnmatchedBankRow(BaseModel):
    ref: str
    date: date
    credit: Paise
    narration: str
    reason: str


class Report(BaseModel):
    meta: RunMeta = Field(default_factory=RunMeta)
    normalise: list[NormaliseReport] = Field(default_factory=list)
    narrations: list[NarrationRead] = Field(default_factory=list)
    batches: list[BatchReport] = Field(default_factory=list)
    unmatched_bank_rows: list[UnmatchedBankRow] = Field(default_factory=list)
    exceptions: list[ExceptionReport] = Field(default_factory=list)
    scoreboard: Scoreboard = Field(default_factory=Scoreboard)
    evaluation: EvalReport | None = None
