import type { BatchReport } from "../types/report";
import { day, inr, stamp } from "../lib/format";
import { GapWaterfall } from "./GapWaterfall";
import { Badge } from "./ui";

function Line({
  label,
  value,
  tone,
  note,
}: {
  label: string;
  value: string;
  tone?: "warn" | "ok";
  note?: string;
}) {
  const toneClass = tone === "warn" ? "text-warn" : tone === "ok" ? "text-ok" : "text-ink";
  return (
    <div className="flex items-baseline justify-between gap-6 border-b border-line px-4 py-1.5">
      <span className="text-[12px] text-ink-soft">
        {label}
        {note && <span className="ml-2 text-[11px] text-ink-faint">{note}</span>}
      </span>
      <span className={`num text-[12px] ${toneClass}`}>{value}</span>
    </div>
  );
}

/** Everything known about one batch, including how each conclusion was reached. */
export function BatchDetail({ batch, onClose }: { batch: BatchReport; onClose: () => void }) {
  const credited = batch.bank_credit !== null;

  return (
    <div className="fixed inset-0 z-20 flex justify-end bg-black/20" onClick={onClose}>
      <aside
        className="h-full w-full max-w-xl overflow-y-auto border-l border-line bg-surface"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-line bg-surface px-4 py-3">
          <div>
            <h2 className="num text-[14px] font-semibold">{batch.settlement_id}</h2>
            <p className="text-[11px] text-ink-faint">
              settled {stamp(batch.settled_at)} · covers {day(batch.window_start)} →{" "}
              {day(batch.window_end)}
            </p>
            <p className="mt-1 flex items-center gap-2">
              {batch.match.rule === "none" ? (
                <Badge tone="warn">unmatched</Badge>
              ) : (
                <>
                  <Badge tone={batch.match.origin === "inference" ? "info" : "ok"}>
                    {batch.match.rule}
                  </Badge>
                  <span className="num text-[11px] text-ink-faint">
                    {batch.match.bank_ref} · confidence {batch.match.confidence.toFixed(2)}
                  </span>
                </>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-line px-2 py-1 text-[11px] text-ink-soft hover:bg-ground"
          >
            Close
          </button>
        </header>

        <section className="py-1">
          <Line
            label="Gross settled"
            note={`${batch.payment_count} payments, ${batch.refund_count} refunds, ${batch.adjustment_count} adjustments`}
            value={inr(batch.gross_settled)}
          />
          <Line label="Fee" value={inr(batch.total_fee)} />
          <Line label="GST on fee" value={inr(batch.total_tax)} />
          <Line
            label="Settlement expects"
            note="gross less fee and GST"
            value={inr(batch.settlement_expected_credit)}
          />
          <Line
            label="Orders expect"
            note="from the merchant's own records"
            value={inr(batch.orders_expected)}
          />
          <Line
            label="Bank credited"
            value={credited ? inr(batch.bank_credit!) : "nothing arrived"}
            tone={credited ? undefined : "warn"}
          />
          {credited && (
            <Line
              label="Settlement residual"
              note="what the settlement file itself says is missing"
              value={inr(batch.settlement_residual)}
              tone={batch.settlement_residual === 0 ? "ok" : "warn"}
            />
          )}
        </section>

        <div className="border-b border-line">
          <h3 className="px-4 pt-3 text-[11px] uppercase tracking-wide text-ink-faint">
            Gap decomposition
          </h3>
          <GapWaterfall batch={batch} />
        </div>

        {batch.bank_narration && (
          <div className="border-b border-line px-4 py-2.5">
            <h3 className="mb-1 text-[11px] uppercase tracking-wide text-ink-faint">
              Matched bank line
            </h3>
            <p className="num text-[11px] leading-relaxed text-ink-soft">
              {batch.bank_ref} · {batch.bank_date} · {batch.bank_narration}
            </p>
          </div>
        )}

        <div className="px-4 py-2.5">
          <h3 className="mb-2 text-[11px] uppercase tracking-wide text-ink-faint">Trace</h3>
          <ol className="space-y-1.5">
            {batch.trace.map((entry, index) => (
              <li key={index} className="flex gap-2 text-[11px]">
                <span className="num w-16 shrink-0 text-ink-faint">{entry.stage}</span>
                <span className="num w-40 shrink-0 font-medium">{entry.action}</span>
                <span className="text-ink-soft">{entry.detail}</span>
              </li>
            ))}
          </ol>
        </div>
      </aside>
    </div>
  );
}
