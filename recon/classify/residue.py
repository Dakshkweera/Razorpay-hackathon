"""Stage 4b - asking a model about whatever survives the five deterministic checks.

This is deliberately its own module, downstream of :mod:`recon.decompose`, and never
imported by it: decompose's own docstring says the LLM has no business there, because
every number it produces is recomputed, not inferred. This module changes no amount.
The residual paise value stays exactly what the five checks left behind; all a
classification can do is attach a label, a confidence, and a reasoning string to a
component and an exception that already exist.

Below the threshold, nothing about the report changes except that it can now say a
model looked and still could not name a cause - which is a stronger claim than "no
model was asked." At or above it, the same is true in reverse: an honest classification
is recorded as such, not silently folded into "unexplained."
"""

from __future__ import annotations

import json
from typing import Any

from recon.llm.base import LlmError, LlmProvider
from recon.report import (
    Attempt,
    BatchReport,
    ComponentKind,
    ComponentSource,
    ExceptionKind,
    ExceptionReport,
)

#: Below this, a proposed classification is refused and the residue stays "unexplained".
#: The PRD states this number explicitly; match.rules.MATCH_COMMIT_THRESHOLD is the
#: analogous constant for Stage 3.
RESIDUE_CONFIDENCE_THRESHOLD = 0.70

_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["label", "confidence", "reasoning"],
}

_CLASSIFICATION_SYSTEM = (
    "You are the last step of a settlement reconciliation pipeline. A residual amount "
    "has survived five deterministic checks: fee recomputation, GST verification, "
    "unlinked adjustments, adjacent-cycle refund search, and a rounding bound. You are "
    "given exactly what each check found and ruled out. Propose a classification only "
    "if the evidence in front of you actually supports one - do not reason from what a "
    "gap of this kind is usually caused by in general. If nothing in the supplied "
    "evidence points to a specific cause, say so plainly and give a low confidence. "
    "Confidence must reflect how well-supported your answer is by the evidence given, "
    "not how plausible it sounds."
)


def _context(batch: BatchReport, exception: ExceptionReport) -> dict[str, Any]:
    return {
        "settlement_id": batch.settlement_id,
        "residual_paise": int(batch.residual),
        "headline_gap_paise": int(batch.headline_gap),
        "tried": [
            {"check": attempt.check, "outcome": attempt.outcome}
            for attempt in exception.tried
        ],
        "ruled_out": [
            {"check": entry.check, "reason": entry.reason} for entry in exception.ruled_out
        ],
        "components_already_attributed": [
            {"kind": component.kind.value, "amount_paise": int(component.amount)}
            for component in batch.components
            if component.attributed and component.kind is not ComponentKind.UNEXPLAINED
        ],
    }


class ResidueClassification:
    __slots__ = ("label", "confidence", "reasoning")

    def __init__(self, label: str, confidence: float, reasoning: str) -> None:
        self.label = label
        self.confidence = max(0.0, min(1.0, confidence))
        self.reasoning = reasoning


def classify(batch: BatchReport, exception: ExceptionReport, provider: LlmProvider) -> ResidueClassification | None:
    """One call, one batch. Returns ``None`` only if the provider itself fails."""
    try:
        response = provider.complete_json(
            schema_name="residue_classification_v1",
            schema=_CLASSIFICATION_SCHEMA,
            system=_CLASSIFICATION_SYSTEM,
            user=json.dumps(_context(batch, exception), sort_keys=True),
        )
        return ResidueClassification(
            label=str(response["label"]),
            confidence=float(response["confidence"]),
            reasoning=str(response["reasoning"]),
        )
    except (LlmError, KeyError, TypeError, ValueError):
        return None


def apply(
    batches: list[BatchReport],
    exceptions: list[ExceptionReport],
    provider: LlmProvider | None,
) -> None:
    """Consult the model for every unresolved residue, in place.

    Skipped entirely when ``provider`` is ``None`` (``LlmMode.OFF``): the residue
    component and exception decompose already built stand exactly as they were,
    honestly labelled "unexplained" with no model consulted.
    """
    if provider is None:
        return

    exceptions_by_settlement = {
        exception.settlement_id: exception
        for exception in exceptions
        if exception.kind is ExceptionKind.UNEXPLAINED_RESIDUE
    }

    for batch in batches:
        if int(batch.residual) == 0:
            continue
        exception = exceptions_by_settlement.get(batch.settlement_id)
        component = next(
            (c for c in batch.components if c.kind is ComponentKind.UNEXPLAINED), None
        )
        if exception is None or component is None:
            continue

        result = classify(batch, exception, provider)
        if result is None:
            continue

        attributed = result.confidence >= RESIDUE_CONFIDENCE_THRESHOLD
        component.source = ComponentSource.LLM
        component.confidence = result.confidence
        component.attributed = attributed
        component.detail = f"{result.label}: {result.reasoning}"

        exception.confidence = result.confidence
        exception.threshold = RESIDUE_CONFIDENCE_THRESHOLD
        verdict = (
            f"The classifier proposed \"{result.label}\" at confidence "
            f"{result.confidence:.2f}"
        )
        exception.what += (
            f" {verdict}, at or above the {RESIDUE_CONFIDENCE_THRESHOLD:.2f} threshold: "
            f"{result.reasoning}"
            if attributed
            else f" {verdict}, below the {RESIDUE_CONFIDENCE_THRESHOLD:.2f} threshold - "
            "not attributed."
        )
        exception.tried.append(
            Attempt(
                check="LLM residue classification",
                outcome=f"proposed {result.label!r} at confidence {result.confidence:.2f}",
                attributed=batch.residual if attributed else None,
            )
        )
