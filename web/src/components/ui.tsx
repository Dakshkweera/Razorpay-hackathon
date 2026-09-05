import type { ReactNode } from "react";

export function Panel({
  title,
  hint,
  right,
  children,
}: {
  title: string;
  hint?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-md border border-line bg-surface">
      <header className="flex items-baseline justify-between gap-4 border-b border-line px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <h2 className="text-[13px] font-semibold tracking-tight">{title}</h2>
          {hint && <p className="text-[11px] text-ink-faint">{hint}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  );
}

/** A headline figure. `tone` carries meaning, so it is never decorative. */
export function Stat({
  label,
  value,
  sub,
  tone = "plain",
  emphasis = false,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "plain" | "ok" | "warn" | "bad";
  emphasis?: boolean;
}) {
  const toneClass = {
    plain: "text-ink",
    ok: "text-ok",
    warn: "text-warn",
    bad: "text-bad",
  }[tone];
  return (
    <div className="px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-ink-faint">{label}</div>
      <div className={`num mt-1 ${emphasis ? "text-2xl" : "text-lg"} font-semibold ${toneClass}`}>
        {value}
      </div>
      {sub && <div className="num mt-0.5 text-[11px] text-ink-faint">{sub}</div>}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "info";
  title?: string;
}) {
  const toneClass = {
    neutral: "bg-ground text-ink-soft border-line-strong",
    ok: "bg-ok-soft text-ok border-transparent",
    warn: "bg-warn-soft text-warn border-transparent",
    bad: "bg-bad-soft text-bad border-transparent",
    info: "bg-info-soft text-info border-transparent",
  }[tone];
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${toneClass}`}
    >
      {children}
    </span>
  );
}

export function Table({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[12px]">
        <thead className="text-[11px] uppercase tracking-wide text-ink-faint">{head}</thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Th({
  children,
  align = "left",
}: {
  children?: ReactNode;
  align?: "left" | "right";
}) {
  return (
    <th
      className={`border-b border-line px-3 py-2 font-medium ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  align = "left",
  mono = false,
  muted = false,
  className = "",
}: {
  children?: ReactNode;
  align?: "left" | "right";
  mono?: boolean;
  muted?: boolean;
  className?: string;
}) {
  return (
    <td
      className={`border-b border-line px-3 py-1.5 ${align === "right" ? "text-right" : ""} ${
        mono ? "num" : ""
      } ${muted ? "text-ink-faint" : ""} ${className}`}
    >
      {children}
    </td>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-6 text-center text-[12px] text-ink-faint">{children}</p>;
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="border-t border-line px-4 py-2.5 text-[11px] leading-relaxed text-ink-faint">
      {children}
    </p>
  );
}
