import { useMemo, useState } from "react";
import type { Report } from "./types/report";
import { Landing } from "./components/Landing";
import { Auth, type AuthedUser } from "./components/Auth";
import { Dashboard } from "./components/Dashboard";
import { UploadScreen } from "./components/UploadScreen";
import { BatchDetail } from "./components/BatchDetail";
import { BatchTable } from "./components/BatchTable";
import { InputBrowser } from "./components/InputBrowser";
import { EvalPanel } from "./components/EvalPanel";
import { ExceptionsPanel } from "./components/ExceptionsPanel";
import { NarrationsPanel } from "./components/NarrationsPanel";
import { ScoreboardPanel } from "./components/ScoreboardPanel";
import { DatasetSummary } from "./components/DatasetSummary";
import { ThemeToggle } from "./components/ThemeToggle";
import { shortHash } from "./lib/format";

type Tab = "scoreboard" | "batches" | "exceptions" | "narrations" | "evaluation" | "inputs";
type Stage = "landing" | "auth" | "dashboard" | "upload" | "workspace";

const TABS: { key: Tab; label: string }[] = [
  { key: "scoreboard", label: "Scoreboard" },
  { key: "batches", label: "Batches" },
  { key: "exceptions", label: "Exceptions" },
  { key: "narrations", label: "Narrations" },
  { key: "evaluation", label: "Evaluation" },
  { key: "inputs", label: "Source files" },
];

export default function App() {
  const [stage, setStage] = useState<Stage>("landing");
  const [authMode, setAuthMode] = useState<"signin" | "register">("signin");
  const [user, setUser] = useState<AuthedUser | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [tab, setTab] = useState<Tab>("scoreboard");
  const [selected, setSelected] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const selectedBatch = useMemo(
    () => report?.batches.find((batch) => batch.settlement_id === selected) ?? null,
    [report, selected],
  );

  const signOut = () => {
    setUser(null);
    setReport(null);
    setStage("landing");
  };

  const handleDownload = async () => {
    if (!report) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const { buildExcelReport, downloadBlob } = await import("./lib/excelReport");
      const blob = await buildExcelReport(report);
      // Timestamped so every click is a distinct file — a repeat download of the same
      // report never looks like a no-op just because the filename already exists.
      const takenAt = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      downloadBlob(
        blob,
        `settlement-report-seed${report.meta.seed}-${report.meta.deterministic_hash.slice(0, 10)}-${takenAt}.xlsx`,
      );
    } catch {
      // The most common real-world cause: the page has been open since before the
      // last deploy, so this chunk's old filename no longer exists on the server.
      setDownloadError("Couldn't build the report — try refreshing the page.");
    } finally {
      setDownloading(false);
    }
  };

  if (stage === "landing") {
    return (
      <Landing
        onSignIn={() => {
          setAuthMode("signin");
          setStage("auth");
        }}
        onRegister={() => {
          setAuthMode("register");
          setStage("auth");
        }}
      />
    );
  }

  if (stage === "auth") {
    return (
      <Auth
        mode={authMode}
        onAuthenticated={(authedUser) => {
          setUser(authedUser);
          setStage("dashboard");
        }}
        onBack={() => setStage("landing")}
      />
    );
  }

  if (stage === "dashboard") {
    return (
      <Dashboard
        user={user!}
        lastReport={report}
        onStart={() => setStage("upload")}
        onSignOut={signOut}
      />
    );
  }

  if (stage === "upload" || !report) {
    return (
      <UploadScreen
        user={user!}
        onSignOut={signOut}
        onBack={() => setStage("dashboard")}
        onRun={(newReport) => {
          setReport(newReport);
          setTab("scoreboard");
          setStage("workspace");
        }}
      />
    );
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3">
          <div className="flex items-baseline gap-3">
            <button
              onClick={() => setStage("dashboard")}
              className="text-[15px] font-semibold tracking-tight hover:text-ink-soft"
            >
              Settlement Explainer
            </button>
            <span
              className="num hidden text-[11px] text-ink-faint sm:inline"
              title={report.meta.deterministic_hash}
            >
              seed {report.meta.seed} · {shortHash(report.meta.deterministic_hash)}
            </span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="rounded border border-line-strong px-3 py-1.5 text-[12px] font-medium text-ink-soft hover:bg-ground disabled:opacity-50"
            >
              {downloading ? "Preparing…" : "Download report"}
            </button>
            <button
              onClick={() => setStage("upload")}
              className="rounded bg-ink px-3 py-1.5 text-[12px] font-medium text-ground"
            >
              New reconciliation
            </button>
            <div className="ml-1 flex items-center gap-2.5 border-l border-line pl-3">
              <span className="text-[12px] text-ink-soft">{user?.name}</span>
              <button onClick={signOut} className="text-[12px] text-ink-faint hover:text-ink-soft">
                Sign out
              </button>
              <ThemeToggle />
            </div>
          </div>

          <nav className="flex w-full gap-1 border-t border-line pt-1">
            {TABS.map((entry) => (
              <button
                key={entry.key}
                onClick={() => setTab(entry.key)}
                className={`relative px-2.5 py-2 text-[12px] ${
                  tab === entry.key ? "font-medium text-ink" : "text-ink-soft hover:text-ink"
                }`}
              >
                {entry.label}
                {tab === entry.key && (
                  <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-ink" />
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-4">
        {downloadError && (
          <div className="mb-3 flex items-center justify-between gap-3 rounded border border-bad bg-bad-soft px-4 py-2 text-[12px] text-bad">
            <span>{downloadError}</span>
            <button onClick={() => setDownloadError(null)} className="font-medium hover:underline">
              Dismiss
            </button>
          </div>
        )}
        <div key={tab} className="screen-enter grid gap-3">
          {tab === "scoreboard" && <DatasetSummary report={report} />}

          {tab === "scoreboard" ? (
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
        </div>
      </main>

      {selectedBatch && (
        <BatchDetail batch={selectedBatch} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
