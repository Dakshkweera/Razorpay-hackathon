import ExcelJS from "exceljs";
import type {
  BatchReport,
  ComponentKind,
  ExceptionReport,
  Report,
} from "../types/report";
import { stamp } from "./format";

const RUPEE_FMT = '"₹"#,##0.00;[Red]-"₹"#,##0.00';
const PCT_FMT = "0.0%";

const INK = "FF1B1A18";
const WHITE = "FFFFFFFF";
const LINE = "FFE7E5E1";
const OK = "FF0F7B46";
const OK_SOFT = "FFE8F4ED";
const WARN = "FF9A6700";
const WARN_SOFT = "FFFDF5E3";
const BAD = "FFB42318";
const BAD_SOFT = "FFFDECEB";
const INFO = "FF2C5D9B";
const FAINT = "FF8A867E";

const GAP_LABEL: Record<ComponentKind, string> = {
  fee: "Fee at contracted rate",
  gst_on_fee: "GST on fee",
  fee_rate_drift: "Fee charged above contracted rate",
  cross_cycle_refund: "Refund documented in an adjacent cycle",
  unlinked_adjustment: "Adjustment with no linked order",
  rounding: "Bank rounding to whole rupees",
  unexplained: "Unexplained — no cause in any of the three files",
};

function rupees(paise: number): number {
  return paise / 100;
}

function fill(argb: string): ExcelJS.Fill {
  return { type: "pattern", pattern: "solid", fgColor: { argb } };
}

function thinBorder(argb: string): Partial<ExcelJS.Borders> {
  return {
    top: { style: "thin", color: { argb } },
    bottom: { style: "thin", color: { argb } },
    left: { style: "thin", color: { argb } },
    right: { style: "thin", color: { argb } },
  };
}

function styleHeaderRow(row: ExcelJS.Row) {
  row.eachCell((cell) => {
    cell.font = { bold: true, color: { argb: WHITE }, size: 10 };
    cell.fill = fill(INK);
    cell.alignment = { vertical: "middle", horizontal: "left" };
    cell.border = thinBorder(INK);
  });
  row.height = 20;
}

function titleBand(sheet: ExcelJS.Worksheet, title: string, subtitle: string, span: number) {
  sheet.mergeCells(1, 1, 1, span);
  const titleCell = sheet.getCell(1, 1);
  titleCell.value = title;
  titleCell.font = { bold: true, size: 16, color: { argb: INK } };
  titleCell.alignment = { vertical: "middle" };
  sheet.getRow(1).height = 28;

  sheet.mergeCells(2, 1, 2, span);
  const subCell = sheet.getCell(2, 1);
  subCell.value = subtitle;
  subCell.font = { size: 10, color: { argb: FAINT } };
  sheet.getRow(3).height = 6;
}

function batchReason(batch: BatchReport): string {
  if (batch.bank_credit === null) {
    return "No bank credit received within the statement window — unresolved, likely timing.";
  }
  if (batch.match.rule === "none") {
    return "No confident match against any bank credit — see the Exceptions sheet for what was tried.";
  }
  if (batch.components.length === 0) {
    return "Clean match — the bank credit ties out exactly to what was expected.";
  }
  const causes = batch.components.map((component) => GAP_LABEL[component.kind]).join("; ");
  if (batch.residual !== 0) {
    return `${causes}. ${rupees(batch.residual).toFixed(2)} remains unexplained.`;
  }
  return causes;
}

