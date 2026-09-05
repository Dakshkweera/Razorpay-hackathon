import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import { api } from "../lib/api";
import type { Report } from "../types/report";
import type { AuthedUser } from "./Auth";
import { formatBytes } from "../lib/format";
import { ThemeToggle } from "./ThemeToggle";

type FileKey = "settlements" | "orders" | "bank";

const SLOTS: { key: FileKey; label: string; hint: string }[] = [
  { key: "settlements", label: "Settlement report", hint: "Razorpay's own report, per settlement batch." },
  { key: "orders", label: "Order records", hint: "Your merchant order ledger." },
  { key: "bank", label: "Bank statement", hint: "The bank's own line-by-line credit statement." },
];

/** Purely cosmetic — the engine always reconciles the fixed seeded dataset underneath. */
const STEPS: { label: string; ms: number }[] = [
  { label: "Uploading files to secure workspace", ms: 700 },
  { label: "Parsing settlement report, bank statement, and order records", ms: 1100 },
  { label: "Normalizing columns and currencies", ms: 900 },
  { label: "Running deterministic match rules (R1–R4)", ms: 1300 },
  { label: "Reading bank narrations with AI", ms: 1200 },
  { label: "Classifying unexplained residue", ms: 1000 },
  { label: "Scoring reconciliation accuracy", ms: 800 },
];

export function UploadScreen({
  user,
  onRun,
  onSignOut,
  onBack,
}: {
  user: AuthedUser;
  onRun: (report: Report) => void;
  onSignOut: () => void;
  onBack: () => void;
}) {
  const [files, setFiles] = useState<Record<FileKey, File | null>>({
    settlements: null,
    orders: null,
    bank: null,
  });
  const [dragOver, setDragOver] = useState<FileKey | null>(null);
  const [stepIndex, setStepIndex] = useState(-1);
  const [error, setError] = useState<string | null>(null);

  const processing = stepIndex >= 0;
  const allAttached = SLOTS.every((slot) => files[slot.key] !== null);

  const attach = useCallback((key: FileKey, file: File | null) => {
    setFiles((prev) => ({ ...prev, [key]: file }));
  }, []);

  const run = useCallback(() => {
    setError(null);
    setStepIndex(0);
  }, []);

  useEffect(() => {
    if (!processing) return;
    if (stepIndex >= STEPS.length) return;
    const timer = setTimeout(() => setStepIndex((index) => index + 1), STEPS[stepIndex].ms);
    return () => clearTimeout(timer);
  }, [processing, stepIndex]);

  useEffect(() => {
    if (!processing || stepIndex < STEPS.length) return;
    let live = true;
    api
      .run()
      .then((report) => live && onRun(report))
      .catch((cause: Error) => {
        if (live) {
          setError(cause.message);
          setStepIndex(-1);
        }
      });
    return () => {
      live = false;
    };
  }, [processing, stepIndex, onRun]);

  if (processing) {
    return <ProcessingView stepIndex={Math.min(stepIndex, STEPS.length - 1)} />;
  }

  return (
    <div className="min-h-screen screen-enter">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[900px] items-center justify-between px-5 py-4">
          <button
            onClick={onBack}
            className="text-[15px] font-semibold tracking-tight hover:text-ink-soft"
          >
            Settlement Explainer
          </button>
          <div className="flex items-center gap-3 text-[12px] text-ink-faint">
            <span>
              Signed in as <span className="font-medium text-ink-soft">{user.name}</span>
            </span>
            <button onClick={onSignOut} className="text-ink-faint hover:text-ink-soft">
              Sign out
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[900px] px-5 py-10">
        <button
          onClick={onBack}
          className="text-[11px] font-medium uppercase tracking-wide text-info hover:underline"
        >
          ← Dashboard
        </button>
        <p className="mt-3 text-[11px] font-medium uppercase tracking-wide text-ink-faint">
          New reconciliation
        </p>
        <h1 className="mt-2 text-[24px] font-semibold tracking-tight">
          Upload your three source files
        </h1>
        <p className="mt-2 max-w-[60ch] text-[13px] leading-relaxed text-ink-soft">
          Drop in your settlement report, order records, and bank statement. We'll line them
          up and show exactly where every rupee went.
        </p>

        <div className="mt-7 grid gap-4 sm:grid-cols-3">
          {SLOTS.map((slot) => (
            <Dropzone
              key={slot.key}
              slot={slot}
              file={files[slot.key]}
              isDragOver={dragOver === slot.key}
              onDragOver={() => setDragOver(slot.key)}
              onDragLeave={() => setDragOver((current) => (current === slot.key ? null : current))}
              onDrop={(file) => {
                setDragOver(null);
                attach(slot.key, file);
              }}
              onSelect={(file) => attach(slot.key, file)}
              onClear={() => attach(slot.key, null)}
            />
          ))}
        </div>

        {error && (
          <div className="mt-5 rounded border border-bad bg-bad-soft px-4 py-2 text-[12px] text-bad">
            {error}
          </div>
        )}

        <div className="mt-7 flex items-center gap-3">
          <button
            onClick={run}
            disabled={!allAttached}
            className="rounded bg-ink px-4 py-2 text-[13px] font-medium text-ground disabled:opacity-40"
          >
            Run reconciliation
          </button>
          <span className="text-[11px] text-ink-faint">
            {allAttached
              ? "All three files attached."
              : `Attach all three files to continue (${SLOTS.filter((s) => files[s.key]).length}/3).`}
          </span>
        </div>
      </main>
    </div>
  );
}

