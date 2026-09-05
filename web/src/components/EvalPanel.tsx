import type { CaseStatus, Report, Verdict } from "../types/report";
import { inr, pct } from "../lib/format";
import { Badge, Empty, Note, Panel, Table, Td, Th } from "./ui";

const CASE_TONE: Record<CaseStatus, "ok" | "bad" | "neutral"> = {
  pass: "ok",
  fail: "bad",
  pending: "neutral",
};

const CASE_LABEL: Record<CaseStatus, string> = {
  pass: "pass",
  fail: "fail",
  pending: "pending",
};

const VERDICT_TONE: Record<Verdict, "ok" | "warn" | "bad"> = {
  correct: "ok",
  missed: "warn",
  over_attributed: "bad",
  false_cause: "bad",
};

/**
 * The direct answer to "one cherry-picked match proves nothing": every planted case
 * scored, and every attributed cause set beside the truth it was never shown.
 *
 * `pending` is its own state rather than a failure. A stage that has not been built
 * and a stage that is broken are different facts, and collapsing them would flatter
 * the run.
 */
export function EvalPanel({ report }: { report: Report }) {
  const evaluation = report.evaluation;
  if (!evaluation) {
    return (
      <Panel title="Evaluation">
        <Empty>
          No scoring available. The reconciler runs without the truth file; scoring
          happens afterwards and needs data/truth.json.
        </Empty>
      </Panel>
    );
  }

  const scored = evaluation.batches.filter((batch) => batch.components.length > 0);

  return (
    <div className="grid gap-3">
      <Panel
        title="Planted cases"
        hint={`${evaluation.cases_passed} passed · ${evaluation.cases_failed} failed · ${evaluation.cases_pending} pending`}
      >
        <Table
          head={
            <tr>
              <Th>#</Th>
              <Th>Case</Th>
              <Th>Expected</Th>
              <Th>Observed</Th>
              <Th>Result</Th>
            </tr>
          }
        >
          {evaluation.cases.map((entry) => (
            <tr key={entry.number}>
              <Td mono muted>
                {entry.number}
              </Td>
              <Td>{entry.name}</Td>
              <Td muted>{entry.expected}</Td>
              <Td>{entry.actual}</Td>
              <Td>
                <Badge tone={CASE_TONE[entry.status]}>{CASE_LABEL[entry.status]}</Badge>
              </Td>
            </tr>
          ))}
        </Table>
        <Note>
          Scored against a truth file the reconciler never reads. Cases marked pending are
          waiting on a stage that has not been built yet, not on a failure.
        </Note>
      </Panel>

      <Panel
        title="Attributed causes vs planted truth"
        hint={`${pct(evaluation.gap_accuracy_pct)} of detectable gap attributed correctly`}
      >
        {scored.length === 0 ? (
          <Empty>
            No gap components attributed yet — decomposition lands in the next stage.
          </Empty>
        ) : (
          <Table
            head={
              <tr>
                <Th>Batch</Th>
                <Th>Cause</Th>
                <Th align="right">Planted</Th>
                <Th align="right">Reported</Th>
                <Th>Verdict</Th>
              </tr>
            }
          >
            {scored.flatMap((batch) =>
              batch.components.map((component, index) => (
                <tr key={`${batch.settlement_id}-${component.kind}`}>
                  <Td mono muted>
                    {index === 0 ? batch.settlement_id : ""}
                  </Td>
                  <Td>{component.kind.replace(/_/g, " ")}</Td>
                  <Td align="right" mono>
                    {inr(component.truth_amount)}
                  </Td>
                  <Td align="right" mono>
                    {inr(component.reported_amount)}
                  </Td>
                  <Td>
                    <Badge tone={VERDICT_TONE[component.verdict]}>
                      {component.verdict.replace(/_/g, " ")}
                    </Badge>
                  </Td>
                </tr>
              )),
            )}
          </Table>
        )}
      </Panel>

      <Panel title="Errors">
        <div className="grid grid-cols-2 divide-x divide-line">
          <div className="px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-ink-faint">
              False matches
            </div>
            <div
              className={`num mt-1 text-2xl font-semibold ${
                evaluation.false_matches === 0 ? "text-ok" : "text-bad"
              }`}
            >
              {evaluation.false_matches}
            </div>
          </div>
          <div className="px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-ink-faint">
              False cause attributions
            </div>
            <div
              className={`num mt-1 text-2xl font-semibold ${
                evaluation.false_cause_attributions === 0 ? "text-ok" : "text-bad"
              }`}
            >
              {evaluation.false_cause_attributions}
            </div>
          </div>
        </div>
        <Note>
          Declining to match, and reporting an amount as unexplained, are never counted as
          errors here. Refusing to answer is the correct answer wherever the evidence runs
          out.
        </Note>
      </Panel>
    </div>
  );
}
