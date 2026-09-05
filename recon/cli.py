"""Command line entry point.

    recon generate    write the synthetic dataset and its planted truth
    recon run         reconcile and emit out/report.json
    recon verify      regenerate and re-run, proving both are byte-identical
    recon schema      export the report JSON Schema the UI types are built from
    recon serve       serve the API and the built UI on one port
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from recon.evaluate.score import attach, load_truth, score
from recon.generate.build import build
from recon.generate.writer import render_bank, render_orders, render_settlements, write_dataset
from recon.llm import resolve_mode
from recon.money import format_inr
from recon.pipeline import run as run_pipeline
from recon.report import CaseStatus, LlmMode, Report, Verdict

DEFAULT_DATA = Path("data")
DEFAULT_REPORT = Path("out/report.json")
DEFAULT_SCHEMA = Path("schema/report.schema.json")


def _use_utf8() -> None:
    """Windows consoles default to cp1252, which cannot render the rupee sign."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _rule(title: str = "") -> None:
    print(f"\n{title}\n{'-' * 68}" if title else "-" * 68)


def cmd_generate(args: argparse.Namespace) -> int:
    data = build(seed=args.seed)
    paths = write_dataset(data, Path(args.out))
    truth = data.truth

    _rule("Generated")
    for name, path in paths.items():
        print(f"  {name:<12} {path}")
    print()
    print(f"  settlement rows   {truth.settlement_rows}")
    print(f"  order rows        {truth.order_rows}")
    print(f"  bank rows         {truth.bank_rows}")
    print(f"  batches           {len(truth.batches)}")
    print(f"  planted gap       {format_inr(truth.total_expected_gap)}")
    print(f"    detectable      {format_inr(truth.total_detectable)}")
    print(f"    undetectable    {format_inr(truth.total_undetectable)}")

    _rule("Planted cases")
    for case in truth.cases:
        targets = ", ".join(case.settlement_ids + case.bank_refs)
        print(f"  {case.number:>2}  {case.name:<42} {targets}")
    print(f"\n  truth.json is written but never read by the reconciler.")
    return 0


def _llm_mode(args: argparse.Namespace) -> LlmMode:
    return LlmMode(args.llm) if getattr(args, "llm", None) else resolve_mode()


