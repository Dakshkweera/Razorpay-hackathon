"""Scoring a finished report against the planted truth.

This is the only module permitted to read ``truth.json``, and it runs strictly after
the reconciliation is complete. It receives a finished :class:`Report` and cannot
influence how it was produced.

Two counters carry the submission:

``false_matches``
    A batch tied to the wrong bank line, or tied to one at all when nothing was
    credited. Not "unmatched" - unmatched is an honest outcome that costs nothing.

``false_cause_attributions``
    A gap component asserted with a cause that the truth does not support: a cause
    that never existed, a value that overstates a real one, or - worst - an
    explanation offered for money planted as unexplainable.

Reporting ``unexplained`` is never counted as an error. Refusing to answer is the
correct answer wherever the evidence runs out.
"""

from __future__ import annotations

from pathlib import Path

from recon.report import (
    CaseStatus,
    ComponentKind,
    EvalBatch,
    EvalCase,
    EvalComponent,
    EvalReport,
    ExceptionKind,
    MappingMethod,
    MatchOrigin,
    MatchRule,
    Report,
    Verdict,
)
from recon.truth import Truth, TruthBatch


def load_truth(path: Path) -> Truth:
    return Truth.model_validate_json(path.read_text(encoding="utf-8"))


def _score_batch(reported, planted: TruthBatch) -> EvalBatch:
    truth_amounts: dict[ComponentKind, int] = {
        component.kind: int(component.amount) for component in planted.components
    }
    # ``attributed`` records whether a *cause* was committed to. An unexplained residue
    # carries no cause and so is flagged false, but it is very much reported - and
    # reporting it is the behaviour being scored. Reading the flag literally here would
    # mark an honest refusal as a miss.
    reported_amounts: dict[ComponentKind, int] = {
        component.kind: int(component.amount)
        for component in reported.components
        if component.attributed or component.kind is ComponentKind.UNEXPLAINED
    }

    components: list[EvalComponent] = []
    for kind in sorted(set(truth_amounts) | set(reported_amounts), key=lambda k: k.value):
        truth_amount = truth_amounts.get(kind, 0)
        reported_amount = reported_amounts.get(kind, 0)

        if kind is ComponentKind.UNEXPLAINED:
            # Admitting an amount is unexplained is the desired behaviour, not a claim.
            # It is scored only on whether the amount is right.
            verdict = Verdict.CORRECT if truth_amount == reported_amount else Verdict.MISSED
        elif kind not in truth_amounts:
            verdict = Verdict.FALSE_CAUSE
        elif kind not in reported_amounts:
            verdict = Verdict.MISSED
        elif truth_amount == reported_amount:
            verdict = Verdict.CORRECT
        else:
            verdict = Verdict.OVER_ATTRIBUTED

        components.append(
            EvalComponent(
                kind=kind,
                truth_amount=truth_amount,
                reported_amount=reported_amount,
                verdict=verdict,
            )
        )

    gap_agrees = planted.expected_gap is None or int(reported.headline_gap) == int(
        planted.expected_gap
    )
    return EvalBatch(
        settlement_id=planted.settlement_id,
        truth_gap=planted.expected_gap if planted.expected_gap is not None else 0,
        reported_gap=reported.headline_gap,
        components=components,
        passed=gap_agrees
        and all(component.verdict is not Verdict.FALSE_CAUSE for component in components)
        and all(component.verdict is not Verdict.OVER_ATTRIBUTED for component in components),
    )


def _count_false_matches(report: Report, truth: Truth) -> tuple[int, list[str]]:
    planted = {batch.settlement_id: batch for batch in truth.batches}
    wrong: list[str] = []
    for batch in report.batches:
        if batch.match.rule is MatchRule.NONE:
            continue  # declining to match is never an error
        expected_ref = planted[batch.settlement_id].bank_ref
        if expected_ref is None:
            wrong.append(f"{batch.settlement_id} matched {batch.bank_ref}, but nothing was credited")
        elif batch.bank_ref != expected_ref:
            wrong.append(
                f"{batch.settlement_id} matched {batch.bank_ref}, should be {expected_ref}"
            )
    return len(wrong), wrong


def _decomposition_has_run(report: Report) -> bool:
    return any(batch.components for batch in report.batches)


