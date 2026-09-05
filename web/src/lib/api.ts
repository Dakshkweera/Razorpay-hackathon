import type { Report } from "../types/report";

export interface InputPayload {
  file: string;
  normalise: {
    file: string;
    rows_read: number;
    rows_rejected: number;
    rejections: string[];
    columns_mapped: { source: string; canonical: string; method: string; confidence: number }[];
  };
  rows: Record<string, string | number | null>[];
}

async function json<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail ?? `request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  /** The last report on disk. 404 until a run has happened. */
  report: () => json<Report>("/api/report"),
  /** Reconcile now and persist the result. */
  run: () => json<Report>("/api/run", { method: "POST" }),
  inputs: (name: "settlements" | "orders" | "bank") => json<InputPayload>(`/api/inputs/${name}`),
};
