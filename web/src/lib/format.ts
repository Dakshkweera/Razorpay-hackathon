/** Paise are integers on the wire, exactly as the engine computes them. */
export type Paise = number;

/** Render paise with Indian digit grouping. Mirrors `recon.money.format_inr`. */
export function inr(amount: Paise, options: { sign?: boolean } = {}): string {
  const negative = amount < 0;
  const rupees = Math.trunc(Math.abs(amount) / 100);
  const paise = Math.abs(amount) % 100;

  let digits = String(rupees);
  if (digits.length > 3) {
    const tail = digits.slice(-3);
    let head = digits.slice(0, -3);
    const groups: string[] = [];
    while (head.length > 2) {
      groups.unshift(head.slice(-2));
      head = head.slice(0, -2);
    }
    if (head) groups.unshift(head);
    digits = [...groups, tail].join(",");
  }

  const body = `₹${digits}.${String(paise).padStart(2, "0")}`;
  if (negative) return `−${body}`;
  return options.sign ? `+${body}` : body;
}

export function pct(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function count(value: number): string {
  return value.toLocaleString("en-IN");
}

/** ISO date or datetime to a compact, unambiguous display form. */
export function day(value: string): string {
  return value.slice(0, 10);
}

export function stamp(value: string | null): string {
  if (!value) return "—";
  return value.replace("T", " ").replace(/(\+00:00|Z)$/, "").slice(0, 16);
}

export function shortHash(value: string): string {
  return value ? `${value.slice(0, 12)}…` : "—";
}
