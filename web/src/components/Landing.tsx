import { ThemeToggle } from "./ThemeToggle";

export function Landing({
  onSignIn,
  onRegister,
}: {
  onSignIn: () => void;
  onRegister: () => void;
}) {
  return (
    <div className="min-h-screen screen-enter">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-[1200px] items-center justify-between px-5 py-4">
          <div className="text-[15px] font-semibold tracking-tight">Settlement Explainer</div>
          <div className="flex items-center gap-3">
            <ThemeToggle />
            <button
              onClick={onSignIn}
              className="text-[12px] font-medium text-ink-soft hover:text-ink"
            >
              Sign in
            </button>
            <button
              onClick={onRegister}
              className="rounded bg-ink px-3 py-1.5 text-[12px] font-medium text-ground"
            >
              Get started
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1200px] px-5">
        <section className="grid gap-10 py-16 sm:grid-cols-2 sm:items-center sm:py-24">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-wide text-info">
              AI Finance Controller
            </p>
            <h1 className="mt-3 text-[32px] font-semibold leading-tight tracking-tight text-balance sm:text-[40px]">
              Every rupee Razorpay ever settled, reconciled — or honestly explained.
            </h1>
            <p className="mt-4 max-w-[46ch] text-[14px] leading-relaxed text-ink-soft">
              Settlement Explainer lines up your Razorpay settlement report, your bank
              credits, and your own order records — then shows exactly where every gap
              came from, in rupees, not guesses.
            </p>
            <div className="mt-7 flex items-center gap-3">
              <button
                onClick={onRegister}
                className="rounded bg-ink px-4 py-2 text-[13px] font-medium text-ground"
              >
                Get started
              </button>
              <button
                onClick={onSignIn}
                className="rounded border border-line-strong px-4 py-2 text-[13px] font-medium text-ink-soft hover:bg-surface"
              >
                Sign in
              </button>
            </div>
          </div>
          <FlowDiagram />
        </section>

        <section className="grid gap-6 border-t border-line py-14 sm:grid-cols-3">
          <Feature
            eyebrow="01"
            title="Deterministic first"
            body="Four matching rules run before any model does — an exact UTR match is proof, not a prediction."
          />
          <Feature
            eyebrow="02"
            title="AI for the unreadable, not the money"
            body="Narration reading and residue classification lean on a model. Every rupee still moves through rules that can't hallucinate."
          />
          <Feature
            eyebrow="03"
            title="Provably accurate"
            body="Every run is scored, reproducible byte-for-byte, and shows its work — no exception ships without saying what it tried."
          />
        </section>
      </main>

      <footer className="border-t border-line py-6 text-center text-[11px] text-ink-faint">
        Built for Razorpay Buildathon 2026 — Track 04, AI Finance Controller.
      </footer>
    </div>
  );
}

function Feature({ eyebrow, title, body }: { eyebrow: string; title: string; body: string }) {
  return (
    <div>
      <div className="num text-[11px] text-ink-faint">{eyebrow}</div>
      <h3 className="mt-1.5 text-[14px] font-semibold tracking-tight">{title}</h3>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-soft">{body}</p>
    </div>
  );
}

function FlowDiagram() {
  const steps = ["Settlement report", "Bank statement", "Order records"];
  return (
    <div className="rounded-lg border border-line bg-surface p-6">
      <div className="grid gap-3">
        {steps.map((step) => (
          <div
            key={step}
            className="rounded border border-line-strong bg-ground px-3 py-2 text-[12px] font-medium text-ink-soft"
          >
            {step}
          </div>
        ))}
      </div>
      <div className="my-3 flex justify-center text-ink-faint">↓</div>
      <div className="rounded border border-ok bg-ok-soft px-3 py-2.5 text-center text-[12px] font-semibold text-ok">
        Reconciled, or honestly flagged
      </div>
    </div>
  );
}
