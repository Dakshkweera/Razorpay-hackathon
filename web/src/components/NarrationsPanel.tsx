import type { NarrationRead, Report } from "../types/report";
import { Badge, Empty, Note, Panel, Table, Td, Th } from "./ui";

/**
 * Raw bank narration next to what was extracted from it, and by what. This is the
 * direct answer to "why is there an LLM here": the regex is the deterministic floor,
 * shown alongside whatever a model added on top of it - and, just as often, alongside
 * a narration where the honest answer was to add nothing at all.
 */
function SourceBadge({ narration }: { narration: NarrationRead }) {
  if (narration.source === "llm") {
    return <Badge tone="info">llm</Badge>;
  }
  return <Badge tone="neutral">regex</Badge>;
}

export function NarrationsPanel({ report }: { report: Report }) {
  if (report.narrations.length === 0) {
    return (
      <Panel title="Narrations">
        <Empty>No credit narrations yet. Run the reconciliation.</Empty>
      </Panel>
    );
  }

  const llmAssisted = report.narrations.filter((n) => n.source === "llm").length;

  return (
    <Panel
      title="Narrations"
      hint={`${report.narrations.length} bank credits · ${llmAssisted} read with model assistance`}
    >
      <Table
        head={
          <tr>
            <Th>Ref</Th>
            <Th>Raw narration</Th>
            <Th>Reference(s)</Th>
            <Th>Counterparty</Th>
            <Th>Kind</Th>
            <Th align="right">Confidence</Th>
            <Th>Read by</Th>
            <Th>Claimed by</Th>
          </tr>
        }
      >
        {report.narrations.map((narration) => (
          <tr key={narration.ref} className="hover:bg-ground">
            <Td mono>{narration.ref}</Td>
            <Td mono muted className="max-w-xs truncate">
              <span title={narration.raw}>{narration.raw}</span>
            </Td>
            <Td mono>
              {narration.utrs.length ? (
                narration.utrs.join(", ")
              ) : (
                <span className="text-ink-faint">none readable</span>
              )}
            </Td>
            <Td mono muted={!narration.counterparty}>{narration.counterparty ?? "unknown"}</Td>
            <Td mono muted>{narration.kind}</Td>
            <Td align="right" mono>
              {narration.confidence.toFixed(2)}
            </Td>
            <Td>
              <SourceBadge narration={narration} />
            </Td>
            <Td mono muted={!narration.matched_settlement_id}>
              {narration.matched_settlement_id ?? "—"}
            </Td>
          </tr>
        ))}
      </Table>
      <Note>
        A reference read by the model rather than the regex is what makes a match
        <strong> inference</strong> instead of <strong>deterministic</strong> — see the batch
        table. A narration missing a reference here was left that way on purpose: a model
        that guessed at a truncated or nonexistent digit run would be inventing evidence,
        not reading it.
      </Note>
    </Panel>
  );
}
