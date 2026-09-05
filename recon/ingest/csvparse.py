"""Stage 1 - parse the three CSVs into typed records.

Rejections are recorded rather than raised. A single malformed row in a real
settlement export should not abort a reconciliation run; it should appear in the
normalise report and be visible in the UI, so the operator can see exactly what was
dropped and why.

Header resolution runs once per file, before any row is parsed - never per row - and
falls through exact match, then a known-alias table, then (only if both fail and a
provider is supplied) one LLM call covering every header still unresolved. See
:mod:`recon.ingest.normalise`.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import TypeVar

from recon.ingest.normalise import resolve_headers
from recon.llm.base import LlmProvider
from recon.model import BankRow, Contract, OrderRow, RowType, SettlementRow
from recon.money import paise
from recon.report import NormaliseReport

Row = TypeVar("Row")

SETTLEMENT_COLUMNS = [
    "settlement_id", "payment_id", "order_id", "type", "amount", "fee", "tax",
    "settled_at", "utr",
]
ORDER_COLUMNS = [
    "order_id", "order_amount", "status", "created_at", "refunded_amount", "payment_ref",
]
BANK_COLUMNS = ["date", "narration", "debit", "credit", "balance", "ref"]


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))


def _parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _read(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _canonicalise(
    raw: list[dict[str, str]], fieldnames: list[str], columns: list[str], provider: LlmProvider | None
) -> tuple[list[dict[str, str]], list]:
    """Rename every row's keys onto the canonical schema, resolved once for the file."""
    rename, mappings = resolve_headers(fieldnames, columns, provider)
    if all(source == target for source, target in rename.items()):
        return raw, mappings
    records = [{rename.get(key, key): value for key, value in record.items()} for record in raw]
    return records, mappings


def read_settlements(
    path: Path, provider: LlmProvider | None = None
) -> tuple[list[SettlementRow], NormaliseReport]:
    raw, fieldnames = _read(path)
    raw, mappings = _canonicalise(raw, fieldnames, SETTLEMENT_COLUMNS, provider)
    rows: list[SettlementRow] = []
    rejections: list[str] = []
    seen: set[str] = set()

    for index, record in enumerate(raw, start=2):  # line 1 is the header
        payment_id = record.get("payment_id", "").strip()
        try:
            if not payment_id:
                raise ValueError("missing payment_id")
            if payment_id in seen:
                raise ValueError(f"duplicate payment_id {payment_id}")
            seen.add(payment_id)
            rows.append(
                SettlementRow(
                    settlement_id=record["settlement_id"].strip(),
                    payment_id=payment_id,
                    order_id=record.get("order_id", "").strip(),
                    type=RowType(record["type"].strip()),
                    amount=paise(record["amount"]),
                    fee=paise(record.get("fee", "")),
                    tax=paise(record.get("tax", "")),
                    settled_at=_parse_datetime(record["settled_at"]),
                    utr=record.get("utr", "").strip(),
                )
            )
        except (KeyError, ValueError) as error:
            rejections.append(f"line {index}: {error}")

    return rows, NormaliseReport(
        file=path.name,
        rows_read=len(raw),
        rows_rejected=len(rejections),
        rejections=rejections,
        columns_mapped=mappings,
    )


def read_orders(
    path: Path, provider: LlmProvider | None = None
) -> tuple[list[OrderRow], NormaliseReport]:
    raw, fieldnames = _read(path)
    raw, mappings = _canonicalise(raw, fieldnames, ORDER_COLUMNS, provider)
    rows: list[OrderRow] = []
    rejections: list[str] = []
    seen: set[str] = set()

    for index, record in enumerate(raw, start=2):
        order_id = record.get("order_id", "").strip()
        try:
            if not order_id:
                raise ValueError("missing order_id")
            if order_id in seen:
                raise ValueError(f"duplicate order_id {order_id}")
            seen.add(order_id)
            rows.append(
                OrderRow(
                    order_id=order_id,
                    order_amount=paise(record["order_amount"]),
                    status=record.get("status", "").strip(),
                    created_at=_parse_datetime(record["created_at"]),
                    refunded_amount=paise(record.get("refunded_amount", "")),
                    payment_ref=record.get("payment_ref", "").strip(),
                )
            )
        except (KeyError, ValueError) as error:
            rejections.append(f"line {index}: {error}")

    return rows, NormaliseReport(
        file=path.name,
        rows_read=len(raw),
        rows_rejected=len(rejections),
        rejections=rejections,
        columns_mapped=mappings,
    )


def read_bank(
    path: Path, provider: LlmProvider | None = None
) -> tuple[list[BankRow], NormaliseReport]:
    raw, fieldnames = _read(path)
    raw, mappings = _canonicalise(raw, fieldnames, BANK_COLUMNS, provider)
    rows: list[BankRow] = []
    rejections: list[str] = []
    seen: set[str] = set()

    for index, record in enumerate(raw, start=2):
        ref = record.get("ref", "").strip()
        try:
            if not ref:
                raise ValueError("missing ref")
            if ref in seen:
                raise ValueError(f"duplicate ref {ref}")
            seen.add(ref)
            rows.append(
                BankRow(
                    date=_parse_date(record["date"]),
                    narration=record.get("narration", "").strip(),
                    debit=paise(record.get("debit", "")),
                    credit=paise(record.get("credit", "")),
                    balance=paise(record.get("balance", "")),
                    ref=ref,
                )
            )
        except (KeyError, ValueError) as error:
            rejections.append(f"line {index}: {error}")

    return rows, NormaliseReport(
        file=path.name,
        rows_read=len(raw),
        rows_rejected=len(rejections),
        rejections=rejections,
        columns_mapped=mappings,
    )


def read_contract(path: Path) -> Contract:
    return Contract.model_validate_json(path.read_text(encoding="utf-8"))
