import type { BatchReport, Report } from "../types/report";
import { day, inr, stamp } from "../lib/format";
import { Badge, Empty, Note, Panel, Table, Td, Th } from "./ui";

function ruleBadge(batch: BatchReport) {
  const { rule, origin, confidence } = batch.match;
  if (rule === "none") return <Badge tone="warn">unmatched</Badge>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <Badge tone={origin === "inference" ? "info" : "ok"} title={batch.match.basis}>
        {rule}
      </Badge>
      <span className="num text-[11px] text-ink-faint">{confidence.toFixed(2)}</span>
    </span>
  );
}

/**
 * One row per settlement batch. Both expectations are shown side by side on
 * purpose: the settlement file and the merchant's order book disagree, and seeing
 * where they diverge is most of the diagnosis.
 */
export function BatchTable({
  report,
  onSelect,
}: {
  report: Report;
  onSelect: (settlementId: string) => void;
}) {
  if (report.batches.length === 0) {
    return (
      <Panel title="Settlement batches">
        <Empty>No batches yet. Run the reconciliation.</Empty>
      </Panel>
    );
  }

  return (
    <Panel title="Settlement batches" hint={`${report.batches.length} batches`}>
      <Table
        head={
          <tr>
            <Th>Settlement</Th>
            <Th>Settled</Th>
            <Th>Window covered</Th>
            <Th align="right">Rows</Th>
            <Th align="right">Gross</Th>
            <Th align="right">Orders expect</Th>
            <Th align="right">Bank credited</Th>
            <Th align="right">Gap</Th>
            <Th align="right">Explained</Th>
            <Th align="right">Residual</Th>
            <Th>Match</Th>
          </tr>
        }
      >
        {report.batches.map((batch) => (
          <tr
            key={batch.settlement_id}
            onClick={() => onSelect(batch.settlement_id)}
            className="cursor-pointer hover:bg-ground"
          >
            <Td mono>{batch.settlement_id}</Td>
            <Td mono muted>{stamp(batch.settled_at)}</Td>
            <Td mono muted>
              {day(batch.window_start)} → {day(batch.window_end)}
            </Td>
            <Td align="right" mono>
              {batch.row_count}
            </Td>
            <Td align="right" mono>
              {inr(batch.gross_settled)}
            </Td>
            <Td align="right" mono>
              {inr(batch.orders_expected)}
            </Td>
            <Td align="right" mono>
              {batch.bank_credit === null ? (
                <span className="text-ink-faint">not credited</span>
              ) : (
                inr(batch.bank_credit)
              )}
            </Td>
            <Td align="right" mono muted={batch.bank_credit === null}>
              {batch.bank_credit === null ? "—" : inr(batch.headline_gap)}
            </Td>
            <Td align="right" mono>
              {batch.bank_credit === null ? (
                <span className="text-ink-faint">—</span>
              ) : (
                inr(batch.explained)
              )}
            </Td>
            <Td align="right" mono>
              {batch.bank_credit === null ? (
                <span className="text-ink-faint">—</span>
              ) : (
                <span className={batch.residual === 0 ? "text-ok" : "text-warn"}>
                  {inr(batch.residual)}
                </span>
              )}
            </Td>
            <Td>{ruleBadge(batch)}</Td>
          </tr>
        ))}
      </Table>
      <Note>
        <strong>Orders expect</strong> is what the merchant's own records imply should arrive,
        knowing nothing about fees or adjustments. The distance between that and the bank is
        the gap a finance team actually sees — click any row to see what caused it. A residual
        of zero means every rupee of that gap was attributed to a recomputed cause.
      </Note>
    </Panel>
  );
}
