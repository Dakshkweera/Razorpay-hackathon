"""Writes the generated dataset to disk.

Everything here is byte-stable on purpose: LF line endings regardless of platform,
no BOM, fixed column order, integers rendered without separators. ``recon verify``
regenerates from the same seed and compares bytes, so any accidental non-determinism
in this module would surface immediately rather than during a demo.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from recon.generate.build import GeneratedData
from recon.model import BankRow, OrderRow, SettlementRow
from recon.money import Paise

SETTLEMENT_COLUMNS = (
    "settlement_id",
    "payment_id",
    "order_id",
    "type",
    "amount",
    "fee",
    "tax",
    "settled_at",
    "utr",
)
ORDER_COLUMNS = (
    "order_id",
    "order_amount",
    "status",
    "created_at",
    "refunded_amount",
    "payment_ref",
)
BANK_COLUMNS = ("date", "narration", "debit", "credit", "balance", "ref")

#: Two of the bank statement's own headers are deliberately exported under the names a
#: real Indian bank export uses instead of the canonical ones - this is stage 1's
#: "schema drift across sources" claim, exercised on real bytes rather than left as an
#: untested capability. "particulars" resolves through the alias table (free,
#: deterministic); "reference_no" is not in that table at all and only resolves
#: through the LLM tier, because "exhaustive is what the LLM tier is for."
BANK_HEADER_OVERRIDES: dict[str, str] = {
    "narration": "particulars",
    "ref": "reference_no",
}


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _blank_if_zero(amount: Paise) -> str:
    """Bank statements leave the unused side of the ledger empty, not zero."""
    return str(int(amount)) if int(amount) else ""


def _render_csv(columns: tuple[str, ...], rows: list[list[str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()


def render_settlements(rows: list[SettlementRow]) -> str:
    return _render_csv(
        SETTLEMENT_COLUMNS,
        [
            [
                row.settlement_id,
                row.payment_id,
                row.order_id,
                row.type.value,
                str(int(row.amount)),
                str(int(row.fee)),
                str(int(row.tax)),
                _iso(row.settled_at),
                row.utr,
            ]
            for row in rows
        ],
    )


def render_orders(rows: list[OrderRow]) -> str:
    return _render_csv(
        ORDER_COLUMNS,
        [
            [
                row.order_id,
                str(int(row.order_amount)),
                row.status,
                _iso(row.created_at),
                str(int(row.refunded_amount)),
                row.payment_ref,
            ]
            for row in rows
        ],
    )


def render_bank(rows: list[BankRow]) -> str:
    header = tuple(BANK_HEADER_OVERRIDES.get(column, column) for column in BANK_COLUMNS)
    return _render_csv(
        header,
        [
            [
                row.date.isoformat(),
                row.narration,
                _blank_if_zero(row.debit),
                _blank_if_zero(row.credit),
                str(int(row.balance)),
                row.ref,
            ]
            for row in rows
        ],
    )


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def write_dataset(data: GeneratedData, out_dir: Path) -> dict[str, Path]:
    """Write the three CSVs, the contract, and the hidden truth file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "settlements": out_dir / "settlements.csv",
        "orders": out_dir / "orders.csv",
        "bank": out_dir / "bank.csv",
        "contract": out_dir / "contract.json",
        "truth": out_dir / "truth.json",
    }
    _write(paths["settlements"], render_settlements(data.settlements))
    _write(paths["orders"], render_orders(data.orders))
    _write(paths["bank"], render_bank(data.bank))
    _write(paths["contract"], data.contract.model_dump_json(indent=2) + "\n")
    _write(paths["truth"], data.truth.model_dump_json(indent=2) + "\n")
    return paths
