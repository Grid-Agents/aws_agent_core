import { useEffect, useMemo, useRef, useState } from "react";
import { useStore, type Activity } from "../store";
import type { LogLine, TraceEntry } from "../types";
import { PhaseChip, elapsed, verdictClass } from "./bits";

/**
 * Global, always-mounted operations console. Two jobs in one dock:
 *   • Activity / reasoning — what every agent is doing to which section, live
 *     (thinking, searching, citing), so operators can follow the work.
 *   • Backend log — the raw connection/heartbeat/event feed, so engineers can
 *     tell "working" from "warming up" from "crashed".
 * Mounted at app root: runs keep streaming here across in-app navigation.
 */
export function AgentConsole() {
  const { activities, tick } = useStore();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"thread" | "log">("thread");
  const [selected, setSelected] = useState<string | null>(null);

  const now = Math.max(tick, Date.now());
  const running = activities.filter((a) => a.status === "running");
  const stalled = running.filter(
    (a) => (a.phase === "waiting" || a.phase === "active") && now - a.lastEventAt > 18_000,
  );

  // Keep a sensible selection: prefer a running activity, else the newest.
  const active = useMemo(
    () => activities.find((a) => a.key === selected) ?? null,
    [activities, selected],
  );
  useEffect(() => {
    if (active) return;
    const next = running[0] ?? activities[0];
    if (next) setSelected(next.key);
  }, [active, running, activities]);

  // Auto-open the first time work starts, so warm-up dead time is visible.
  const everRan = useRef(false);
  useEffect(() => {
    if (running.length > 0 && !everRan.current) {
      everRan.current = true;
      setOpen(true);
    }
  }, [running.length]);

  const summary =
    running.length > 0
      ? `${running.length} running${stalled.length ? ` · ${stalled.length} stalled` : ""}`
      : activities.length > 0
        ? `${activities.length} run${activities.length > 1 ? "s" : ""}`
        : "idle";

  return (
    <aside className={`console ${open ? "open" : ""}`}>
      <button className="console-bar" onClick={() => setOpen((o) => !o)}>
        <span className={`console-led ${running.length ? (stalled.length ? "warn" : "live") : "off"}`} />
        <span className="console-title">Agent Console</span>
        <span className="console-summary">{summary}</span>
        <span className="console-spacer" />
        {running.length > 0 && <span className="console-mini">⌁ streaming</span>}
        <span className="console-caret">{open ? "▾" : "▴"}</span>
      </button>

      {open && (
        <div className="console-body">
          <div className="console-list">
            {activities.length === 0 && (
              <div className="console-empty">No agent runs yet. Trigger a section review or a co-pilot question.</div>
            )}
            {activities.map((a) => (
              <ActivityRow
                key={a.key}
                a={a}
                now={now}
                selected={a.key === selected}
                onClick={() => setSelected(a.key)}
              />
            ))}
          </div>

          <div className="console-detail">
            {!active ? (
              <div className="console-empty">Select a run to inspect its reasoning and backend log.</div>
            ) : (
              <>
                <div className="console-detail-head">
                  <div className="cdh-main">
                    <span className={`cdh-kind ${active.kind}`}>{active.kind === "review" ? "REVIEW" : "CO-PILOT"}</span>
                    <span className="cdh-title">{active.title}</span>
                  </div>
                  <div className="cdh-meta">
                    <PhaseChip phase={active.phase} silentMs={now - active.lastEventAt} />
                    <span className="cdh-elapsed">{elapsed(now - active.startedAt)}</span>
                  </div>
                </div>
                <div className="console-tabs">
                  <button className={view === "thread" ? "on" : ""} onClick={() => setView("thread")}>
                    Reasoning thread <span className="n">{active.traces.length}</span>
                  </button>
                  <button className={view === "log" ? "on" : ""} onClick={() => setView("log")}>
                    Backend log <span className="n">{active.log.length}</span>
                  </button>
                </div>
                {view === "thread" ? (
                  <ReasoningThread traces={active.traces} live={active.status === "running"} phase={active.phase} />
                ) : (
                  <BackendLog log={active.log} live={active.status === "running"} />
                )}
              </>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}

function ActivityRow({
  a,
  now,
  selected,
  onClick,
}: {
  a: Activity;
  now: number;
  selected: boolean;
  onClick: () => void;
}) {
  const silentMs = now - a.lastEventAt;
  return (
    <button className={`arow ${selected ? "sel" : ""}`} onClick={onClick}>
      <PhaseChip phase={a.phase} silentMs={silentMs} />
      <div className="arow-text">
        <div className="arow-title">{a.title}</div>
        <div className="arow-sub">
          <span className={`arow-tag ${a.kind}`}>{a.kind}</span>
          {a.subtitle} · {elapsed(now - a.startedAt)}
          {a.status === "done" && a.verdict && (
            <span className={`arow-verdict ${verdictClass(a.verdict)}`}>{a.verdict.replace("_", " ")}</span>
          )}
        </div>
      </div>
    </button>
  );
}

/* ---- reasoning thread -------------------------------------------------- */

const KIND_META: Record<string, { glyph: string; label: string; cls: string }> = {
  user: { glyph: "◉", label: "task", cls: "k-user" },
  agentcore: { glyph: "☁", label: "aws", cls: "k-aws" },
  agent: { glyph: "✦", label: "thinking", cls: "k-think" },
  subagent: { glyph: "✧", label: "subagent", cls: "k-think" },
  "tool-call": { glyph: "⚙", label: "tool", cls: "k-tool" },
  "subagent-call": { glyph: "⊕", label: "dispatch", cls: "k-tool" },
  retrieval: { glyph: "⌕", label: "search", cls: "k-search" },
  inspect: { glyph: "❏", label: "inspect", cls: "k-search" },
  citation: { glyph: "❝", label: "cite", cls: "k-cite" },
  error: { glyph: "⚠", label: "error", cls: "k-error" },
  result: { glyph: "✓", label: "done", cls: "k-done" },
};

function evidenceIds(t: TraceEntry): string[] {
  const ids = (t.metadata as { evidence_ids?: unknown })?.evidence_ids;
  return Array.isArray(ids) ? ids.map(String) : [];
}

function ReasoningThread({ traces, live, phase }: { traces: TraceEntry[]; live: boolean; phase: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (live && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [traces, live]);

  return (
    <div className="thread" ref={ref}>
      {traces.length === 0 && (
        <div className="thread-wait">
          <span className="spinner" />
          {phase === "connecting"
            ? "Opening connection to the backend…"
            : "Agent is warming up — no reasoning emitted yet. The backend log confirms it is alive."}
        </div>
      )}
      {traces.map((t, i) => {
        const m = KIND_META[t.kind] ?? { glyph: "•", label: t.kind, cls: "" };
        const ids = evidenceIds(t);
        return (
          <div className={`tstep ${m.cls}`} key={t.id ?? i}>
            <div className="tstep-rail">
              <span className="tstep-glyph">{m.glyph}</span>
            </div>
            <div className="tstep-body">
              <div className="tstep-head">
                <span className="tstep-kind">{m.label}</span>
                {t.title && <span className="tstep-title">{t.title}</span>}
              </div>
              {t.detail && <div className="tstep-detail">{t.detail}</div>}
              {ids.length > 0 && (
                <div className="tstep-ev">
                  {ids.map((id) => (
                    <span className="ev-pill" key={id}>{id}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
      {live && traces.length > 0 && (
        <div className="thread-cursor"><span className="spinner" /> agent working…</div>
      )}
    </div>
  );
}

/* ---- backend log ------------------------------------------------------- */

function ts(t: number): string {
  const d = new Date(t);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function BackendLog({ log, live }: { log: LogLine[]; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (live && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log, live]);

  return (
    <div className="blog" ref={ref}>
      {log.map((l, i) => (
        <div className={`blog-line lv-${l.level}`} key={i}>
          <span className="blog-t">{ts(l.t)}</span>
          <span className="blog-lv">{l.level}</span>
          <span className="blog-msg">{l.text}</span>
        </div>
      ))}
      {live && <div className="blog-line lv-wait"><span className="blog-t">{ts(Date.now())}</span><span className="blog-lv">···</span><span className="blog-msg"><span className="spinner" /> stream open</span></div>}
    </div>
  );
}