def _score_cases(report: Report, truth: Truth) -> list[EvalCase]:
    """Score the PRD's planted-case table one row at a time.

    Cases whose deciding stage is not built yet report ``pending`` rather than
    ``fail``: an unbuilt stage and a broken one are different facts, and collapsing
    them would make the scoreboard lie in the direction that flatters us.
    """
    batches = {batch.settlement_id: batch for batch in report.batches}
    planted = {batch.settlement_id: batch for batch in truth.batches}
    exceptions_by_settlement: dict[str, list] = {}
    exceptions_by_ref: dict[str, list] = {}
    for exception in report.exceptions:
        if exception.settlement_id:
            exceptions_by_settlement.setdefault(exception.settlement_id, []).append(exception)
        for ref in (exception.bank_ref or "").split(", "):
            if ref:
                exceptions_by_ref.setdefault(ref, []).append(exception)

    decomposed = _decomposition_has_run(report)
    results: list[EvalCase] = []

    def add(number: int, name: str, expected: str, status: CaseStatus, actual: str) -> None:
        results.append(
            EvalCase(number=number, name=name, expected=expected, actual=actual, status=status)
        )

    def fully_explained(settlement_id: str) -> tuple[CaseStatus, str]:
        batch = batches[settlement_id]
        if not decomposed:
            return CaseStatus.PENDING, "gap decomposition not implemented yet"
        if int(batch.residual) != 0:
            return CaseStatus.FAIL, f"residual {int(batch.residual)} paise remains"
        return CaseStatus.PASS, "gap fully attributed, residual 0"

    for case in truth.cases:
        number, name, expected = case.number, case.name, case.expected

        if number == 1:
            batch = batches[case.settlement_ids[0]]
            if batch.match.rule is not MatchRule.R1:
                add(number, name, expected, CaseStatus.FAIL, f"matched by {batch.match.rule.value}")
            else:
                status, detail = fully_explained(batch.settlement_id)
                add(number, name, expected, status, f"matched by R1; {detail}")

        elif number == 2:
            status, detail = fully_explained(case.settlement_ids[0])
            add(number, name, expected, status, detail)

        elif number == 3:
            if not decomposed:
                add(number, name, expected, CaseStatus.PENDING, "adjacent-cycle search not built yet")
            else:
                found = [
                    settlement_id
                    for settlement_id in case.settlement_ids
                    if any(
                        component.kind is ComponentKind.CROSS_CYCLE_REFUND
                        for component in batches[settlement_id].components
                    )
                ]
                add(
                    number,
                    name,
                    expected,
                    CaseStatus.PASS if len(found) == len(case.settlement_ids) else CaseStatus.FAIL,
                    f"cross-cycle refund attributed on {', '.join(found) or 'neither end'}",
                )

        elif number == 4:
            if not decomposed:
                add(number, name, expected, CaseStatus.PENDING, "fee recomputation not built yet")
            else:
                batch = batches[case.settlement_ids[0]]
                drift = next(
                    (c for c in batch.components if c.kind is ComponentKind.FEE_RATE_DRIFT), None
                )
                planted_drift = next(
                    (
                        c
                        for c in planted[batch.settlement_id].components
                        if c.kind is ComponentKind.FEE_RATE_DRIFT
                    ),
                    None,
                )
                ok = (
                    drift is not None
                    and planted_drift is not None
                    and int(drift.amount) == int(planted_drift.amount)
                )
                add(
                    number,
                    name,
                    expected,
                    CaseStatus.PASS if ok else CaseStatus.FAIL,
                    f"drift reported as {int(drift.amount)} paise" if drift else "no drift flagged",
                )

        elif number == 5:
            # With the AI layer engaged (the normal way this system runs), the model
            # reads past the lookalike-glyph corruption and recovers the reference in
            # full - R1, credited as inference rather than a rule. With the model
            # switched off entirely there is nothing to recover it with, and R4
            # (amount within two days) is the correct fallback: still a pass, because
            # the honest behaviour with no model available is not a failure.
            batch = batches[case.settlement_ids[0]]
            via_inference = (
                batch.match.rule is MatchRule.R1 and batch.match.origin is MatchOrigin.INFERENCE
            )
            via_fallback = batch.match.rule is MatchRule.R4
            ok = via_inference or via_fallback
            add(
                number,
                name,
                expected,
                CaseStatus.PASS if ok else CaseStatus.FAIL,
                f"matched by {batch.match.rule.value} "
                f"({batch.match.origin.value}) at confidence {batch.match.confidence:.2f}",
            )

        elif number == 6:
            unmatched = [
                settlement_id
                for settlement_id in case.settlement_ids
                if batches[settlement_id].match.rule is MatchRule.NONE
            ]
            flagged = [
                settlement_id
                for settlement_id in case.settlement_ids
                if any(
                    exception.kind is ExceptionKind.AMBIGUOUS_MATCH
                    for exception in exceptions_by_settlement.get(settlement_id, [])
                )
            ]
            ok = len(unmatched) == len(case.settlement_ids) == len(flagged)
            add(
                number,
                name,
                expected,
                CaseStatus.PASS if ok else CaseStatus.FAIL,
                f"{len(unmatched)} of {len(case.settlement_ids)} left unmatched, "
                f"{len(flagged)} raised as ambiguous",
            )

        elif number == 7:
            duplicate = [
                exception
                for ref in case.bank_refs
                for exception in exceptions_by_ref.get(ref, [])
                if exception.kind is ExceptionKind.DUPLICATE_UTR
            ]
            counted = sum(
                1
                for batch in report.batches
                if batch.bank_ref in case.bank_refs
            )
            ok = bool(duplicate) and counted == 1
            add(
                number,
                name,
                expected,
                CaseStatus.PASS if ok else CaseStatus.FAIL,
                f"flagged as duplicate; {counted} of the {len(case.bank_refs)} lines counted",
            )

        elif number == 8:
            ref = case.bank_refs[0]
            ok = any(
                exception.kind is ExceptionKind.UNMATCHED_BANK_CREDIT
                for exception in exceptions_by_ref.get(ref, [])
            )
            add(
                number,
                name,
                expected,
                CaseStatus.PASS if ok else CaseStatus.FAIL,
                f"{ref} raised as an unmatched credit" if ok else f"{ref} not raised",
            )

        elif number == 9:
            settlement_id = case.settlement_ids[0]
            raised = [
                exception
                for exception in exceptions_by_settlement.get(settlement_id, [])
                if exception.kind is ExceptionKind.UNMATCHED_SETTLEMENT
            ]
            mentions_timing = bool(raised) and "timing" in raised[0].what.lower()
            add(
                number,
                name,
                expected,
                CaseStatus.PASS if raised and mentions_timing else CaseStatus.FAIL,
                "raised as unmatched settlement, timing noted as an inference"
                if mentions_timing
                else "raised without noting timing"
                if raised
                else "not raised",
            )

        elif number == 10:
            if not decomposed:
                add(number, name, expected, CaseStatus.PENDING, "residue classification not built yet")
            else:
                batch = batches[case.settlement_ids[0]]
                planted_amount = next(
                    int(component.amount)
                    for component in planted[batch.settlement_id].components
                    if not component.detectable
                )
                invented = [
                    component
                    for component in batch.components
                    if component.attributed and component.kind is not ComponentKind.UNEXPLAINED
                    and component.kind
                    not in {c.kind for c in planted[batch.settlement_id].components}
                ]
                ok = int(batch.residual) == planted_amount and not invented
                add(
                    number,
                    name,
                    expected,
                    CaseStatus.PASS if ok else CaseStatus.FAIL,
                    f"{int(batch.residual)} paise left unexplained, {len(invented)} causes invented",
                )

        elif number == 11:
            bank_report = next(
                (n for n in report.normalise if n.file == "bank.csv"), None
            )
            if bank_report is None:
                add(number, name, expected, CaseStatus.FAIL, "bank.csv was not ingested")
            else:
                mapped = {m.source: m for m in bank_report.columns_mapped}
                alias_ok = (
                    "particulars" in mapped
                    and mapped["particulars"].canonical == "narration"
                    and mapped["particulars"].method == MappingMethod.ALIAS
                )
                llm_ok = (
                    "reference_no" in mapped
                    and mapped["reference_no"].canonical == "ref"
                    and mapped["reference_no"].method == MappingMethod.LLM
                )
                all_parsed = bank_report.rows_rejected == 0
                ok = alias_ok and llm_ok and all_parsed
                add(
                    number,
                    name,
                    expected,
                    CaseStatus.PASS if ok else CaseStatus.FAIL,
                    f"particulars via {mapped.get('particulars').method.value if 'particulars' in mapped else 'unresolved'}, "
                    f"reference_no via {mapped.get('reference_no').method.value if 'reference_no' in mapped else 'unresolved'}, "
                    f"{bank_report.rows_rejected} of {bank_report.rows_read} rows rejected",
                )

    return results


