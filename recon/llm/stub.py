"""A deterministic, offline stand-in for a real model.

This is what runs in tests and what backs :data:`~recon.report.LlmMode.STUB` and the
fallback half of :data:`~recon.report.LlmMode.CACHE`. It exists so the pipeline is
never *required* to hold an API key or a network connection to produce a report: every
test in this repository, and a demo run with no fixtures yet committed, exercises the
same code paths a live Perplexity call would.

It is deliberately conservative rather than clever. A stub that guessed aggressively
would let "the pipeline works offline" quietly become "the pipeline invents answers
offline," which is exactly the failure mode this whole project is built to catch. Where
a real model might notice something a rule-based heuristic cannot, this one says so
honestly at low confidence instead.
"""

from __future__ import annotations

import json
import re
from typing import Any

from recon.llm.base import LlmError

_MIN_REFERENCE_DIGITS = 9
_DIGIT_RUN = re.compile(rf"\d{{{_MIN_REFERENCE_DIGITS},}}")
_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "S": "5"})

_COUNTERPARTY_TOKENS: tuple[tuple[str, str], ...] = (
    ("razorpay", "razorpay"),
    ("rzpy", "razorpay"),
    ("rzp ", "razorpay"),
    ("stripe", "stripe"),
    ("payu", "payu"),
    ("cashfree", "cashfree"),
)
_SETTLEMENT_TOKENS = ("settlement", "sttl", "stl ", "payout")

#: A handful of the header spellings a merchant export drifts into. The point is to
#: demonstrate the fallback path exists, not to enumerate every possible header.
_HEADER_ALIASES: dict[str, str] = {
    "txn_id": "payment_id",
    "transaction_id": "payment_id",
    "payment_ref": "payment_ref",
    "settlement_ref": "settlement_id",
    "utr_number": "utr",
    "utrno": "utr",
    "order_no": "order_id",
    "orderid": "order_id",
    "amt": "amount",
    "gst": "tax",
    "narrative": "narration",
    "txn_date": "settled_at",
    "value_date": "date",
    "cr": "credit",
    "dr": "debit",
    "closing_balance": "balance",
}


def _guess_narration(key: str) -> dict[str, Any]:
    lowered = key.lower()
    counterparty = next((name for token, name in _COUNTERPARTY_TOKENS if token in lowered), None)

    exact = _DIGIT_RUN.findall(key)
    if exact:
        return {
            "key": key,
            "utr": exact[0],
            "counterparty": counterparty,
            "kind": "settlement" if counterparty == "razorpay" else "unknown",
            "confidence": 0.6,
        }

    # A run broken by lookalike glyphs (O/I/S for 0/1/5) can be reconstructed; a run
    # broken by a literal gap (bank exports truncating with "####" or similar) cannot,
    # and claiming otherwise would be exactly the fabrication this stub exists to avoid.
    if any(marker in key for marker in ("#", "*" * 3, "X" * 4)):
        return {
            "key": key,
            "utr": None,
            "counterparty": counterparty,
            "kind": "settlement" if counterparty == "razorpay" else "unknown",
            "confidence": 0.3,
        }

    recovered = _DIGIT_RUN.findall(key.translate(_LOOKALIKE))
    if recovered:
        return {
            "key": key,
            "utr": recovered[0],
            "counterparty": counterparty,
            "kind": "settlement" if counterparty == "razorpay" else "unknown",
            "confidence": 0.75,
        }

    settlement_like = counterparty == "razorpay" and any(
        token in lowered for token in _SETTLEMENT_TOKENS
    )
    return {
        "key": key,
        "utr": None,
        "counterparty": counterparty,
        "kind": "settlement" if settlement_like else ("other_gateway" if counterparty else "unknown"),
        "confidence": 0.5 if settlement_like else 0.2,
    }


def _guess_header(source: str, canonical_names: list[str]) -> dict[str, Any]:
    key = re.sub(r"[^a-z0-9]+", "_", source.strip().lower()).strip("_")
    if key in canonical_names:
        return {"source": source, "canonical": key, "confidence": 0.95}
    if key in _HEADER_ALIASES and _HEADER_ALIASES[key] in canonical_names:
        return {"source": source, "canonical": _HEADER_ALIASES[key], "confidence": 0.8}
    for canonical in canonical_names:
        if canonical in key or key in canonical:
            return {"source": source, "canonical": canonical, "confidence": 0.55}
    return {"source": source, "canonical": None, "confidence": 0.1}


def _guess_residue(payload: dict[str, Any]) -> dict[str, Any]:
    """Refuse by default. See the module docstring for why."""
    amount = abs(int(payload.get("residual_paise", 0)))
    tried = payload.get("tried", [])
    return {
        "label": "unexplained",
        "confidence": 0.3,
        "reasoning": (
            f"{len(tried)} deterministic check(s) already ran and none accounted for this "
            f"{amount} paise; nothing in the narration, contract or order records offers a "
            "corroborating cause, so this is reported as unexplained rather than guessed at."
        ),
    }


class StubProvider:
    name = "stub"

    def __init__(self) -> None:
        self.calls = 0
        self.cache_hits = 0

    def complete_json(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        system: str,
        user: str,
    ) -> dict[str, Any]:
        self.calls += 1
        try:
            payload = json.loads(user)
        except json.JSONDecodeError as error:
            raise LlmError(f"stub provider expects JSON user content: {error}") from error

        if schema_name == "narration_extraction_v1":
            items = payload.get("narrations", [])
            return {"results": [_guess_narration(item["key"]) for item in items]}

        if schema_name == "header_mapping_v1":
            canonical = payload.get("canonical", [])
            unmapped = payload.get("unmapped", [])
            return {"mappings": [_guess_header(source, canonical) for source in unmapped]}

        if schema_name == "residue_classification_v1":
            return _guess_residue(payload)

        raise LlmError(f"stub provider has no heuristic for schema {schema_name!r}")