/** Builds the same numbers the app shows, laid out as a report a finance team can file. */
export async function buildExcelReport(report: Report): Promise<Blob> {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "Settlement Explainer";
  workbook.created = new Date();

  const board = report.scoreboard;
  const generatedAt = report.meta.run_at ? stamp(report.meta.run_at) : "just now";
  const subtitle = `Generated ${generatedAt} · seed ${report.meta.seed} · run ${report.meta.deterministic_hash.slice(0, 16)}`;

  // ---------------------------------------------------------------- Summary
  const summary = workbook.addWorksheet("Summary", { views: [{ showGridLines: false }] });
  summary.columns = [{ width: 34 }, { width: 22 }, { width: 44 }];
  titleBand(summary, "Settlement Reconciliation Report", subtitle, 3);

  const kpiHeader = summary.addRow(["Metric", "Value", "Detail"]);
  styleHeaderRow(kpiHeader);

  type KpiRow = [string, number | string, string, string?];
  const kpis: KpiRow[] = [
    ["Records processed", board.records_processed, `${board.settlement_rows} settlement · ${board.order_rows} order · ${board.bank_rows} bank`],
    ["Settlement batches", board.settlement_batches, ""],
    ["Runtime", `${board.runtime_ms} ms`, ""],
    ["Gap observed", rupees(board.gap_total), "", "currency"],
    ["Gap explained", rupees(board.gap_explained), `${board.gap_explained_pct.toFixed(1)}% of the gap`, "currency"],
    ["Gap unexplained", rupees(board.gap_unexplained), `${board.gap_unexplained_pct.toFixed(1)}% of the gap`, "currency"],
    ["Matched deterministically", board.matched_deterministic.n, `${board.matched_deterministic.pct.toFixed(1)}% of batches`],
    ["Matched by AI inference", board.matched_inference.n, `${board.matched_inference.pct.toFixed(1)}% of batches`],
    ["Unmatched exceptions", board.unmatched.n, `${board.unmatched.pct.toFixed(1)}% of batches`],
    ["False matches (scored against planted truth)", board.false_matches, "0 is the best possible score"],
    ["False cause attributions (scored against planted truth)", board.false_cause_attributions, "0 is the best possible score"],
    ["LLM provider / mode", report.meta.llm_provider, report.meta.llm_mode],
    ["LLM calls (cache hits)", report.meta.llm_calls, `${report.meta.llm_cache_hits} served from cache`],
  ];

  for (const [metric, value, detail, kind] of kpis) {
    const row = summary.addRow([metric, value, detail]);
    row.getCell(1).font = { color: { argb: INK }, size: 10 };
    const valueCell = row.getCell(2);
    valueCell.font = { bold: true, size: 10, color: { argb: INK } };
    valueCell.alignment = { horizontal: "right" };
    if (kind === "currency") valueCell.numFmt = RUPEE_FMT;
    if (metric.startsWith("False") && typeof value === "number") {
      valueCell.font = { bold: true, size: 10, color: { argb: value === 0 ? OK : BAD } };
    }
    row.getCell(3).font = { size: 9, color: { argb: FAINT } };
    row.eachCell((cell) => (cell.border = { bottom: { style: "hair", color: { argb: LINE } } }));
  }

  // -------------------------------------------------------- Batch reconciliation
  const batches = workbook.addWorksheet("Batch Reconciliation", {
    views: [{ state: "frozen", xSplit: 1, ySplit: 4, showGridLines: false }],
  });
  batches.columns = [
    { header: "Settlement", key: "id", width: 14 },
    { header: "Settled at", key: "settled", width: 18 },
    { header: "Window start", key: "ws", width: 12 },
    { header: "Window end", key: "we", width: 12 },
    { header: "Rows", key: "rows", width: 8 },
    { header: "Gross settled", key: "gross", width: 14 },
    { header: "Orders expect (should arrive)", key: "expect", width: 20 },
    { header: "Bank credited (what arrived)", key: "credited", width: 20 },
    { header: "Gap (difference)", key: "gap", width: 15 },
    { header: "Explained", key: "explained", width: 14 },
    { header: "Residual", key: "residual", width: 13 },
    { header: "Status", key: "status", width: 11 },
    { header: "Rule", key: "rule", width: 8 },
    { header: "Origin", key: "origin", width: 14 },
    { header: "Confidence", key: "confidence", width: 11 },
    { header: "Reason", key: "reason", width: 55 },
  ];
  titleBand(batches, "Batch Reconciliation", "Every rupee expected against every rupee credited, and why they differ", 16);
  batches.getRow(4).values = batches.columns.map((c) => c.header as string);
  styleHeaderRow(batches.getRow(4));
  batches.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: 16 } };

  for (const batch of report.batches) {
    const matched = batch.match.rule !== "none";
    const row = batches.addRow({
      id: batch.settlement_id,
      settled: stamp(batch.settled_at),
      ws: batch.window_start.slice(0, 10),
      we: batch.window_end.slice(0, 10),
      rows: batch.row_count,
      gross: rupees(batch.gross_settled),
      expect: rupees(batch.orders_expected),
      credited: batch.bank_credit === null ? "Not credited" : rupees(batch.bank_credit),
      gap: batch.bank_credit === null ? "—" : rupees(batch.headline_gap),
      explained: batch.bank_credit === null ? "—" : rupees(batch.explained),
      residual: batch.bank_credit === null ? "—" : rupees(batch.residual),
      status: matched ? "Matched" : "Unmatched",
      rule: matched ? batch.match.rule : "—",
      origin: matched ? batch.match.origin : "—",
      confidence: matched ? batch.match.confidence : null,
      reason: batchReason(batch),
    });

    ["gross", "expect"].forEach((key) => {
      const cell = row.getCell(batches.getColumn(key).number);
      cell.numFmt = RUPEE_FMT;
    });
    for (const key of ["credited", "gap", "explained", "residual"]) {
      const cell = row.getCell(batches.getColumn(key).number);
      if (typeof cell.value === "number") cell.numFmt = RUPEE_FMT;
    }
    const confCell = row.getCell(batches.getColumn("confidence").number);
    if (typeof confCell.value === "number") confCell.numFmt = PCT_FMT;

    const statusCell = row.getCell(batches.getColumn("status").number);
    statusCell.font = { bold: true, color: { argb: matched ? OK : WARN } };
    statusCell.fill = fill(matched ? OK_SOFT : WARN_SOFT);
    statusCell.alignment = { horizontal: "center" };

    if (matched) {
      const residualCell = row.getCell(batches.getColumn("residual").number);
      if (typeof residualCell.value === "number" && residualCell.value !== 0) {
        residualCell.font = { color: { argb: WARN }, bold: true };
      }
      const originCell = row.getCell(batches.getColumn("origin").number);
      if (batch.match.origin === "inference") {
        originCell.font = { color: { argb: INFO }, italic: true };
      }
    }

    row.eachCell((cell) => (cell.border = { bottom: { style: "hair", color: { argb: LINE } } }));
    row.getCell(batches.getColumn("reason").number).alignment = { wrapText: true, vertical: "top" };
  }

  // -------------------------------------------------------------- Gap decomposition
  const decomposition = workbook.addWorksheet("Gap Decomposition", {
    views: [{ state: "frozen", ySplit: 4, showGridLines: false }],
  });
  decomposition.columns = [
    { header: "Settlement", key: "id", width: 14 },
    { header: "Cause", key: "cause", width: 42 },
    { header: "Amount", key: "amount", width: 14 },
    { header: "Source", key: "source", width: 16 },
    { header: "Check performed", key: "check", width: 26 },
    { header: "Detail", key: "detail", width: 60 },
    { header: "Confidence", key: "confidence", width: 11 },
  ];
  titleBand(decomposition, "Gap Decomposition", "What was subtracted from every gap, and how it was verified", 7);
  decomposition.getRow(4).values = decomposition.columns.map((c) => c.header as string);
  styleHeaderRow(decomposition.getRow(4));
  decomposition.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: 7 } };

  for (const batch of report.batches) {
    for (const component of batch.components) {
      const row = decomposition.addRow({
        id: batch.settlement_id,
        cause: GAP_LABEL[component.kind],
        amount: rupees(component.amount),
        source: component.source === "llm" ? "AI-inferred" : "Rule-based",
        check: component.check,
        detail: component.detail,
        confidence: component.confidence,
      });
      row.getCell(decomposition.getColumn("amount").number).numFmt = RUPEE_FMT;
      const confCell = row.getCell(decomposition.getColumn("confidence").number);
      if (typeof confCell.value === "number") confCell.numFmt = PCT_FMT;
      row.getCell(decomposition.getColumn("detail").number).alignment = {
        wrapText: true,
        vertical: "top",
      };
      if (component.kind === "unexplained") {
        const causeCell = row.getCell(decomposition.getColumn("cause").number);
        causeCell.font = { color: { argb: BAD }, bold: true };
        causeCell.fill = fill(BAD_SOFT);
      } else if (component.source === "llm") {
        const sourceCell = row.getCell(decomposition.getColumn("source").number);
        sourceCell.font = { color: { argb: INFO }, italic: true };
      }
      row.eachCell((cell) => (cell.border = { bottom: { style: "hair", color: { argb: LINE } } }));
    }
  }

  // ------------------------------------------------------------------ Exceptions
  const exceptions = workbook.addWorksheet("Exceptions", {
    views: [{ state: "frozen", ySplit: 4, showGridLines: false }],
  });
  exceptions.columns = [
    { header: "ID", key: "id", width: 10 },
    { header: "Kind", key: "kind", width: 18 },
    { header: "Reference", key: "ref", width: 16 },
    { header: "Amount", key: "amount", width: 14 },
    { header: "What", key: "what", width: 46 },
    { header: "Tried", key: "tried", width: 46 },
    { header: "Ruled out", key: "ruled_out", width: 40 },
    { header: "Needs", key: "needs", width: 40 },
    { header: "Confidence", key: "confidence", width: 11 },
  ];
  titleBand(
    exceptions,
    "Exceptions",
    "Money the system declined to reconcile, and exactly what would settle it",
    9,
  );
  exceptions.getRow(4).values = exceptions.columns.map((c) => c.header as string);
  styleHeaderRow(exceptions.getRow(4));
  exceptions.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: 9 } };

  const describeException = (exception: ExceptionReport) => ({
    id: exception.id,
    kind: exception.kind.replace(/_/g, " "),
    ref: exception.settlement_id ?? exception.bank_ref ?? "—",
    amount: rupees(exception.amount),
    what: exception.what,
    tried: exception.tried.map((t) => `${t.check}: ${t.outcome}`).join(" | "),
    ruled_out: exception.ruled_out.map((r) => `${r.check}: ${r.reason}`).join(" | "),
    needs: exception.needs,
    confidence: exception.confidence,
  });

  for (const exception of report.exceptions) {
    const row = exceptions.addRow(describeException(exception));
    row.getCell(exceptions.getColumn("amount").number).numFmt = RUPEE_FMT;
    const confCell = row.getCell(exceptions.getColumn("confidence").number);
    if (typeof confCell.value === "number") confCell.numFmt = PCT_FMT;
    for (const key of ["what", "tried", "ruled_out", "needs"]) {
      row.getCell(exceptions.getColumn(key).number).alignment = { wrapText: true, vertical: "top" };
    }
    const kindCell = row.getCell(exceptions.getColumn("kind").number);
    kindCell.font = { color: { argb: WARN }, bold: true };
    kindCell.fill = fill(WARN_SOFT);
    row.eachCell((cell) => (cell.border = { bottom: { style: "hair", color: { argb: LINE } } }));
  }

  // ------------------------------------------------------------------ Narrations
  if (report.narrations.length > 0) {
    const narrations = workbook.addWorksheet("Bank Narrations", {
      views: [{ state: "frozen", ySplit: 4, showGridLines: false }],
    });
    narrations.columns = [
      { header: "Bank ref", key: "ref", width: 12 },
      { header: "Raw narration", key: "raw", width: 46 },
      { header: "Reference(s) read", key: "utrs", width: 22 },
      { header: "Counterparty", key: "counterparty", width: 14 },
      { header: "Read by", key: "source", width: 12 },
      { header: "Confidence", key: "confidence", width: 11 },
      { header: "Matched settlement", key: "matched", width: 16 },
    ];
    titleBand(narrations, "Bank Narrations", "What each credit line said, and what was read out of it", 7);
    narrations.getRow(4).values = narrations.columns.map((c) => c.header as string);
    styleHeaderRow(narrations.getRow(4));
    narrations.autoFilter = { from: { row: 4, column: 1 }, to: { row: 4, column: 7 } };

    for (const narration of report.narrations) {
      const row = narrations.addRow({
        ref: narration.ref,
        raw: narration.raw,
        utrs: narration.utrs.length ? narration.utrs.join(", ") : "none readable",
        counterparty: narration.counterparty ?? "unknown",
        source: narration.source === "llm" ? "AI" : "Rule (regex)",
        confidence: narration.confidence,
        matched: narration.matched_settlement_id ?? "—",
      });
      const confCell = row.getCell(narrations.getColumn("confidence").number);
      if (typeof confCell.value === "number") confCell.numFmt = PCT_FMT;
      if (narration.source === "llm") {
        const sourceCell = row.getCell(narrations.getColumn("source").number);
        sourceCell.font = { color: { argb: INFO }, italic: true };
      }
      row.eachCell((cell) => (cell.border = { bottom: { style: "hair", color: { argb: LINE } } }));
    }
  }

  const buffer = await workbook.xlsx.writeBuffer();
  return new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoking on the next tick, rather than immediately, avoids browsers that haven't
  // started the download yet from losing the blob out from under it.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