def score(report: Report, truth: Truth) -> EvalReport:
    planted = {batch.settlement_id: batch for batch in truth.batches}
    batch_scores = [
        _score_batch(batch, planted[batch.settlement_id])
        for batch in report.batches
        if batch.settlement_id in planted and batch.bank_credit is not None
    ]

    false_matches, _ = _count_false_matches(report, truth)
    false_causes = sum(
        1
        for scored in batch_scores
        for component in scored.components
        if component.verdict in (Verdict.FALSE_CAUSE, Verdict.OVER_ATTRIBUTED)
    )

    detectable_total = int(truth.total_detectable)
    correctly_attributed = sum(
        int(component.reported_amount)
        for scored in batch_scores
        for component in scored.components
        if component.verdict is Verdict.CORRECT and component.kind is not ComponentKind.UNEXPLAINED
    )

    cases = _score_cases(report, truth)
    return EvalReport(
        batches=batch_scores,
        cases=cases,
        cases_passed=sum(1 for case in cases if case.status is CaseStatus.PASS),
        cases_failed=sum(1 for case in cases if case.status is CaseStatus.FAIL),
        cases_pending=sum(1 for case in cases if case.status is CaseStatus.PENDING),
        cases_total=len(cases),
        false_matches=false_matches,
        false_cause_attributions=false_causes,
        gap_accuracy_pct=round(100.0 * correctly_attributed / detectable_total, 1)
        if detectable_total
        else 0.0,
    )


def attach(report: Report, truth_path: Path) -> Report:
    """Score a finished report in place.

    Called by the CLI and the API *after* :func:`recon.pipeline.run` has returned, never
    from inside it. The two counters land on the scoreboard here because they cannot be
    known without the truth file.
    """
    from recon.pipeline import deterministic_hash

    evaluation = score(report, load_truth(truth_path))
    report.evaluation = evaluation
    report.scoreboard.false_matches = evaluation.false_matches
    report.scoreboard.false_cause_attributions = evaluation.false_cause_attributions
    # Recomputed so the hash describes the report as it is written, evaluation included.
    report.meta.deterministic_hash = deterministic_hash(report)
    return report
