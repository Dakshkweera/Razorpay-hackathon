import type { ExceptionKind, ExceptionReport, Report } from "../types/report";
import { inr } from "../lib/format";
import { Badge, Empty, Note, Panel } from "./ui";

const KIND_LABEL: Record<ExceptionKind, string> = {
  ambiguous_match: "ambiguous",
  duplicate_utr: "duplicate posting",
  unmatched_bank_credit: "unexplained credit",
  unmatched_settlement: "not credited",
  unexplained_residue: "unexplained residue",
};

const KIND_TONE: Record<ExceptionKind, "warn" | "bad" | "info"> = {
  ambiguous_match: "warn",
  duplicate_utr: "info",
  unmatched_bank_credit: "bad",
  unmatched_settlement: "warn",
  unexplained_residue: "bad",
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 px-4 py-1.5">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</div>
      <div className="text-[12px] leading-relaxed text-ink-soft">{children}</div>
    </div>
  );
}

/**
 * One card per exception, in the shape the PRD asks for: what, what was tried, what
 * was ruled out, what would resolve it.
 *
 * `Tried` and `Ruled out` are the difference between "we could not explain this" and
 * "we did not look" — a finance team can act on the first and cannot act on the
 * second. That is why this list is worth as much as the match rate.
 */
function ExceptionCard({ exception }: { exception: ExceptionReport }) {
  const belowThreshold =
    exception.confidence !== null &&
    exception.threshold !== null &&
    exception.confidence < exception.threshold;

  return (
    <article className="rounded-md border border-line bg-surface">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
        <span className="num text-[13px] font-semibold">{exception.id}</span>
        <span className="num text-[13px]">{inr(exception.amount)}</span>
        <Badge tone={KIND_TONE[exception.kind]}>{KIND_LABEL[exception.kind]}</Badge>
        <span className="num text-[11px] text-ink-faint">
          {exception.settlement_id ?? exception.bank_ref}
        </span>
      </header>

      <Section label="What">{exception.what}</Section>

      {exception.tried.length > 0 && (
        <Section label="Tried">
          <ul className="space-y-0.5">
            {exception.tried.map((attempt, index) => (
              <li key={index} className="flex flex-wrap gap-x-2">
                <span className="num text-ink">{attempt.check}</span>
                <span>{attempt.outcome}</span>
                {attempt.attributed !== null && (
                  <span className="num text-ok">{inr(attempt.attributed)} accounted for</span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {exception.ruled_out.length > 0 && (
        <Section label="Ruled out">
          <ul className="space-y-0.5">
            {exception.ruled_out.map((entry, index) => (
              <li key={index} className="flex flex-wrap gap-x-2">
                <span className="num text-ink">{entry.check}</span>
                <span>{entry.reason}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {exception.candidates.length > 0 && (
        <Section label="Candidates">
          <span className="num">{exception.candidates.join(", ")}</span>
        </Section>
      )}

      <Section label="Needs">{exception.needs}</Section>

      {exception.confidence !== null && (
        <Section label="Confidence">
          <span className="num">
            {exception.confidence.toFixed(2)}
            {exception.threshold !== null && ` against a threshold of ${exception.threshold}`}
          </span>
          {belowThreshold && (
            <span className="text-warn"> — below threshold, so nothing was attributed.</span>
          )}
        </Section>
      )}
    </article>
  );
}

export function ExceptionsPanel({ report }: { report: Report }) {
  const total = report.exceptions.reduce(
    (sum, exception) => sum + Math.abs(exception.amount),
    0,
  );

  if (report.exceptions.length === 0) {
    return (
      <Panel title="Exceptions">
        <Empty>
          Nothing unresolved. For a run of this size that is worth double-checking rather
          than celebrating.
        </Empty>
      </Panel>
    );
  }

  return (
    <div className="grid gap-3">
      <Panel
        title="Exceptions"
        hint={`${report.exceptions.length} open · ${inr(total)} at stake`}
      >
        <Note>
          Every entry below is money the system declined to reconcile. Each says what was
          tried and what would settle it, because an exception a person cannot act on is
          just a different way of losing the problem.
        </Note>
      </Panel>

      {report.exceptions.map((exception) => (
        <ExceptionCard key={exception.id} exception={exception} />
      ))}

      {report.unmatched_bank_rows.length > 0 && (
        <Panel
          title="Credits not tied to a settlement"
          hint={`${report.unmatched_bank_rows.length} lines`}
        >
          <ul className="divide-y divide-line">
            {report.unmatched_bank_rows.map((row) => (
              <li key={row.ref} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2">
                <span className="num text-[12px]">{row.ref}</span>
                <span className="num text-[12px]">{inr(row.credit)}</span>
                <span className="num text-[11px] text-ink-faint">{row.date}</span>
                <span className="text-[11px] text-ink-soft">{row.reason}</span>
                <span className="num w-full truncate text-[11px] text-ink-faint">
                  {row.narration}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
