import type { ConnType, Verdict } from "../types";
import type { RunStatus } from "../store";

const VERDICT_META: Record<Verdict, { cls: string; glyph: string; label: string }> = {
  PASS: { cls: "pass", glyph: "✓", label: "Pass" },
  NEEDS_REVISION: { cls: "revise", glyph: "!", label: "Needs revision" },
  FAIL: { cls: "fail", glyph: "✕", label: "Fail" },
};

export function VerdictBadge({
  status,
  verdict,
}: {
  status: RunStatus;
  verdict: Verdict | null;
}) {
  if (status === "running")
    return (
      <span className="verdict running">
        <span className="spinner" /> Reviewing
      </span>
    );
  if (status === "error")
    return <span className="verdict fail">Error</span>;
  if (status === "done" && verdict) {
    const m = VERDICT_META[verdict];
    return (
      <span className={`verdict ${m.cls}`}>
        <span className="glyph">{m.glyph}</span> {m.label}
      </span>
    );
  }
  if (status === "done") return <span className="verdict idle">Reviewed</span>;
  return <span className="verdict idle">Not reviewed</span>;
}

export function TypeChip({ type }: { type: ConnType }) {
  return <span className={`chip ${type}`}>{type}</span>;
}

export function verdictClass(v: Verdict | null): string {
  if (v === "PASS") return "pass";
  if (v === "NEEDS_REVISION") return "revise";
  if (v === "FAIL") return "fail";
  return "";
}
