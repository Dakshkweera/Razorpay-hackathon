import type { Report } from "../types/report";
import type { AuthedUser } from "./Auth";
import { count, stamp } from "../lib/format";
import { ThemeToggle } from "./ThemeToggle";

export function Dashboard({
  user,
  lastReport,
  onStart,
  onSignOut,
}: {
  user: AuthedUser;
  lastReport: Report | null;
  onStart: () => void;
  onSignOut: () => void;
}) {
  return (
    <div className="min-h-screen screen-enter">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[900px] items-center justify-between px-5 py-4">
          <div className="text-[15px] font-semibold tracking-tight">Settlement Explainer</div>
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
        <p className="text-[11px] font-medium uppercase tracking-wide text-info">Dashboard</p>
        <h1 className="mt-2 text-[24px] font-semibold tracking-tight">
          Welcome back, {user.name.split(" ")[0]}
        </h1>
        <p className="mt-2 max-w-[60ch] text-[13px] leading-relaxed text-ink-soft">
          {lastReport
            ? "Your last reconciliation is still available below, or start a fresh one with new files."
            : "Choose a module to get started — a merchant workspace usually starts here."}
        </p>

        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          <button
            onClick={onStart}
            className="group rounded-md border border-line-strong bg-surface p-4 text-left transition-colors hover:border-info"
          >
            <div className="inline-flex rounded bg-info-soft px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-info">
              Track 04
            </div>
            <h3 className="mt-3 text-[13px] font-semibold text-ink">Settlement Reconciliation</h3>
            <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">
              Match settlement reports against bank credits and order records, and explain
              every gap.
            </p>
            <span className="mt-3 inline-block text-[12px] font-medium text-info group-hover:underline">
              {lastReport ? "Run again →" : "Start →"}
            </span>
          </button>

          <ComingSoon
            title="Payout Insights"
            body="Forecast upcoming payouts against pending order volume."
          />
          <ComingSoon
            title="Dispute Copilot"
            body="Draft chargeback responses from linked order evidence."
          />
        </div>

        {lastReport && (
          <div className="mt-8 rounded-md border border-line bg-surface px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-ink-faint">Last run</div>
            <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-ink-soft">
              <span>
                <span className="num font-medium text-ink">
                  {count(lastReport.scoreboard.settlement_batches)}
                </span>{" "}
                settlement batches
              </span>
              <span>
                <span className="num font-medium text-ink">
                  {count(lastReport.scoreboard.records_processed)}
                </span>{" "}
                records processed
              </span>
              <span className="num">{stamp(lastReport.meta.run_at)}</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function ComingSoon({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong p-4 text-left opacity-60">
      <div className="inline-flex rounded bg-ground px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
        Coming soon
      </div>
      <h3 className="mt-3 text-[13px] font-semibold text-ink">{title}</h3>
      <p className="mt-1.5 text-[12px] leading-relaxed text-ink-soft">{body}</p>
    </div>
  );
}
