import { useCallback, useEffect, useMemo, useState } from "react";
import type { Report } from "./types/report";
import { api } from "./lib/api";
import { BatchDetail } from "./components/BatchDetail";
import { BatchTable } from "./components/BatchTable";
import { InputBrowser } from "./components/InputBrowser";
import { EvalPanel } from "./components/EvalPanel";
import { ExceptionsPanel } from "./components/ExceptionsPanel";
import { NarrationsPanel } from "./components/NarrationsPanel";
import { ScoreboardPanel } from "./components/ScoreboardPanel";
import { Empty, Panel } from "./components/ui";
import { shortHash } from "./lib/format";

type Tab = "scoreboard" | "batches" | "exceptions" | "narrations" | "evaluation" | "inputs";

const TABS: { key: Tab; label: string }[] = [
  { key: "scoreboard", label: "Scoreboard" },
  { key: "batches", label: "Batches" },
  { key: "exceptions", label: "Exceptions" },
  { key: "narrations", label: "Narrations" },
  { key: "evaluation", label: "Evaluation" },
  { key: "inputs", label: "Source files" },
];

export default function App() {
  const [report, setReport] = useState<Report | null>(null);
  const [tab, setTab] = useState<Tab>("scoreboard");
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A missing report is the expected state before the first run, not an error.
  useEffect(() => {
    api
      .report()
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.run());
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  const selectedBatch = useMemo(
    () => report?.batches.find((batch) => batch.settlement_id === selected) ?? null,
    [report, selected],
  );

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-3">
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight">Settlement Explainer</h1>
            <p className="text-[11px] text-ink-faint">
              Gateway settlement → bank credit → order records. Every rupee accounted for, or
              honestly flagged.
            </p>
          </div>

          <div className="ml-auto flex items-center gap-4">
            {report && (
              <dl className="hidden items-center gap-4 text-[11px] text-ink-faint sm:flex">
                <div>
                  <dt className="inline">seed </dt>
                  <dd className="num inline text-ink-soft">{report.meta.seed}</dd>
                </div>
                <div>
                  <dt className="inline">hash </dt>
                  <dd
                    className="num inline text-ink-soft"
                    title={report.meta.deterministic_hash}
                  >
                    {shortHash(report.meta.deterministic_hash)}
                  </dd>
                </div>
              </dl>
            )}
            <button
              onClick={run}
              disabled={busy}
              className="rounded bg-ink px-3 py-1.5 text-[12px] font-medium text-ground disabled:opacity-50"
            >
              {busy ? "Reconciling…" : "Run reconciliation"}
            </button>
          </div>

          <nav className="flex w-full gap-1 border-t border-line pt-2">
            {TABS.map((entry) => (
              <button
                key={entry.key}
                onClick={() => setTab(entry.key)}
                className={`rounded px-2.5 py-1 text-[12px] ${
                  tab === entry.key ? "bg-ground font-medium text-ink" : "text-ink-soft hover:bg-ground"
                }`}
              >
                {entry.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-4">
        {error && (
          <div className="mb-3 rounded border border-bad bg-bad-soft px-4 py-2 text-[12px] text-bad">
            {error}
          </div>
        )}

        {!report ? (
          <Panel title="No run yet">
            <Empty>
              Nothing has been reconciled. Press <strong>Run reconciliation</strong> to process
              the dataset.
            </Empty>
          </Panel>
        ) : tab === "scoreboard" ? (
          <ScoreboardPanel report={report} />
        ) : tab === "batches" ? (
          <BatchTable report={report} onSelect={setSelected} />
        ) : tab === "exceptions" ? (
          <ExceptionsPanel report={report} />
        ) : tab === "narrations" ? (
          <NarrationsPanel report={report} />
        ) : tab === "evaluation" ? (
          <EvalPanel report={report} />
        ) : (
          <InputBrowser />
        )}
      </main>

      {selectedBatch && (
        <BatchDetail batch={selectedBatch} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