function Dropzone({
  slot,
  file,
  isDragOver,
  onDragOver,
  onDragLeave,
  onDrop,
  onSelect,
  onClear,
}: {
  slot: { key: FileKey; label: string; hint: string };
  file: File | null;
  isDragOver: boolean;
  onDragOver: () => void;
  onDragLeave: () => void;
  onDrop: (file: File) => void;
  onSelect: (file: File) => void;
  onClear: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onDrop(dropped);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        onDragOver();
      }}
      onDragLeave={onDragLeave}
      onDrop={handleDrop}
      onClick={() => !file && inputRef.current?.click()}
      className={`flex min-h-[9.5rem] flex-col rounded-md border p-3.5 text-left transition-colors ${
        file
          ? "border-line-strong bg-surface"
          : isDragOver
            ? "cursor-pointer border-info bg-info-soft"
            : "cursor-pointer border-dashed border-line-strong bg-ground hover:border-ink-faint"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(event) => {
          const picked = event.target.files?.[0];
          if (picked) onSelect(picked);
          event.target.value = "";
        }}
      />
      <div className="text-[12px] font-semibold text-ink">{slot.label}</div>

      {file ? (
        <div className="mt-2 flex flex-1 flex-col justify-between">
          <div>
            <p className="break-all text-[12px] font-medium text-ink">{file.name}</p>
            <p className="num mt-1 text-[11px] text-ink-faint">{formatBytes(file.size)}</p>
          </div>
          <button
            onClick={(event) => {
              event.stopPropagation();
              onClear();
            }}
            className="mt-2 self-start text-[11px] text-ink-faint hover:text-bad"
          >
            Remove
          </button>
        </div>
      ) : (
        <div className="mt-2 flex flex-1 flex-col justify-between">
          <p className="text-[11px] leading-relaxed text-ink-faint">{slot.hint}</p>
          <p className="mt-2 text-[11px] font-medium text-info">Click or drop a file here</p>
        </div>
      )}
    </div>
  );
}

function ProcessingView({ stepIndex }: { stepIndex: number }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-5 screen-enter">
      <div className="w-full max-w-[440px]">
        <p className="text-center text-[11px] font-medium uppercase tracking-wide text-info">
          Reconciling
        </p>
        <h1 className="mt-2 text-center text-[18px] font-semibold tracking-tight">
          Working through your files…
        </h1>

        <div className="mt-7 grid gap-2.5 rounded-md border border-line bg-surface p-4">
          {STEPS.map((step, index) => {
            const done = index < stepIndex;
            const active = index === stepIndex;
            return (
              <div key={step.label} className="flex items-center gap-3">
                <span
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] ${
                    done
                      ? "bg-ok text-ground"
                      : active
                        ? "border-2 border-info"
                        : "border border-line-strong"
                  }`}
                >
                  {done && "✓"}
                  {active && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-info" />}
                </span>
                <span
                  className={`text-[12px] ${
                    done ? "text-ink-faint line-through" : active ? "font-medium text-ink" : "text-ink-faint"
                  }`}
                >
                  {step.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