def cmd_run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data)
    llm_mode = _llm_mode(args)
    report = run_pipeline(data_dir, seed=args.seed, llm_mode=llm_mode)

    # Scoring runs only after the reconciliation has finished and returned. The
    # pipeline cannot see truth.json; this can.
    truth_path = data_dir / "truth.json"
    if truth_path.exists():
        attach(report, truth_path)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="")
    print_scoreboard(report)
    if report.evaluation:
        print_cases(report)
    print(f"\n  report written to {out}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"  no report at {report_path} - run `recon run` first")
        return 1
    report = Report.model_validate_json(report_path.read_text(encoding="utf-8"))
    evaluation = score(report, load_truth(Path(args.data) / "truth.json"))
    report.evaluation = evaluation
    report.scoreboard.false_matches = evaluation.false_matches
    report.scoreboard.false_cause_attributions = evaluation.false_cause_attributions

    print_scoreboard(report)
    print_cases(report)
    print_eval_table(report)
    return 0 if evaluation.cases_failed == 0 else 1


def print_cases(report: Report) -> None:
    evaluation = report.evaluation
    if evaluation is None:
        return
    marks = {CaseStatus.PASS: "PASS", CaseStatus.FAIL: "FAIL", CaseStatus.PENDING: "...."}
    _rule("Planted cases, scored against truth")
    for case in evaluation.cases:
        print(f"  {marks[case.status]}  {case.number:>2}  {case.name}")
        print(f"              expected  {case.expected}")
        print(f"              observed  {case.actual}")
    print(
        f"\n  {evaluation.cases_passed} passed, {evaluation.cases_failed} failed, "
        f"{evaluation.cases_pending} awaiting a stage that is not built yet"
    )


def print_eval_table(report: Report) -> None:
    """System output against planted truth, cause by cause."""
    evaluation = report.evaluation
    if evaluation is None:
        return
    _rule("System output vs planted truth")
    print(f"  {'batch':<12} {'cause':<22} {'truth':>13} {'reported':>13}  verdict")
    for scored in evaluation.batches:
        if not scored.components:
            print(f"  {scored.settlement_id:<12} (nothing planted or reported)")
            continue
        for index, component in enumerate(scored.components):
            label = scored.settlement_id if index == 0 else ""
            flag = "" if component.verdict is Verdict.CORRECT else "  <--"
            print(
                f"  {label:<12} {component.kind.value:<22} "
                f"{format_inr(component.truth_amount):>13} "
                f"{format_inr(component.reported_amount):>13}  "
                f"{component.verdict.value}{flag}"
            )
    print(f"\n  gap attribution accuracy  {evaluation.gap_accuracy_pct:.1f}%")
    print(f"  false matches             {evaluation.false_matches}")
    print(f"  false cause attributions  {evaluation.false_cause_attributions}")


def print_scoreboard(report: Report) -> None:
    board = report.scoreboard
    _rule("Scoreboard")
    print(f"  Records processed        {board.records_processed:>7}")
    print(
        f"    settlements {board.settlement_rows}   orders {board.order_rows}   "
        f"bank {board.bank_rows}"
    )
    print(f"  Settlement batches       {board.settlement_batches:>7}")
    print(f"  Runtime                  {board.runtime_ms:>6}ms")
    print(
        f"  LLM                      {report.meta.llm_provider}/{report.meta.llm_mode.value}"
        f"   calls {report.meta.llm_calls}   cache hits {report.meta.llm_cache_hits}"
        f"   errors {report.meta.llm_errors}"
    )
    print()
    print(
        f"  Matched deterministically{board.matched_deterministic.n:>7}   "
        f"({board.matched_deterministic.pct:>5.1f}%)"
    )
    print(
        f"  Matched by inference     {board.matched_inference.n:>7}   "
        f"({board.matched_inference.pct:>5.1f}%)"
    )
    print(f"  Unmatched exceptions     {board.unmatched.n:>7}   ({board.unmatched.pct:>5.1f}%)")
    print()
    print(
        f"  Gap explained      {format_inr(board.gap_explained):>14}   "
        f"({board.gap_explained_pct:>5.1f}%)"
    )
    print(
        f"  Gap unexplained    {format_inr(board.gap_unexplained):>14}   "
        f"({board.gap_unexplained_pct:>5.1f}%)"
    )
    print()
    print(f"  FALSE MATCHES            {board.false_matches:>7}")
    print(f"  FALSE CAUSE ATTRIBUTIONS {board.false_cause_attributions:>7}")
    print()
    print(f"  deterministic hash  {report.meta.deterministic_hash}")

    if report.meta.llm_errors:
        # Loud on purpose. The reconciliation is still valid - every caller falls back
        # to a deterministic floor - but a run reported as "live" that never reached the
        # model is exactly the kind of thing that gets claimed on a slide by accident.
        print()
        print(f"  !! LLM DEGRADED: {report.meta.llm_errors} call"
              f"{'s' if report.meta.llm_errors != 1 else ''} failed and fell back to the "
              "deterministic stub.")
        if report.meta.llm_error_detail:
            print(f"     {report.meta.llm_error_detail}")
        print("     Results below came from rules, not from the model.")


def cmd_verify(args: argparse.Namespace) -> int:
    """Prove the two determinism claims: stable data, and a stable answer over it."""
    data_dir = Path(args.data)
    regenerated = build(seed=args.seed)
    on_disk = {
        "settlements.csv": (data_dir / "settlements.csv").read_text(encoding="utf-8"),
        "orders.csv": (data_dir / "orders.csv").read_text(encoding="utf-8"),
        "bank.csv": (data_dir / "bank.csv").read_text(encoding="utf-8"),
    }
    rebuilt = {
        "settlements.csv": render_settlements(regenerated.settlements),
        "orders.csv": render_orders(regenerated.orders),
        "bank.csv": render_bank(regenerated.bank),
    }

    _rule("Determinism")
    data_ok = True
    for name, text in on_disk.items():
        same = text == rebuilt[name]
        data_ok &= same
        print(f"  {'OK  ' if same else 'FAIL'}  {name} regenerates byte-identical from seed "
              f"{args.seed}")

    # A determinism check must not depend on the network. Two live calls can differ for
    # reasons that say nothing about this pipeline, and `verify` reads as a free local
    # check - it should not spend an API key nobody asked it to spend.
    llm_mode = LlmMode(args.llm) if getattr(args, "llm", None) else LlmMode.CACHE
    first = run_pipeline(data_dir, seed=args.seed, llm_mode=llm_mode)
    second = run_pipeline(data_dir, seed=args.seed, llm_mode=llm_mode)
    runs_ok = first.meta.deterministic_hash == second.meta.deterministic_hash
    print(f"  {'OK  ' if runs_ok else 'FAIL'}  two runs agree")
    print(f"        run 1  {first.meta.deterministic_hash}")
    print(f"        run 2  {second.meta.deterministic_hash}")
    print(f"        runtimes {first.meta.runtime_ms}ms and {second.meta.runtime_ms}ms differ, "
          "and are excluded from the hash")
    return 0 if (data_ok and runs_ok) else 1


def _mark_all_required(node: object) -> None:
    """Every field with a default is optional to Pydantic but always present on the wire.

    ``model_dump_json`` serialises defaults, so the server never omits a key. Saying so
    in the schema is both accurate and the difference between a UI typed on
    ``Scoreboard`` and one typed on ``Partial<Scoreboard>``.
    """
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict) and node.get("type") == "object":
            node["required"] = sorted(properties)
        for value in node.values():
            _mark_all_required(value)
    elif isinstance(node, list):
        for value in node:
            _mark_all_required(value)


