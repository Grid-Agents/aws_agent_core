import type { ConnType, Phase, Verdict } from "../types";
import type { RunStatus } from "../store";
import { STALL_MS } from "../store";

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

/* ---- agent run phase --------------------------------------------------- */

export type PhaseTone = "run" | "warn" | "ok" | "fail" | "idle";

export interface PhaseMeta {
  label: string;
  tone: PhaseTone;
  cls: string; // phase-{tone}
  spin: boolean;
}

/**
 * Resolve the live phase of a run into display metadata. A running stream that
 * has gone silent past STALL_MS is surfaced as "stalled" regardless of the
 * stored phase, so a wedged backend reads as trouble rather than progress.
 */
export function phaseMeta(phase: Phase, silentMs: number): PhaseMeta {
  const stalled = (phase === "waiting" || phase === "active") && silentMs > STALL_MS;
  if (stalled)
    return { label: "No signal — may be stalled", tone: "warn", cls: "phase-warn", spin: false };
  switch (phase) {
    case "connecting":
      return { label: "Connecting to backend", tone: "run", cls: "phase-run", spin: true };
    case "waiting":
      return { label: "Waiting on agent (warm-up)", tone: "run", cls: "phase-run", spin: true };
    case "active":
      return { label: "Agent working", tone: "run", cls: "phase-run", spin: true };
    case "done":
      return { label: "Completed", tone: "ok", cls: "phase-ok", spin: false };
    case "error":
      return { label: "Failed", tone: "fail", cls: "phase-fail", spin: false };
    default:
      return { label: "Idle", tone: "idle", cls: "phase-idle", spin: false };
  }
}

export function PhaseChip({ phase, silentMs }: { phase: Phase; silentMs: number }) {
  const m = phaseMeta(phase, silentMs);
  return (
    <span className={`phasechip ${m.cls}`}>
      {m.spin && <span className="spinner" />}
      {m.label}
    </span>
  );
}

/** Format an elapsed duration in ms as a compact mm:ss / s string. */
export function elapsed(ms: number): string {
  if (ms < 0) ms = 0;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}
