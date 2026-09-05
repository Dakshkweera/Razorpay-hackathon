import type { Report } from "../types/report";
import { count, inr, pct } from "../lib/format";
import { Badge, Note, Panel, Stat } from "./ui";

/**
 * The scoreboard. Its point is the bottom row: a wrong match is worse than an
 * honest gap, because it closes the books on a real problem. Those two counters
 * are therefore given the most weight on the page.
 */
export function ScoreboardPanel({ report }: { report: Report }) {
  const board = report.scoreboard;
  const clean = board.false_matches === 0 && board.false_cause_attributions === 0;

  const matchedBatches = report.batches.filter((batch) => batch.bank_credit !== null);
  const ordersTotal = matchedBatches.reduce((sum, batch) => sum + batch.orders_expected, 0);
  const razorpayTotal = matchedBatches.reduce((sum, batch) => sum + batch.settlement_expected_credit, 0);
  const bankTotal = matchedBatches.reduce((sum, batch) => sum + (batch.bank_credit ?? 0), 0);

  return (
    <div className="grid gap-3">
      <Panel title="Headline" hint="order value, what Razorpay settled, what the bank actually credited">
        <div className="grid grid-cols-2 divide-x divide-y divide-line sm:grid-cols-4 sm:divide-y-0">
          <HeadlineStat label="Order value sold" value={inr(ordersTotal)} tone="plain" />
          <HeadlineStat label="Razorpay settlement" value={inr(razorpayTotal)} tone="info" />
          <HeadlineStat label="Bank credit received" value={inr(bankTotal)} tone="ok" />
          <HeadlineStat
            label="Gap"
            value={inr(board.gap_total)}
            tone={board.gap_total > 0 ? "warn" : "ok"}
          />
        </div>
      </Panel>

      <Panel title="Throughput" hint="one run, measured">
        <div className="grid grid-cols-2 divide-x divide-line sm:grid-cols-4">
          <Stat
            label="Records processed"
            value={count(board.records_processed)}
            sub={`${count(board.settlement_rows)} settlement · ${count(board.order_rows)} order · ${count(board.bank_rows)} bank`}
          />
          <Stat label="Settlement batches" value={count(board.settlement_batches)} />
          <Stat label="Runtime" value={`${count(board.runtime_ms)} ms`} />
          <Stat
            label="Reproducibility"
            value={report.meta.deterministic_hash ? "hashed" : "—"}
            sub={report.meta.deterministic_hash.slice(0, 16)}
          />
        </div>
      </Panel>

      <Panel title="LLM" hint="deterministic where money is concerned; AI only over unstructured text">
        {/* A run that never reached the model must never look like one that did. Every
            caller falls back to a deterministic floor so nothing crashes, which is
            exactly why the failure has to be stated here rather than inferred from a
            call count nobody reads. */}
        {report.meta.llm_errors > 0 && (
          <div className="border-b border-line bg-bad-soft px-4 py-2.5">
            <p className="text-[12px] font-semibold text-bad">
              Degraded — {count(report.meta.llm_errors)}{" "}
              {report.meta.llm_errors === 1 ? "call" : "calls"} failed and fell back to
              the deterministic stub.
            </p>
            {report.meta.llm_error_detail && (
              <p className="num mt-1 text-[11px] leading-relaxed text-ink-soft">
                {report.meta.llm_error_detail}
              </p>
            )}
            <p className="mt-1 text-[11px] text-ink-soft">
              The reconciliation below is still valid, but its narration reading and
              residue classification came from rules, not from the model.
            </p>
          </div>
        )}
        <div className="grid grid-cols-2 divide-x divide-line sm:grid-cols-4">
          <Stat
            label="Provider"
            value={report.meta.llm_provider}
            sub={report.meta.llm_mode}
            tone={report.meta.llm_errors > 0 ? "bad" : "plain"}
          />
          <Stat label="Calls" value={count(report.meta.llm_calls)} />
          <Stat
            label={report.meta.llm_errors > 0 ? "Failed calls" : "Cache hits"}
            value={count(
              report.meta.llm_errors > 0
                ? report.meta.llm_errors
                : report.meta.llm_cache_hits,
            )}
            tone={report.meta.llm_errors > 0 ? "bad" : "plain"}
          />
          <Stat
            label="Matched by inference"
            value={count(board.matched_inference.n)}
            sub={pct(board.matched_inference.pct)}
          />
        </div>
        <Note>
          {report.meta.llm_mode === "off"
            ? "The model was not consulted this run; narration reading and residue "
              + "classification fell back to their deterministic floor."
            : "Narration extraction (batched, cached) and residue classification "
              + "(0.70 confidence threshold) are the only two places a model runs. "
              + "See the Narrations tab for what it read, and the exception cards below "
              + "for what it refused to classify."}
        </Note>
      </Panel>

      <Panel title="Match rate" hint="deterministic rules first; inference is measured separately">
        <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <Stat
            label="Matched deterministically"
            value={count(board.matched_deterministic.n)}
            sub={pct(board.matched_deterministic.pct)}
            tone="ok"
          />
          <Stat
            label="Matched by inference"
            value={count(board.matched_inference.n)}
            sub={pct(board.matched_inference.pct)}
          />
          <Stat
            label="Unmatched exceptions"
            value={count(board.unmatched.n)}
            sub={pct(board.unmatched.pct)}
            tone="warn"
          />
        </div>
        <Note>
          An unmatched batch is a reported outcome, not a failure. The exception list below
          says what was tried before giving up on each one.
        </Note>
      </Panel>

      <Panel title="Gap attribution">
        <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <Stat label="Gap observed" value={inr(board.gap_total)} />
          <Stat
            label="Explained"
            value={inr(board.gap_explained)}
            sub={pct(board.gap_explained_pct)}
            tone="ok"
          />
          <Stat
            label="Unexplained"
            value={inr(board.gap_unexplained)}
            sub={pct(board.gap_unexplained_pct)}
            tone="warn"
          />
        </div>
      </Panel>

      <Panel
        title="Correctness"
        hint={clean ? "verified against planted truth" : "review before reporting"}
        right={
          <Badge tone={clean ? "ok" : "bad"}>
            {clean ? "✓ Verified accurate" : "Needs review"}
          </Badge>
        }
      >
        {clean && (
          <div className="border-b border-line bg-ok-soft px-4 py-3">
            <p className="text-[13px] font-semibold text-ok">
              {report.evaluation
                ? `${count(report.evaluation.cases_passed)} of ${count(report.evaluation.cases_total)} planted cases verified correct — zero wrong matches, zero wrong causes.`
                : "Zero wrong matches, zero wrong causes against the planted truth file."}
            </p>
          </div>
        )}
        <div className="grid grid-cols-2 divide-x divide-line">
          <Stat
            label="False matches"
            value={count(board.false_matches)}
            tone={board.false_matches === 0 ? "ok" : "bad"}
            emphasis
          />
          <Stat
            label="False cause attributions"
            value={count(board.false_cause_attributions)}
            tone={board.false_cause_attributions === 0 ? "ok" : "bad"}
            emphasis
          />
        </div>
        <Note>
          Both are counted against a truth file the reconciler never reads. Zero here is the
          best possible score — a wrong match is worse than an honest gap, because it closes
          the books on a real problem.
        </Note>
      </Panel>
    </div>
  );
}

function HeadlineStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "plain" | "ok" | "warn" | "bad" | "info";
}) {
  const toneClass = {
    plain: "text-ink",
    ok: "text-ok",
    warn: "text-warn",
    bad: "text-bad",
    info: "text-info",
  }[tone];
  return (
    <div className="px-4 py-4">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</div>
      <div className={`num mt-1.5 text-[26px] font-bold leading-none sm:text-[32px] ${toneClass}`}>
        {value}
      </div>
    </div>
  );
}