def cmd_schema(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = Report.model_json_schema()
    schema["title"] = "Report"
    _mark_all_required(schema)
    out.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline=""
    )
    print(f"  report schema written to {out}  ({len(schema['$defs'])} definitions)")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from recon.api import create_app

    app = create_app(
        data_dir=Path(args.data),
        report_path=Path(args.report),
        seed=args.seed,
        llm_mode=_llm_mode(args),
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


_LLM_CHOICES = [mode.value for mode in LlmMode]


def _load_env() -> None:
    """Read .env into the environment, if one exists.

    Without this, a key sitting in .env is invisible: everything downstream reads
    ``os.environ`` directly, so mode resolution would quietly fall through to the
    cached fixtures and the run would look like it worked. Values already exported in
    the shell win, which is what makes ``PERPLEXITY_API_KEY=... recon run`` behave the
    way anyone would expect.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional dependency; exporting the variable still works
        return
    load_dotenv(Path(".env"), override=False)


def main(argv: list[str] | None = None) -> int:
    _use_utf8()
    _load_env()
    parser = argparse.ArgumentParser(prog="recon", description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="dataset seed (default: 42)")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="write the synthetic dataset and truth.json")
    generate.add_argument("--out", default=str(DEFAULT_DATA))
    generate.set_defaults(func=cmd_generate)

    run_cmd = sub.add_parser("run", help="reconcile and write the report")
    run_cmd.add_argument("--data", default=str(DEFAULT_DATA))
    run_cmd.add_argument("--out", default=str(DEFAULT_REPORT))
    run_cmd.add_argument(
        "--llm", choices=_LLM_CHOICES, default=None,
        help="stub|cache|live|off (default: auto - live if PERPLEXITY_API_KEY is set, "
        "else cache if fixtures exist, else stub)",
    )
    run_cmd.set_defaults(func=cmd_run)

    eval_cmd = sub.add_parser("eval", help="score the last report against planted truth")
    eval_cmd.add_argument("--data", default=str(DEFAULT_DATA))
    eval_cmd.add_argument("--report", default=str(DEFAULT_REPORT))
    eval_cmd.set_defaults(func=cmd_eval)

    verify = sub.add_parser("verify", help="prove the data and the run are reproducible")
    verify.add_argument("--data", default=str(DEFAULT_DATA))
    verify.add_argument("--llm", choices=_LLM_CHOICES, default=None)
    verify.set_defaults(func=cmd_verify)

    schema = sub.add_parser("schema", help="export the report JSON Schema")
    schema.add_argument("--out", default=str(DEFAULT_SCHEMA))
    schema.set_defaults(func=cmd_schema)

    serve = sub.add_parser("serve", help="serve the API and the built UI")
    serve.add_argument("--data", default=str(DEFAULT_DATA))
    serve.add_argument("--report", default=str(DEFAULT_REPORT))
    serve.add_argument("--llm", choices=_LLM_CHOICES, default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8020")))
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
