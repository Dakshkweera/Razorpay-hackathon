import type { Report } from "../types/report";
import { count } from "../lib/format";
import { Badge, Panel } from "./ui";

/** A per-source-file readout, distinct from the Scoreboard's aggregate throughput. */
export function DatasetSummary({ report }: { report: Report }) {
  const board = report.scoreboard;

  return (
    <Panel
      title="Dataset summary"
      hint={`${count(board.records_processed)} records across ${count(board.settlement_batches)} settlement batches`}
    >
      <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {report.normalise.map((file) => (
          <div key={file.file} className="px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-ink-faint">{file.file}</div>
            <div className="num mt-1 text-lg font-semibold text-ink">
              {count(file.rows_read)} <span className="text-[11px] font-normal text-ink-faint">rows</span>
            </div>
            <div className="mt-1">
              {file.rows_rejected > 0 ? (
                <Badge tone="bad">{count(file.rows_rejected)} rejected</Badge>
              ) : (
                <span className="text-[11px] text-ink-faint">all rows accepted</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}
