"""Stage 1b - resolving column headers that do not match the canonical schema exactly.

Three tiers, cheapest and most certain first:

1. **Exact** - the header already is the canonical name.
2. **Alias** - a known synonym (``txn_id`` for ``payment_id``, and so on), matched by
   a fixed table. Free, deterministic, and covers most real-world schema drift.
3. **LLM** - whatever is left, resolved in one call per file rather than one per
   column, because a merchant's export does not rename one column at a time.

This module never changes a value, only which key a value is filed under. Every
resolution - however it was reached - is recorded as a :class:`~recon.report.ColumnMapping`
so a normalise report can show exactly which columns were guessed at and how
confidently, rather than silently accepting a model's opinion of the merchant's schema.
"""

from __future__ import annotations

import json
import re
from typing import Any

from recon.llm.base import LlmError, LlmProvider
from recon.report import ColumnMapping, MappingMethod

#: A handful of the header spellings a real export drifts into. Not exhaustive by
#: design - exhaustive is what the LLM tier is for.
ALIASES: dict[str, str] = {
    "txn_id": "payment_id",
    "transaction_id": "payment_id",
    "settlement_ref": "settlement_id",
    "settlement_no": "settlement_id",
    "utr_number": "utr",
    "utrno": "utr",
    "utr_no": "utr",
    "order_no": "order_id",
    "orderid": "order_id",
    "amt": "amount",
    "gross_amount": "amount",
    "row_type": "type",
    "gst": "tax",
    "gst_amount": "tax",
    "narrative": "narration",
    "description": "narration",
    "particulars": "narration",
    "txn_date": "settled_at",
    "settlement_date": "settled_at",
    "value_date": "date",
    "posting_date": "date",
    "cr": "credit",
    "dr": "debit",
    "closing_balance": "balance",
    "order_value": "order_amount",
    "payment_reference": "payment_ref",
    "refund_amount": "refunded_amount",
}

_MAPPING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "canonical": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["source", "canonical", "confidence"],
            },
        },
    },
    "required": ["mappings"],
}

_MAPPING_SYSTEM = (
    "You map spreadsheet column headers from a settlement reconciliation export onto "
    "a fixed canonical schema. For each header, return the canonical name it most "
    "likely corresponds to, or null if none of the canonical names plausibly match. "
    "Never invent a canonical name that is not in the list you were given."
)


def _slug(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def resolve_headers(
    fieldnames: list[str],
    canonical: list[str],
    provider: LlmProvider | None = None,
) -> tuple[dict[str, str], list[ColumnMapping]]:
    """Resolve one file's header row. Called once per file, never once per row.

    Returns a ``source -> canonical`` rename map (only for headers that resolved to a
    known canonical column) and the full :class:`ColumnMapping` trail, unresolved
    headers included, so the caller can decide how to handle what is left over.
    """
    canonical_set = set(canonical)
    resolved: dict[str, str] = {}
    mappings: list[ColumnMapping] = []
    unresolved: list[str] = []

    for header in fieldnames:
        slug = _slug(header)
        if header in canonical_set:
            resolved[header] = header
            mappings.append(ColumnMapping(source=header, canonical=header, method=MappingMethod.EXACT))
        elif slug in canonical_set:
            resolved[header] = slug
            mappings.append(ColumnMapping(source=header, canonical=slug, method=MappingMethod.EXACT))
        elif ALIASES.get(slug) in canonical_set:
            target = ALIASES[slug]
            resolved[header] = target
            mappings.append(
                ColumnMapping(source=header, canonical=target, method=MappingMethod.ALIAS)
            )
        else:
            unresolved.append(header)

    if unresolved and provider is not None:
        mappings.extend(_resolve_via_llm(unresolved, canonical, provider, resolved))
    else:
        mappings.extend(
            ColumnMapping(source=header, canonical=header, method=MappingMethod.EXACT, confidence=0.0)
            for header in unresolved
        )

    return resolved, mappings


def _resolve_via_llm(
    unresolved: list[str],
    canonical: list[str],
    provider: LlmProvider,
    resolved: dict[str, str],
) -> list[ColumnMapping]:
    request = json.dumps(
        {"unmapped": unresolved, "canonical": sorted(canonical)}, sort_keys=True
    )
    out: list[ColumnMapping] = []
    try:
        response = provider.complete_json(
            schema_name="header_mapping_v1",
            schema=_MAPPING_SCHEMA,
            system=_MAPPING_SYSTEM,
            user=request,
        )
    except LlmError:
        return [
            ColumnMapping(source=header, canonical=header, method=MappingMethod.EXACT, confidence=0.0)
            for header in unresolved
        ]

    by_source = {item["source"]: item for item in response.get("mappings", [])}
    for header in unresolved:
        item = by_source.get(header)
        target = item.get("canonical") if item else None
        confidence = float(item.get("confidence", 0.0)) if item else 0.0
        if target and target in canonical:
            resolved[header] = target
            out.append(
                ColumnMapping(
                    source=header, canonical=target, method=MappingMethod.LLM, confidence=confidence
                )
            )
        else:
            out.append(
                ColumnMapping(
                    source=header, canonical=header, method=MappingMethod.LLM, confidence=confidence
                )
            )
    return out
