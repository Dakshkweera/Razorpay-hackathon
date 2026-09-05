"""Stage 3 - deterministic matching.

Four rules, run in strict order, first hit wins, and every match records which rule
fired and what else was in the running.

The governing idea is that a match must be *uniquely* justified. A rule fires only
when one batch and one bank line pick each other out: if a batch has two candidates,
or a bank line is claimed by two batches, the answer is an exception. Committing to
either half of an ambiguous pair would be indistinguishable, from the outside, from
having reconciled it correctly - and that is the failure this project exists to avoid.

Rules record what they tried as they go, and exactly one exception is raised per
unresolved batch at the end. A batch refused by R3 and refused again by R4 is one
problem, not two, and an exception list that says otherwise is a dump rather than a
work queue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from recon.model import BankRow
from recon.money import Paise, format_inr
from recon.narration.extract import Narration
from recon.report import (
    Attempt,
    BatchReport,
    ExceptionKind,
    ExceptionReport,
    Match,
    MatchOrigin,
    MatchRule,
    RuledOut,
    TraceEntry,
    UnmatchedBankRow,
)

#: Below this, a proposed match is refused. R4 sits exactly on it.
MATCH_COMMIT_THRESHOLD = 0.85

RULE_CONFIDENCE: dict[MatchRule, float] = {
    MatchRule.R1: 1.00,
    MatchRule.R2: 1.00,
    MatchRule.R3: 0.95,
    MatchRule.R4: 0.85,
}

RULE_BASIS: dict[MatchRule, str] = {
    MatchRule.R1: "settlement UTR found in the bank narration",
    MatchRule.R2: "settlement id printed verbatim in the bank narration",
    MatchRule.R3: "exact expected credit on the same date",
    MatchRule.R4: "exact expected credit within two days",
}

RULE_CHECK_NAME: dict[MatchRule, str] = {
    MatchRule.R1: "R1 utr in narration",
    MatchRule.R2: "R2 settlement id in narration",
    MatchRule.R3: "R3 exact amount, same date",
    MatchRule.R4: "R4 exact amount, within 2 days",
}

#: A settlement dated this close to the end of the statement has probably just not been
#: posted yet. That is a reason to say so on the exception, never to assume it.
_TIMING_WINDOW_DAYS = 3


@dataclass
class MatchResult:
    exceptions: list[ExceptionReport] = field(default_factory=list)
    unmatched_bank_rows: list[UnmatchedBankRow] = field(default_factory=list)


@dataclass
class _Candidate:
    row: BankRow
    narration: Narration


@dataclass
class _Attempts:
    """What was tried against one batch, so a refusal can explain itself."""

    entries: list[Attempt] = field(default_factory=list)
    ruled_out: list[RuledOut] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    ambiguous: bool = False

    def note(self, rule: MatchRule, outcome: str) -> None:
        self.entries.append(Attempt(check=RULE_CHECK_NAME[rule], outcome=outcome))

    def saw(self, refs: list[str]) -> None:
        for ref in refs:
            if ref not in self.candidates:
                self.candidates.append(ref)


def _days_apart(left: date, right: date) -> int:
    return abs((left - right).days)


def _claim(
    batch: BatchReport,
    candidate: _Candidate,
    rule: MatchRule,
    considered: int,
    origin: MatchOrigin = MatchOrigin.DETERMINISTIC,
) -> None:
    """Commit a match and fill in everything downstream that depends on it."""
    row = candidate.row
    batch.match = Match(
        rule=rule,
        origin=origin,
        confidence=RULE_CONFIDENCE[rule],
        basis=RULE_BASIS[rule],
        bank_ref=row.ref,
        candidates_considered=considered,
    )
    batch.bank_ref = row.ref
    batch.bank_credit = row.credit
    batch.bank_narration = row.narration
    batch.bank_date = row.date
    batch.headline_gap = Paise(int(batch.orders_expected) - int(row.credit))
    batch.settlement_residual = Paise(int(batch.settlement_expected_credit) - int(row.credit))
    inferred = " - identifier recovered by the LLM, not the regex" if origin is MatchOrigin.INFERENCE else ""
    batch.trace.append(
        TraceEntry(
            stage="match",
            action=f"{rule.value}_matched",
            detail=f"{row.ref} - {RULE_BASIS[rule]} "
            f"(confidence {RULE_CONFIDENCE[rule]:.2f}, {considered} candidate"
            f"{'s' if considered != 1 else ''} considered){inferred}",
        )
    )


def _find_duplicates(
    pool: dict[str, _Candidate],
) -> tuple[dict[str, _Candidate], list[ExceptionReport]]:
    """Collapse repeated postings of one payout before anything tries to match them.

    Keyed on the reference *and* the value *and* the day: those three agreeing means the
    bank posted one payout twice. Two lines sharing a UTR for different amounts are a
    different situation and are deliberately left alone.
    """
    groups: dict[tuple[str, int, str], list[str]] = {}
    for ref, candidate in sorted(pool.items()):
        for utr in candidate.narration.utrs:
            key = (utr, int(candidate.row.credit), candidate.row.date.isoformat())
            groups.setdefault(key, []).append(ref)

    survivors = dict(pool)
    exceptions: list[ExceptionReport] = []
    for (utr, amount, day), refs in sorted(groups.items()):
        if len(refs) < 2:
            continue
        kept, dropped = refs[0], refs[1:]
        for ref in dropped:
            survivors.pop(ref, None)
        plural = len(dropped) > 1
        exceptions.append(
            ExceptionReport(
                id="",
                kind=ExceptionKind.DUPLICATE_UTR,
                amount=Paise(amount * len(dropped)),
                bank_ref=", ".join(dropped),
                what=f"UTR {utr} was posted {len(refs)} times on {day}, each for "
                f"{format_inr(Paise(amount))}. {kept} is treated as the payout; "
                f"{', '.join(dropped)} {'are' if plural else 'is'} a repeated posting and "
                f"{'were' if plural else 'was'} not counted again.",
                tried=[
                    Attempt(
                        check="duplicate posting scan",
                        outcome=f"grouped {len(refs)} credit lines agreeing on UTR, amount "
                        "and date",
                        attributed=Paise(amount * len(dropped)),
                    )
                ],
                ruled_out=[
                    RuledOut(
                        check="separate payouts",
                        reason="two settlements of identical value on one day sharing one UTR "
                        "would require two batches carrying that UTR; only one exists",
                    )
                ],
                needs="confirmation from the bank that a single payout was received, or a "
                "reversal entry for the repeat",
                candidates=refs,
            )
        )
    return survivors, exceptions


def _apply_identifier_rule(
    batches: list[BatchReport],
    pool: dict[str, _Candidate],
    attempts: dict[str, _Attempts],
    rule: MatchRule,
    predicate: Callable[[BatchReport, _Candidate], bool],
    absent: Callable[[BatchReport], str],
    origin_of: Callable[[BatchReport, _Candidate], MatchOrigin] = (
        lambda batch, candidate: MatchOrigin.DETERMINISTIC
    ),
) -> None:
    """R1 and R2: a batch's own identifier appearing on exactly one bank line.

    ``origin_of`` exists for R1 alone: a UTR the regex read directly is deterministic,
    but one recovered from a narration only the LLM could parse makes the resulting
    match *inference* - see :meth:`~recon.narration.extract.Narration.utr_source`. R2
    never needs it, because it reads the raw narration text itself, not an extracted
    field.
    """
    for batch in batches:
        if batch.match.rule is not MatchRule.NONE:
            continue
        record = attempts[batch.settlement_id]
        candidates = [
            candidate for _, candidate in sorted(pool.items()) if predicate(batch, candidate)
        ]
        if not candidates:
            record.note(rule, absent(batch))
            continue
        refs = [candidate.row.ref for candidate in candidates]
        if len(candidates) == 1:
            record.note(rule, f"matched {refs[0]}")
            _claim(batch, candidates[0], rule, considered=1, origin=origin_of(batch, candidates[0]))
            pool.pop(refs[0])
            continue
        record.note(rule, f"{len(refs)} bank lines carry this identifier ({', '.join(refs)})")
        record.saw(refs)
        record.ambiguous = True
        batch.trace.append(
            TraceEntry(
                stage="match",
                action=f"{rule.value}_ambiguous",
                detail=f"candidates {', '.join(refs)} - refused",
            )
        )


def _apply_amount_rule(
    batches: list[BatchReport],
    pool: dict[str, _Candidate],
    attempts: dict[str, _Attempts],
    rule: MatchRule,
    max_days: int,
) -> None:
    """R3 and R4: value and date, committed only when the choice is mutual.

    Both directions are checked. One candidate is not enough on its own: if that same
    bank line is also the only candidate for another batch, neither can be committed.
    That is exactly the identical-amount-same-day case, and it is the one place where
    doing nothing is the correct behaviour.
    """
    open_batches = [batch for batch in batches if batch.match.rule is MatchRule.NONE]
    candidates: dict[str, list[str]] = {
        batch.settlement_id: [
            ref
            for ref, candidate in sorted(pool.items())
            if int(candidate.row.credit) == int(batch.settlement_expected_credit)
            and _days_apart(candidate.row.date, batch.settled_at.date()) <= max_days
        ]
        for batch in open_batches
    }

    claimants: dict[str, list[str]] = {}
    for settlement_id, refs in candidates.items():
        for ref in refs:
            claimants.setdefault(ref, []).append(settlement_id)

    window = "on the settled date" if max_days == 0 else f"within {max_days} days"
    for batch in open_batches:
        record = attempts[batch.settlement_id]
        refs = candidates[batch.settlement_id]
        if not refs:
            record.note(rule, f"no credit of {format_inr(batch.settlement_expected_credit)} {window}")
            continue

        if len(refs) > 1:
            record.note(rule, f"{len(refs)} credits of this value {window} ({', '.join(refs)})")
            record.saw(refs)
            record.ambiguous = True
            batch.trace.append(
                TraceEntry(
                    stage="match",
                    action=f"{rule.value}_ambiguous",
                    detail=f"{len(refs)} bank lines share this amount and date "
                    f"({', '.join(refs)}) - refused",
                )
            )
            continue

        ref = refs[0]
        rivals = [other for other in claimants[ref] if other != batch.settlement_id]
        if rivals:
            record.note(
                rule,
                f"{ref} is the only candidate, but it is equally the only candidate for "
                f"{', '.join(rivals)}",
            )
            record.saw([ref])
            record.ambiguous = True
            batch.trace.append(
                TraceEntry(
                    stage="match",
                    action=f"{rule.value}_contested",
                    detail=f"{ref} is also the only candidate for {', '.join(rivals)} - refused",
                )
            )
            continue

        record.note(rule, f"matched {ref}")
        _claim(batch, pool[ref], rule, considered=1)
        pool.pop(ref)


def _refusals(
    batches: list[BatchReport],
    attempts: dict[str, _Attempts],
    statement_end: date | None,
) -> tuple[list[ExceptionReport], set[str]]:
    """One exception per unresolved batch, carrying everything that was tried."""
    exceptions: list[ExceptionReport] = []
    contested: set[str] = set()

    for batch in batches:
        if batch.match.rule is not MatchRule.NONE:
            continue
        record = attempts[batch.settlement_id]

        if record.ambiguous:
            contested.update(record.candidates)
            batch.match = Match(
                candidates_considered=len(record.candidates),
                rejected_reason=f"{len(record.candidates)} candidates, none uniquely justified",
            )
            exceptions.append(
                ExceptionReport(
                    id="",
                    kind=ExceptionKind.AMBIGUOUS_MATCH,
                    amount=batch.settlement_expected_credit,
                    settlement_id=batch.settlement_id,
                    what=f"{batch.settlement_id} expects {format_inr(batch.settlement_expected_credit)} "
                    f"and {len(record.candidates)} bank credits fit it equally well "
                    f"({', '.join(record.candidates)}). Nothing in the three files "
                    f"distinguishes them, so no match was made.",
                    tried=record.entries,
                    ruled_out=[
                        RuledOut(
                            check="pick the earlier credit",
                            reason="ordering is not evidence; committing to either would be "
                            "indistinguishable from having reconciled it correctly",
                        )
                    ],
                    needs="a bank reference or settlement id in the narration, or a payout "
                    "advice tying one of these credits to this batch",
                    confidence=0.5,
                    threshold=MATCH_COMMIT_THRESHOLD,
                    candidates=record.candidates,
                )
            )
            continue

        timing = (
            statement_end is not None
            and _days_apart(statement_end, batch.settled_at.date()) <= _TIMING_WINDOW_DAYS
        )
        batch.match = Match(rejected_reason="no candidate on any rule")
        batch.trace.append(
            TraceEntry(
                stage="match",
                action="no_candidate",
                detail="no bank line matched on identifier, amount or date",
            )
        )
        exceptions.append(
            ExceptionReport(
                id="",
                kind=ExceptionKind.UNMATCHED_SETTLEMENT,
                amount=batch.settlement_expected_credit,
                settlement_id=batch.settlement_id,
                what=f"{batch.settlement_id} settled "
                f"{format_inr(batch.settlement_expected_credit)} on "
                f"{batch.settled_at.date().isoformat()}, and no credit in the statement "
                f"corresponds to it."
                + (
                    f" The statement ends {statement_end.isoformat()}, so this is most "
                    "likely timing rather than a loss - but that is an inference, and it "
                    "is not being recorded as a finding."
                    if timing
                    else ""
                ),
                tried=record.entries,
                ruled_out=[
                    RuledOut(
                        check="assume delayed settlement",
                        reason="a payout that has not arrived and a payout that will never "
                        "arrive look identical inside this statement period",
                    )
                ]
                if timing
                else [],
                needs="the following statement period, or confirmation from Razorpay that "
                "the payout was released",
                threshold=MATCH_COMMIT_THRESHOLD,
            )
        )
    return exceptions, contested


def _unmatched_credits(
    pool: dict[str, _Candidate], contested: set[str]
) -> tuple[list[UnmatchedBankRow], list[ExceptionReport]]:
    """Credits nothing accounted for.

    A line already named in an ambiguity is not an orphan - it has candidate
    settlements, they just cannot be told apart. Reporting it a second time under a
    different heading would inflate the exception count with the same problem.
    """
    rows: list[UnmatchedBankRow] = []
    exceptions: list[ExceptionReport] = []

    for ref, candidate in sorted(pool.items()):
        narration = candidate.narration
        if ref in contested:
            rows.append(
                UnmatchedBankRow(
                    ref=ref,
                    date=candidate.row.date,
                    credit=candidate.row.credit,
                    narration=candidate.row.narration,
                    reason="candidate in an unresolved ambiguity, reported there",
                )
            )
            continue

        settlement_like = narration.looks_like_a_settlement
        rows.append(
            UnmatchedBankRow(
                ref=ref,
                date=candidate.row.date,
                credit=candidate.row.credit,
                narration=candidate.row.narration,
                reason="credit carries a reference that matches no settlement"
                if narration.all_utrs and settlement_like
                else "credit does not appear to be a settlement from this gateway"
                if not settlement_like
                else "credit could not be tied to any settlement",
            )
        )
        if not settlement_like:
            continue

        exceptions.append(
            ExceptionReport(
                id="",
                kind=ExceptionKind.UNMATCHED_BANK_CREDIT,
                amount=candidate.row.credit,
                bank_ref=ref,
                what=f"{ref} credited {format_inr(candidate.row.credit)} on "
                f"{candidate.row.date.isoformat()} and no settlement accounts for it.",
                tried=[
                    Attempt(
                        check="reference lookup",
                        outcome=f"reference{'s' if len(narration.all_utrs) != 1 else ''} "
                        f"{', '.join(narration.all_utrs) or 'none readable'} "
                        f"{'match' if len(narration.all_utrs) != 1 else 'matches'} no settlement "
                        "batch",
                    ),
                    Attempt(
                        check="amount lookup",
                        outcome="value matches no batch's expected credit within two days",
                    ),
                ],
                ruled_out=[
                    RuledOut(
                        check="duplicate of a matched payout",
                        reason="no other credit line shares this reference, amount and date",
                    )
                ],
                needs="the payout advice for this credit, or confirmation that it belongs to "
                "another account or another gateway",
                confidence=narration.confidence,
                threshold=MATCH_COMMIT_THRESHOLD,
            )
        )
    return rows, exceptions


def match(
    batches: list[BatchReport],
    bank: list[BankRow],
    narrations: dict[str, Narration],
) -> MatchResult:
    pool: dict[str, _Candidate] = {
        row.ref: _Candidate(row=row, narration=narrations[row.ref])
        for row in bank
        if int(row.credit) > 0 and row.ref in narrations
    }
    statement_end = max((row.date for row in bank), default=None)
    attempts = {batch.settlement_id: _Attempts() for batch in batches}

    pool, exceptions = _find_duplicates(pool)

    _apply_identifier_rule(
        batches,
        pool,
        attempts,
        MatchRule.R1,
        lambda batch, candidate: batch.utr in candidate.narration.all_utrs,
        lambda batch: f"UTR {batch.utr} appears on no bank line",
        origin_of=lambda batch, candidate: (
            MatchOrigin.INFERENCE
            if candidate.narration.utr_source(batch.utr) == "llm"
            else MatchOrigin.DETERMINISTIC
        ),
    )
    _apply_identifier_rule(
        batches,
        pool,
        attempts,
        MatchRule.R2,
        lambda batch, candidate: batch.settlement_id.lower() in candidate.row.narration.lower(),
        lambda batch: "settlement id is not printed on any narration",
    )
    _apply_amount_rule(batches, pool, attempts, MatchRule.R3, max_days=0)
    _apply_amount_rule(batches, pool, attempts, MatchRule.R4, max_days=2)

    refusals, contested = _refusals(batches, attempts, statement_end)
    exceptions += refusals
    unmatched_rows, credit_exceptions = _unmatched_credits(pool, contested)
    exceptions += credit_exceptions

    # Stable, readable identifiers assigned last so they follow the report's own order.
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

    return MatchResult(exceptions=exceptions, unmatched_bank_rows=unmatched_rows)
