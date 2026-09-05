"""Reading identifiers out of bank narration strings.

This is the deterministic floor: a regular expression that finds digit runs long
enough to be a UTR, and a keyword scan for the counterparty. It is deliberately built
and measured *before* any model is involved, so that stage 2's LLM can be judged on
what it adds rather than on what it does at all.

What the regex cannot do, and what the LLM is for:

* It over-extracts. ``UTR911002345678`` in a Stripe narration is a perfectly valid
  twelve-digit reference that has nothing to do with a Razorpay settlement. Nothing
  in the digits themselves says otherwise.
* It under-extracts. A UTR mangled into lookalike glyphs (``4O29I433####``) is not a
  digit run at all, and a corrupted tail cannot be recovered by any rule.

The first of those is what makes the counterparty field matter: it shrinks the
candidate pool for the amount-based rules, where an unrelated credit of a coincidentally
equal value is exactly how a false match happens.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from recon.llm.base import LlmError, LlmProvider
from recon.model import BankRow
from recon.narration.cache import NarrationCache

#: Indian bank references (UTR/RRN) run 12 to 22 digits. Nine is a permissive floor
#: that still excludes IFSC fragments and invoice numbers.
_MIN_REFERENCE_DIGITS = 9

#: Narrations per model call. Throughput is a scored metric, so one row per call is
#: never acceptable - see the PRD's Stage 2.
_LLM_BATCH_SIZE = 20

_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "utr": {"type": ["string", "null"]},
                    "counterparty": {"type": ["string", "null"]},
                    "kind": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["key", "utr", "counterparty", "kind", "confidence"],
            },
        },
    },
    "required": ["results"],
}

_EXTRACTION_SYSTEM = (
    "You read bank statement narration lines for a settlement reconciliation system. "
    "For each narration, extract the payout reference number (UTR/RRN/NEFT ref), the "
    "counterparty if identifiable, and whether it looks like a payment gateway "
    "settlement. If part of the reference is missing or replaced with placeholder "
    "characters (####, ***, XXXX), you cannot know those digits - return null for utr "
    "rather than guessing. Confidence must reflect how certain you actually are, not "
    "how plausible your answer sounds."
)

_DIGIT_RUN = re.compile(rf"\d{{{_MIN_REFERENCE_DIGITS},}}")

_COUNTERPARTY_TOKENS: tuple[tuple[str, str], ...] = (
    ("razorpay", "razorpay"),
    ("rzpy", "razorpay"),
    ("rzp ", "razorpay"),
    ("stripe", "stripe"),
    ("payu", "payu"),
    ("cashfree", "cashfree"),
)

_SETTLEMENT_TOKENS = ("settlement", "sttl", "stl ", "payout")


@dataclass(frozen=True)
class Narration:
    """What could be read off one bank line, and how confidently.

    ``utrs`` is the deterministic floor: digit runs a regular expression can point at
    with certainty. ``llm_utrs`` holds references recovered only because a model read
    past a lookalike-glyph corruption a regex cannot - see
    :meth:`~recon.narration.extract.Narration.utr_source`, which is what lets a match
    built on one of these be counted as *inference* rather than *deterministic*.
    """

    ref: str
    raw: str
    utrs: tuple[str, ...] = ()
    llm_utrs: tuple[str, ...] = ()
    counterparty: str | None = None
    kind: str = "unknown"
    confidence: float = 0.0
    source: str = "regex"
    notes: list[str] = field(default_factory=list)

    @property
    def all_utrs(self) -> tuple[str, ...]:
        """Every reference this narration yields, regex first, then LLM-only recoveries."""
        return self.utrs + tuple(utr for utr in self.llm_utrs if utr not in self.utrs)

    def utr_source(self, utr: str) -> str:
        return "regex" if utr in self.utrs else "llm"

    @property
    def looks_like_a_settlement(self) -> bool:
        """Whether this credit is worth raising as a missing settlement.

        A twelve-digit reference alone is not enough - another gateway's payout carries
        one too, and reporting it as an unexplained Razorpay credit would be a false
        alarm dressed up as diligence. An unrecognised counterparty still qualifies:
        not knowing who sent money is a reason to look, not a reason to dismiss.
        """
        if self.counterparty and self.counterparty != "razorpay":
            return False
        return self.kind == "settlement" or bool(self.all_utrs)


def normalise(raw: str) -> str:
    """Collapse a narration to a stable cache key. Real statements repeat formats."""
    return re.sub(r"\s+", " ", raw.strip().upper())


def extract(row: BankRow) -> Narration:
    text = row.narration
    lowered = text.lower()

    counterparty = next(
        (name for token, name in _COUNTERPARTY_TOKENS if token in lowered), None
    )
    utrs = tuple(dict.fromkeys(_DIGIT_RUN.findall(text)))

    if counterparty == "razorpay" and any(token in lowered for token in _SETTLEMENT_TOKENS):
        kind, confidence = "settlement", 0.9 if utrs else 0.6
    elif counterparty == "razorpay":
        kind, confidence = "settlement", 0.7 if utrs else 0.4
    elif counterparty:
        kind, confidence = "other_gateway", 0.5
    else:
        kind, confidence = "unknown", 0.2

    notes: list[str] = []
    if not utrs and counterparty == "razorpay":
        # Either genuinely absent, or mangled past what a rule can read. Both end up
        # at the amount-based rules, which is the honest outcome.
        notes.append("no readable reference in narration")
    if len(utrs) > 1:
        notes.append(f"{len(utrs)} reference-length digit runs present")

    return Narration(
        ref=row.ref,
        raw=text,
        utrs=utrs,
        counterparty=counterparty,
        kind=kind,
        confidence=confidence,
        notes=notes,
    )


def extract_all(rows: list[BankRow]) -> dict[str, Narration]:
    """Read every credit line. Debits are not settlements and are skipped."""
    return {row.ref: extract(row) for row in rows if int(row.credit) > 0}


def _merge(base: Narration, result: dict[str, Any]) -> Narration:
    """Layer one LLM extraction on top of the regex floor. Never weakens it."""
    llm_utr = result.get("utr")
    llm_utrs: tuple[str, ...] = ()
    notes = list(base.notes)
    if (
        isinstance(llm_utr, str)
        and llm_utr.isdigit()
        and len(llm_utr) >= _MIN_REFERENCE_DIGITS
        and llm_utr not in base.utrs
    ):
        llm_utrs = (llm_utr,)
        notes.append(f"LLM recovered reference {llm_utr} from a narration the regex could not read")

    counterparty = base.counterparty or result.get("counterparty")
    kind, confidence, source = base.kind, base.confidence, base.source
    llm_kind = result.get("kind")
    llm_confidence = float(result.get("confidence") or 0.0)

    if llm_utrs:
        kind = llm_kind if llm_kind and llm_kind != "unknown" else kind
        confidence = max(confidence, llm_confidence)
        source = "llm"
    elif base.kind == "unknown" and llm_kind and llm_kind != "unknown":
        kind, confidence, source = llm_kind, max(confidence, llm_confidence), "llm"

    return replace(
        base,
        llm_utrs=llm_utrs,
        counterparty=counterparty,
        kind=kind,
        confidence=confidence,
        source=source,
        notes=notes,
    )


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def extract_all_llm(
    rows: list[BankRow],
    provider: LlmProvider | None,
    cache: NarrationCache | None = None,
) -> dict[str, Narration]:
    """Stage 2: the regex floor first, then a batched LLM pass over what it left unread.

    Only narrations the regex could not resolve to a reference are sent to a model -
    reconfirming an identifier a rule already read with certainty would just be paying
    for an answer this system already has. Batched twenty at a time per the PRD, and
    never re-sent for a narration format :class:`~recon.narration.cache.NarrationCache`
    has already seen, in this run or a previous one.
    """
    base = extract_all(rows)
    if provider is None:
        return base

    cache = cache or NarrationCache()
    candidates = {
        narration.ref: normalise(narration.raw)
        for narration in base.values()
        if not narration.utrs and narration.counterparty in (None, "razorpay")
    }
    if not candidates:
        return base

    pending = sorted({key for key in candidates.values() if cache.get(key) is None})
    for chunk in _chunked(pending, _LLM_BATCH_SIZE):
        request = json.dumps({"narrations": [{"key": key} for key in chunk]}, sort_keys=True)
        try:
            response = provider.complete_json(
                schema_name="narration_extraction_v1",
                schema=_EXTRACTION_SCHEMA,
                system=_EXTRACTION_SYSTEM,
                user=request,
            )
        except LlmError:
            continue  # a failed batch leaves those narrations at the regex floor
        fresh = {
            item["key"]: item for item in response.get("results", []) if item.get("key") in chunk
        }
        cache.put_many(fresh)
    cache.save()

    merged = dict(base)
    for ref, key in candidates.items():
        result = cache.get(key)
        if result is not None:
            merged[ref] = _merge(base[ref], result)
    return merged
