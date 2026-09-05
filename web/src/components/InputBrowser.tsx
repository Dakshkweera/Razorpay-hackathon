import { useEffect, useState } from "react";
import { api, type InputPayload } from "../lib/api";
import { Badge, Empty, Note, Panel, Table, Td, Th } from "./ui";
import { inr } from "../lib/format";

type FileName = "settlements" | "orders" | "bank";

const FILES: { key: FileName; label: string; note: string }[] = [
  {
    key: "settlements",
    label: "settlements.csv",
    note: "Razorpay's own report. Amounts are signed: payments positive, refunds and adjustments negative.",
  },
  {
    key: "orders",
    label: "orders.csv",
    note: "The merchant's records. payment_ref is deliberately unreliable — sometimes a payment id, sometimes a bare UTR, sometimes empty.",
  },
  {
    key: "bank",
    label: "bank.csv",
    note: "The statement. Narration format varies per row, which is where the reading gets hard.",
  },
];

const MONEY_COLUMNS = new Set([
  "amount",
  "fee",
  "tax",
  "order_amount",
  "refunded_amount",
  "debit",
  "credit",
  "balance",
]);

/** Reading the source files next to the conclusions is what makes the run auditable. */
export function InputBrowser() {
  const [active, setActive] = useState<FileName>("settlements");
  const [payload, setPayload] = useState<InputPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setPayload(null);
    setError(null);
    api
      .inputs(active)
      .then((data) => live && setPayload(data))
      .catch((cause: Error) => live && setError(cause.message));
    return () => {
      live = false;
    };
  }, [active]);

  const meta = FILES.find((file) => file.key === active)!;
  const columns = payload?.rows.length ? Object.keys(payload.rows[0]) : [];

  return (
    <Panel
      title="Source files"
      hint={payload ? `${payload.normalise.rows_read} rows read` : undefined}
      right={
        <div className="flex gap-1">
          {FILES.map((file) => (
            <button
              key={file.key}
              onClick={() => setActive(file.key)}
              className={`rounded px-2 py-1 text-[11px] ${
                active === file.key
                  ? "bg-ink text-ground"
                  : "text-ink-soft hover:bg-ground"
              }`}
            >
              {file.label}
            </button>
          ))}
        </div>
      }
    >
      {error && <Empty>{error}</Empty>}
      {!error && !payload && <Empty>Loading {meta.label}…</Empty>}
      {payload && (
        <>
          {payload.normalise.rows_rejected > 0 && (
            <div className="border-b border-line px-4 py-2">
              <Badge tone="bad">{payload.normalise.rows_rejected} rows rejected</Badge>
              <ul className="num mt-1.5 space-y-0.5 text-[11px] text-ink-soft">
                {payload.normalise.rejections.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="max-h-[28rem] overflow-y-auto">
            <Table
              head={
                <tr className="sticky top-0 bg-surface">
                  {columns.map((column) => (
                    <Th key={column} align={MONEY_COLUMNS.has(column) ? "right" : "left"}>
                      {column}
                    </Th>
                  ))}
                </tr>
              }
            >
              {payload.rows.map((row, index) => (
                <tr key={index} className="hover:bg-ground">
                  {columns.map((column) => {
                    const value = row[column];
                    const money = MONEY_COLUMNS.has(column);
                    return (
                      <Td
                        key={column}
                        align={money ? "right" : "left"}
                        mono
                        muted={value === "" || value === 0 || value === null}
                      >
                        {money && typeof value === "number"
                          ? value === 0
                            ? "—"
                            : inr(value)
                          : String(value ?? "") || "—"}
                      </Td>
                    );
                  })}
                </tr>
              ))}
            </Table>
          </div>
          <Note>{meta.note}</Note>
        </>
      )}
    </Panel>
  );
}
