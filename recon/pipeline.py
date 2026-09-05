"""Orchestrates a reconciliation run.

Stages land here one at a time. Today the pipeline ingests, assembles batches and
computes both expectations; matching, decomposition and classification plug in at
the marked seams without the report shape changing.

Nothing in this module, or anything it imports, may read ``truth.json``.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from recon.classify import residue as residue_classify
from recon.decompose.checks import ADJACENT_CYCLES, decompose
from recon.ingest.csvparse import read_bank, read_contract, read_orders, read_settlements
from recon.llm import build_provider, resolve_mode
from recon.llm.base import LlmProvider
from recon.match.rules import match
from recon.model import BankRow, Contract, OrderRow, RowType, SettlementRow
from recon.money import Paise
from recon.narration.cache import NarrationCache
from recon.narration.extract import extract_all_llm
from recon.report import (
    BatchReport,
    Count,
    ExceptionKind,
    ExceptionReport,
    LlmMode,
    MatchOrigin,
    NarrationRead,
    NormaliseReport,
    Report,
    RunMeta,
    Scoreboard,
    TraceEntry,
)


@dataclass
class Inputs:
    settlements: list[SettlementRow]
    orders: list[OrderRow]
    bank: list[BankRow]
    contract: Contract
    normalise: list[NormaliseReport]


def load(data_dir: Path, provider: LlmProvider | None = None) -> Inputs:
    settlements, settlement_report = read_settlements(data_dir / "settlements.csv", provider)
    orders, order_report = read_orders(data_dir / "orders.csv", provider)
    bank, bank_report = read_bank(data_dir / "bank.csv", provider)
    contract = read_contract(data_dir / "contract.json")
    return Inputs(
        settlements=settlements,
        orders=orders,
        bank=bank,
        contract=contract,
        normalise=[settlement_report, order_report, bank_report],
    )


def assemble_batches(inputs: Inputs) -> list[BatchReport]:
    """Group settlement rows into batches and compute both sides of the expectation.

    Two numbers matter and they are deliberately different:

    ``settlement_expected_credit`` is what Razorpay's own file implies should land -
    gross less fee less tax. ``orders_expected`` is what the merchant's records imply,
    which knows nothing about fees or adjustments. The distance between the second and
    the bank is the gap a finance team actually sees; the distance between the first
    and the bank is the narrower question of whether the settlement itself is sound.
    """
    orders_by_id = {order.order_id: order for order in inputs.orders}

    grouped: dict[str, list[SettlementRow]] = {}
    for row in inputs.settlements:
        grouped.setdefault(row.settlement_id, []).append(row)

    batches: list[BatchReport] = []
    for settlement_id, rows in grouped.items():
        payments = [row for row in rows if row.type is RowType.PAYMENT]
        refunds = [row for row in rows if row.type is RowType.REFUND]
        adjustments = [row for row in rows if row.type is RowType.ADJUSTMENT]

        gross = sum(int(row.amount) for row in rows)
        total_fee = sum(int(row.fee) for row in rows)
        total_tax = sum(int(row.tax) for row in rows)

        # The settlement's own timestamp is the batch's; the cross-cycle refund rows
        # deliberately carry an older one, which is exactly the signal stage 4 hunts for.
        settled_at = max(row.settled_at for row in payments) if payments else rows[0].settled_at

        # The covered window is inferred from when the underlying orders were created.
        # Nothing tells us the cycle boundaries directly, and assuming a fixed cadence
        # would be a guess.
        covered = [
            orders_by_id[row.order_id].created_at.date()
            for row in payments
            if row.order_id in orders_by_id
        ]
        window_start = min(covered) if covered else settled_at.date()
        window_end = max(covered) if covered else settled_at.date()

        orders_expected = 0
        missing_orders = 0
        for row in rows:
            if row.type is RowType.PAYMENT:
                order = orders_by_id.get(row.order_id)
                if order is None:
                    missing_orders += 1
                    continue
                orders_expected += int(order.order_amount)
            elif row.type is RowType.REFUND:
                orders_expected -= -int(row.amount)

        trace = [
            TraceEntry(
                stage="assemble",
                action="group_rows",
                detail=f"{len(payments)} payments, {len(refunds)} refunds, "
                f"{len(adjustments)} adjustments",
            ),
            TraceEntry(
                stage="assemble",
                action="infer_window",
                detail=f"{window_start.isoformat()} to {window_end.isoformat()}, "
                f"inferred from order creation dates",
            ),
        ]
        if missing_orders:
            trace.append(
                TraceEntry(
                    stage="assemble",
                    action="unlinked_payments",
                    detail=f"{missing_orders} payment rows reference an order that is not "
                    "in the order file",
                )
            )

        batches.append(
            BatchReport(
                settlement_id=settlement_id,
                utr=rows[0].utr,
                settled_at=settled_at,
                window_start=window_start,
                window_end=window_end,
                row_count=len(rows),
                payment_count=len(payments),
                refund_count=len(refunds),
                adjustment_count=len(adjustments),
                gross_settled=Paise(gross),
                total_fee=Paise(total_fee),
                total_tax=Paise(total_tax),
                settlement_expected_credit=Paise(gross - total_fee - total_tax),
                orders_expected=Paise(orders_expected),
                trace=trace,
            )
        )

    batches.sort(key=lambda batch: (batch.settled_at, batch.settlement_id))
    return batches


def group_rows(inputs: Inputs) -> dict[str, list[SettlementRow]]:
    grouped: dict[str, list[SettlementRow]] = {}
    for row in inputs.settlements:
        grouped.setdefault(row.settlement_id, []).append(row)
    return grouped


def decompose_all(inputs: Inputs, batches: list[BatchReport]) -> list[ExceptionReport]:
    """Attribute every matched batch's gap.

    Neighbours are the batches immediately either side in settlement order, which is
    what "adjacent cycle" means when the cycle boundaries are inferred rather than
    given. Batches with no credit are skipped: there is no gap to decompose until
    money arrives.
    """
    rows_by_settlement = group_rows(inputs)
    orders_by_id = {order.order_id: order for order in inputs.orders}

    exceptions: list[ExceptionReport] = []
    for index, batch in enumerate(batches):
        neighbours = [
            (other, rows_by_settlement[other.settlement_id])
            for offset in range(-ADJACENT_CYCLES, ADJACENT_CYCLES + 1)
            if offset != 0
            and 0 <= index + offset < len(batches)
            for other in [batches[index + offset]]
        ]
        raised = decompose(
            batch,
            rows_by_settlement[batch.settlement_id],
            orders_by_id,
            inputs.contract,
            neighbours,
        )
        if raised is not None:
            exceptions.append(raised)
    return exceptions


def renumber(exceptions: list[ExceptionReport]) -> None:
    """Re-sort and re-label after a later stage adds to the list."""
    order = {
        ExceptionKind.AMBIGUOUS_MATCH: 0,
        ExceptionKind.DUPLICATE_UTR: 1,
        ExceptionKind.UNMATCHED_SETTLEMENT: 2,
        ExceptionKind.UNMATCHED_BANK_CREDIT: 3,
        ExceptionKind.UNEXPLAINED_RESIDUE: 4,
    }
    exceptions.sort(
        key=lambda item: (order[item.kind], item.settlement_id or "", item.bank_ref or "")
    )
    for index, exception in enumerate(exceptions, start=1):
        exception.id = f"EXC-{index:02d}"


def build_scoreboard(inputs: Inputs, batches: list[BatchReport]) -> Scoreboard:
    """Aggregate the run.

    Gap figures are summed on magnitude. A batch credited more than its orders imply is
    every bit as unreconciled as one credited less, and letting the two cancel would
    report a tidier number than the books deserve.
    """
    total = len(batches)
    deterministic = sum(
        1 for batch in batches if batch.match.origin is MatchOrigin.DETERMINISTIC
    )
    inference = sum(1 for batch in batches if batch.match.origin is MatchOrigin.INFERENCE)
    unmatched = total - deterministic - inference

    def share(count: int) -> Count:
        return Count(n=count, pct=round(100.0 * count / total, 1) if total else 0.0)

    # Magnitudes, and unexplained measured directly. Components legitimately carry
    # either sign - a refund documented in the wrong cycle makes one batch short and
    # its neighbour long - so summing signed components would report a tidier number
    # than the books deserve.
    matched_batches = [batch for batch in batches if batch.bank_credit is not None]
    gap_total = sum(abs(int(batch.headline_gap)) for batch in matched_batches)
    unexplained = sum(abs(int(batch.residual)) for batch in matched_batches)
    explained = sum(
        max(0, abs(int(batch.headline_gap)) - abs(int(batch.residual)))
        for batch in matched_batches
    )

    return Scoreboard(
        settlement_rows=len(inputs.settlements),
        order_rows=len(inputs.orders),
        bank_rows=len(inputs.bank),
        records_processed=len(inputs.settlements) + len(inputs.orders) + len(inputs.bank),
        settlement_batches=total,
        matched_deterministic=share(deterministic),
        matched_inference=share(inference),
        unmatched=share(unmatched),
        gap_total=Paise(gap_total),
        gap_explained=Paise(explained),
        gap_unexplained=Paise(unexplained),
        gap_explained_pct=round(100.0 * explained / gap_total, 1) if gap_total else 0.0,
        gap_unexplained_pct=round(100.0 * unexplained / gap_total, 1) if gap_total else 0.0,
    )


def deterministic_hash(report: Report) -> str:
    """SHA-256 over the report with wall-clock fields removed.

    Runtime and start time are properties of the machine, not of the reconciliation.
    Call and cache-hit counts are properties of *how* the answer was reached - whether
    a fixture was already warm - not of what the answer is. Excluding all four is what
    lets ``recon verify`` make an honest claim about two runs producing the same answer,
    including a first run that has to call a live model and a second that replays it.
    """
    payload = report.model_dump(mode="json")
    for key in ("run_at", "runtime_ms", "deterministic_hash", "llm_calls", "llm_cache_hits"):
        payload["meta"].pop(key, None)
    payload["scoreboard"].pop("runtime_ms", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run(data_dir: Path, seed: int = 42, llm_mode: LlmMode | None = None) -> Report:
    started = time.perf_counter()
    mode = llm_mode if llm_mode is not None else resolve_mode()
    provider = build_provider(mode)
    inputs = load(data_dir, provider)
    batches = assemble_batches(inputs)

    # --- stage 2: read identifiers off the bank narrations -------------------- #
    narrations = extract_all_llm(inputs.bank, provider, NarrationCache())

    # --- stage 3: deterministic matching -------------------------------------- #
    matched = match(batches, inputs.bank, narrations)

    # --- stage 4: gap decomposition ------------------------------------------- #
    matched.exceptions.extend(decompose_all(inputs, batches))
    renumber(matched.exceptions)

    # --- stage 4b: ask a model about whatever the five checks left over -------- #
    residue_classify.apply(batches, matched.exceptions, provider)

    claimed_by = {
        batch.bank_ref: batch.settlement_id for batch in batches if batch.bank_ref is not None
    }
    narration_reads = [
        NarrationRead(
            ref=narration.ref,
            raw=narration.raw,
            utrs=list(narration.all_utrs),
            counterparty=narration.counterparty,
            kind=narration.kind,
            confidence=narration.confidence,
            source=narration.source,
            notes=list(narration.notes),
            matched_settlement_id=claimed_by.get(narration.ref),
        )
        for narration in sorted(narrations.values(), key=lambda item: item.ref)
    ]

    report = Report(
        meta=RunMeta(
            seed=seed,
            data_dir=str(data_dir).replace("\\", "/"),
            run_at=datetime.now(timezone.utc),
            llm_provider=provider.name if provider is not None else "none",
            llm_mode=mode,
            llm_calls=getattr(provider, "calls", 0),
            llm_cache_hits=getattr(provider, "cache_hits", 0),
        ),
        normalise=inputs.normalise,
        narrations=narration_reads,
        batches=batches,
        unmatched_bank_rows=matched.unmatched_bank_rows,
        exceptions=matched.exceptions,
        scoreboard=build_scoreboard(inputs, batches),
    )
    report.scoreboard.runtime_ms = int((time.perf_counter() - started) * 1000)
    report.meta.runtime_ms = report.scoreboard.runtime_ms
    report.meta.deterministic_hash = deterministic_hash(report)
    return report
