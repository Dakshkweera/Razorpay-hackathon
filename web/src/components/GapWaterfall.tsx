import type { BatchReport, GapComponent } from "../types/report";
import { inr } from "../lib/format";
import { Badge } from "./ui";

const KIND_LABEL: Record<GapComponent["kind"], string> = {
  fee: "Fee at contracted rate",
  gst_on_fee: "GST on fee",
  fee_rate_drift: "Fee charged above contract",
  cross_cycle_refund: "Refund across cycle boundary",
  unlinked_adjustment: "Adjustment with no order",
  rounding: "Rounding",
  unexplained: "Unexplained",
};

/**
 * The gap, broken into what caused it.
 *
 * Bars are drawn on magnitude against the largest component, so a small residue next
 * to a large fee stays visible. Components can legitimately be negative — a refund
 * documented in the wrong cycle leaves one batch short and its neighbour long — and
 * the sign is shown rather than smoothed away.
 */
export function GapWaterfall({ batch }: { batch: BatchReport }) {
  if (batch.components.length === 0) {
    return (
      <p className="px-4 py-5 text-center text-[12px] text-ink-faint">
        {batch.bank_credit === null
          ? "No credit arrived, so there is no gap to decompose."
          : "Nothing attributed."}
      </p>
    );
  }

  const widest = Math.max(...batch.components.map((c) => Math.abs(c.amount)), 1);

  return (
    <div>
      <div className="flex items-baseline justify-between border-b border-line px-4 py-2">
        <span className="text-[12px] text-ink-soft">
          Orders expected {inr(batch.orders_expected)}, bank credited{" "}
          {inr(batch.bank_credit ?? 0)}
        </span>
        <span className="num text-[13px] font-semibold">{inr(batch.headline_gap)}</span>
      </div>

      <ol className="divide-y divide-line">
        {batch.components.map((component, index) => {
          const magnitude = Math.abs(component.amount);
          const negative = component.amount < 0;
          const residue = component.kind === "unexplained";
          return (
            <li key={index} className="px-4 py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="flex items-baseline gap-2 text-[12px]">
                  <span className={residue ? "text-warn" : "text-ink"}>
                    {KIND_LABEL[component.kind]}
                  </span>
                  {residue && <Badge tone="warn">no cause committed</Badge>}
                  {component.source === "llm" && <Badge tone="info">inferred</Badge>}
                </span>
                <span
                  className={`num text-[12px] ${
                    residue ? "text-warn" : negative ? "text-info" : "text-ink"
                  }`}
                >
                  {inr(component.amount)}
                </span>
              </div>

              <div className="mt-1 h-1 w-full rounded-sm bg-ground">
                <div
                  className={`h-1 rounded-sm ${
                    residue ? "bg-warn" : negative ? "bg-info" : "bg-ok"
                  }`}
                  style={{ width: `${Math.max(2, (magnitude / widest) * 100)}%` }}
                />
              </div>

              <p className="mt-1 text-[11px] leading-relaxed text-ink-faint">
                <span className="num text-ink-soft">{component.check}</span> — {component.detail}
                {component.confidence !== null && (
                  <span className="num"> · confidence {component.confidence.toFixed(2)}</span>
                )}
              </p>
            </li>
          );
        })}
      </ol>

      <div className="flex items-baseline justify-between border-t border-line px-4 py-2">
        <span className="text-[12px] text-ink-soft">Residual after attribution</span>
        <span
          className={`num text-[13px] font-semibold ${
            batch.residual === 0 ? "text-ok" : "text-warn"
          }`}
        >
          {inr(batch.residual)}
        </span>
      </div>
    </div>
  );
}
