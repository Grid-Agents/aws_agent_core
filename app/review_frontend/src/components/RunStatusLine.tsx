import { useStore } from "../store";
import type { Phase } from "../types";
import { elapsed, phaseMeta } from "./bits";

/**
 * Compact live-status strip shown inline on a section card or co-pilot panel
 * while a run is in flight. Surfaces phase + elapsed + a stall warning so a
 * run that is merely warming up never reads as frozen — and one that has
 * genuinely gone silent is called out.
 */
export function RunStatusLine({
  phase,
  startedAt,
  lastEventAt,
}: {
  phase: Phase;
  startedAt: number;
  lastEventAt: number;
}) {
  const { tick } = useStore();
  if (phase === "idle" || phase === "done") return null;

  const now = Math.max(tick, Date.now());
  const silentMs = now - lastEventAt;
  const m = phaseMeta(phase, silentMs);

  return (
    <div className={`runstatus ${m.cls}`}>
      {m.spin ? <span className="spinner" /> : <span className="rs-dot" />}
      <span className="rs-label">{m.label}</span>
      <span className="rs-sep">·</span>
      <span className="rs-elapsed">{elapsed(now - startedAt)} elapsed</span>
      {(phase === "waiting" || phase === "active") && silentMs > 6000 && (
        <span className="rs-silent">last signal {elapsed(silentMs)} ago</span>
      )}
    </div>
  );
}
