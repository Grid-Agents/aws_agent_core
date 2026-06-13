import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { streamCopilot, streamReview } from "./api";
import type {
  AgentEvent,
  Evidence,
  LogLine,
  Phase,
  TraceEntry,
  Verdict,
} from "./types";

/* ---------------------------------------------------------------------- */
/* state shapes                                                            */
/* ---------------------------------------------------------------------- */

export type RunStatus = "idle" | "running" | "done" | "error";

/** Anything the agent console can observe as a live run. */
interface RunCore {
  status: RunStatus;
  phase: Phase;
  startedAt: number;
  lastEventAt: number;
  traces: TraceEntry[];
  log: LogLine[];
}

export interface ReviewState extends RunCore {
  sectionTitle?: string;
  answer: string;
  summary: string;
  verdict: Verdict | null;
  citations: Evidence[];
  latencyMs?: number;
  error?: string;
}

export interface CopilotPanel extends RunCore {
  id: string;
  sectionTitle?: string;
  selectedText: string;
  question: string;
  answer: string;
  citations: Evidence[];
  error?: string;
}

/** A flattened, uniform view of every run for the global Agent Console. */
export interface Activity {
  key: string;
  kind: "review" | "copilot";
  projectId: string;
  title: string;
  subtitle?: string;
  status: RunStatus;
  phase: Phase;
  startedAt: number;
  lastEventAt: number;
  traces: TraceEntry[];
  log: LogLine[];
  verdict?: Verdict | null;
  citationCount: number;
}

/** Silence past this (ms) on a running stream is treated as a stall. The
 * backend heartbeats every 5s, so >18s of total silence means real trouble. */
export const STALL_MS = 18_000;

const EMPTY_REVIEW: ReviewState = {
  status: "idle",
  phase: "idle",
  startedAt: 0,
  lastEventAt: 0,
  traces: [],
  log: [],
  answer: "",
  summary: "",
  verdict: null,
  citations: [],
};

interface Store {
  reviews: Record<string, Record<string, ReviewState>>; // [projectId][sectionId]
  panels: Record<string, CopilotPanel[]>; // [projectId]
  activities: Activity[];
  tick: number;
  getReview(projectId: string, sectionId: string): ReviewState;
  runReview(projectId: string, sectionId: string, sectionTitle?: string): void;
  runAll(projectId: string, sections: { id: string; title: string }[]): void;
  askCopilot(
    projectId: string,
    sectionId: string | undefined,
    sectionTitle: string | undefined,
    selectedText: string,
    question: string,
  ): void;
  closePanel(projectId: string, panelId: string): void;
}

const Ctx = createContext<Store | null>(null);
export const useStore = () => {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside provider");
  return s;
};

/* ---------------------------------------------------------------------- */
/* helpers                                                                 */
/* ---------------------------------------------------------------------- */

function parseVerdict(answer: string): { verdict: Verdict | null; summary: string } {
  const v = answer.match(/VERDICT:\s*\**\s*(PASS|NEEDS[_\s]REVISION|FAIL)/i);
  const s = answer.match(/SUMMARY:\s*\**\s*(.+)/i);
  const verdict = v
    ? (v[1].toUpperCase().replace(/\s/g, "_") as Verdict)
    : null;
  return { verdict, summary: s ? s[1].trim() : "" };
}

/** Strip the machine-readable trailer so the prose reads cleanly. */
function cleanAnswer(answer: string): string {
  return answer.replace(/\n*VERDICT:[\s\S]*$/i, "").trim();
}

/** Render a stream event as one human-readable backend-log line. */
function logForEvent(ev: AgentEvent, t: number): LogLine | null {
  if (ev.type === "heartbeat") {
    const s = Math.round((ev.waited_ms ?? 0) / 1000);
    return { t, level: "wait", text: `backend alive — waiting on AgentCore runtime (${s}s)` };
  }
  if (ev.type === "result") {
    if (ev.status === "error") return { t, level: "error", text: `error — ${ev.error ?? "agent failed"}` };
    const sec = ev.latency_ms != null ? ` in ${(ev.latency_ms / 1000).toFixed(1)}s` : "";
    return { t, level: "done", text: `result received — ${ev.citations?.length ?? 0} citation(s)${sec}` };
  }
  const e = ev.entry;
  const d = (e.detail ?? "").replace(/\s+/g, " ").trim();
  switch (e.kind) {
    case "user": return { t, level: "info", text: "task dispatched to agent" };
    case "agentcore": return { t, level: "wait", text: e.title || d || "AgentCore runtime" };
    case "agent": return { t, level: "agent", text: `reasoning — ${d.slice(0, 140)}` };
    case "subagent": return { t, level: "agent", text: `subagent — ${d.slice(0, 140)}` };
    case "tool-call": return { t, level: "info", text: e.title || "tool call" };
    case "subagent-call": return { t, level: "info", text: e.title || "subagent dispatched" };
    case "retrieval": return { t, level: "search", text: `${e.title} — “${d.slice(0, 100)}”` };
    case "inspect": return { t, level: "info", text: e.title || "inspected evidence" };
    case "citation": return { t, level: "cite", text: `${e.title} — ${d}` };
    case "error": return { t, level: "error", text: `${e.title} — ${d}` };
    case "result": return null; // covered by the terminal result event
    default: return { t, level: "info", text: e.title || e.kind };
  }
}

/** Phase + trace + log patch for a trace/heartbeat event (not the result). */
function ingestStreamEvent(cur: RunCore, ev: AgentEvent): Partial<RunCore> {
  const now = Date.now();
  const out: Partial<RunCore> = { lastEventAt: now };
  const ln = logForEvent(ev, now);
  if (ln) out.log = [...cur.log, ln];
  if (ev.type === "heartbeat") {
    out.phase = cur.phase === "active" ? "active" : "waiting";
  } else if (ev.type === "trace") {
    out.traces = [...cur.traces, ev.entry];
    // The deployed runtime's own "invoking" notice still counts as waiting;
    // any real reasoning/search step means the agent is actively working.
    out.phase = ev.entry.kind === "agentcore" ? "waiting" : "active";
  }
  return out;
}

/* ---------------------------------------------------------------------- */
/* provider                                                                */
/* ---------------------------------------------------------------------- */

export function StoreProvider({ children }: { children: ReactNode }) {
  const [reviews, setReviews] = useState<Store["reviews"]>({});
  const [panels, setPanels] = useState<Store["panels"]>({});
  // Guard against duplicate concurrent runs of the same section.
  const inflight = useRef<Set<string>>(new Set());

  // 1 Hz clock so elapsed timers + stall detection re-render while a run is
  // live, without forcing renders when everything is idle.
  const [tick, setTick] = useState(Date.now());
  const hasRunning = useMemo(
    () =>
      Object.values(reviews).some((p) => Object.values(p).some((s) => s.status === "running")) ||
      Object.values(panels).some((arr) => arr.some((p) => p.status === "running")),
    [reviews, panels],
  );
  const hasRunningRef = useRef(hasRunning);
  hasRunningRef.current = hasRunning;
  useEffect(() => {
    const h = setInterval(() => {
      if (hasRunningRef.current) setTick(Date.now());
    }, 1000);
    return () => clearInterval(h);
  }, []);

  const patchReview = useCallback(
    (pid: string, sid: string, patch: Partial<ReviewState>) => {
      setReviews((prev) => {
        const proj = prev[pid] ?? {};
        const cur = proj[sid] ?? EMPTY_REVIEW;
        return { ...prev, [pid]: { ...proj, [sid]: { ...cur, ...patch } } };
      });
    },
    [],
  );

  const runReview = useCallback(
    (pid: string, sid: string, sectionTitle?: string) => {
      const key = `${pid}/${sid}`;
      if (inflight.current.has(key)) return;
      inflight.current.add(key);
      const now = Date.now();
      patchReview(pid, sid, {
        ...EMPTY_REVIEW,
        status: "running",
        phase: "connecting",
        startedAt: now,
        lastEventAt: now,
        sectionTitle,
        log: [{ t: now, level: "info", text: `POST review · section ${sid}` }],
      });

      const onOpen = () =>
        setReviews((prev) => {
          const cur = prev[pid]?.[sid];
          if (!cur || cur.status !== "running") return prev;
          const nowOpen = Date.now();
          return {
            ...prev,
            [pid]: {
              ...prev[pid],
              [sid]: {
                ...cur,
                phase: cur.phase === "connecting" ? "waiting" : cur.phase,
                lastEventAt: nowOpen,
                log: [...cur.log, { t: nowOpen, level: "info", text: "connection open — awaiting agent" }],
              },
            },
          };
        });

      const onEvent = (ev: AgentEvent) => {
        if (ev.type === "result") {
          // Append the terminal line to whatever the live (functional) state
          // holds — never rebuild the log from a stale closure, or the
          // accumulated heartbeat/trace lines are lost.
          const term = logForEvent(ev, Date.now());
          setReviews((prev) => {
            const cur = prev[pid]?.[sid] ?? EMPTY_REVIEW;
            const base = { ...cur, lastEventAt: Date.now(), log: term ? [...cur.log, term] : cur.log };
            const next =
              ev.status === "error"
                ? { ...base, status: "error" as const, phase: "error" as const, error: ev.error || "agent error" }
                : (() => {
                    const raw = ev.answer || "";
                    const { verdict, summary } = parseVerdict(raw);
                    return {
                      ...base,
                      status: "done" as const,
                      phase: "done" as const,
                      answer: cleanAnswer(raw),
                      verdict,
                      summary,
                      citations: ev.citations || [],
                      latencyMs: ev.latency_ms,
                    };
                  })();
            return { ...prev, [pid]: { ...prev[pid], [sid]: next } };
          });
          return;
        }
        setReviews((prev) => {
          const cur = prev[pid]?.[sid] ?? EMPTY_REVIEW;
          return { ...prev, [pid]: { ...prev[pid], [sid]: { ...cur, ...ingestStreamEvent(cur, ev) } } };
        });
      };

      streamReview(pid, sid, { onEvent, onOpen })
        .catch((e) =>
          patchReview(pid, sid, {
            status: "error",
            phase: "error",
            error: String(e),
            lastEventAt: Date.now(),
          }),
        )
        .finally(() => inflight.current.delete(key));
    },
    [patchReview, reviews],
  );

  // Fire a batch with a small concurrency cap (real agent calls are slow + billable).
  const runAll = useCallback(
    (pid: string, sections: { id: string; title: string }[]) => {
      const queue = sections.filter((s) => {
        const st = reviews[pid]?.[s.id]?.status;
        return st !== "running" && st !== "done";
      });
      const CAP = 3;
      let i = 0;
      const pump = () => {
        while (i < queue.length && inflight.current.size < CAP) {
          const s = queue[i++];
          runReview(pid, s.id, s.title);
        }
        if (i < queue.length) setTimeout(pump, 600);
      };
      pump();
    },
    [reviews, runReview],
  );

  const askCopilot = useCallback(
    (
      pid: string,
      sectionId: string | undefined,
      sectionTitle: string | undefined,
      selectedText: string,
      question: string,
    ) => {
      const panelId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const now = Date.now();
      const panel: CopilotPanel = {
        id: panelId,
        sectionTitle,
        selectedText,
        question,
        status: "running",
        phase: "connecting",
        startedAt: now,
        lastEventAt: now,
        traces: [],
        log: [{ t: now, level: "info", text: "POST co-pilot query" }],
        answer: "",
        citations: [],
      };
      setPanels((prev) => ({ ...prev, [pid]: [panel, ...(prev[pid] ?? [])] }));

      const patch = (p: Partial<CopilotPanel>) =>
        setPanels((prev) => ({
          ...prev,
          [pid]: (prev[pid] ?? []).map((x) => (x.id === panelId ? { ...x, ...p } : x)),
        }));

      const onOpen = () =>
        setPanels((prev) => ({
          ...prev,
          [pid]: (prev[pid] ?? []).map((x) => {
            if (x.id !== panelId || x.status !== "running") return x;
            const nowOpen = Date.now();
            return {
              ...x,
              phase: x.phase === "connecting" ? "waiting" : x.phase,
              lastEventAt: nowOpen,
              log: [...x.log, { t: nowOpen, level: "info", text: "connection open — awaiting agent" }],
            };
          }),
        }));

      const onEvent = (ev: AgentEvent) => {
        if (ev.type === "result") {
          const term = logForEvent(ev, Date.now());
          setPanels((prev) => ({
            ...prev,
            [pid]: (prev[pid] ?? []).map((x) => {
              if (x.id !== panelId) return x;
              const base = { ...x, lastEventAt: Date.now(), log: term ? [...x.log, term] : x.log };
              return ev.status === "error"
                ? { ...base, status: "error" as const, phase: "error" as const, error: ev.error || "agent error" }
                : { ...base, status: "done" as const, phase: "done" as const, answer: cleanAnswer(ev.answer || ""), citations: ev.citations || [] };
            }),
          }));
          return;
        }
        setPanels((prev) => ({
          ...prev,
          [pid]: (prev[pid] ?? []).map((x) =>
            x.id === panelId ? { ...x, ...ingestStreamEvent(x, ev) } : x,
          ),
        }));
      };

      streamCopilot({ project_id: pid, section_id: sectionId, selected_text: selectedText, question }, { onEvent, onOpen })
        .catch((e) => patch({ status: "error", phase: "error", error: String(e), lastEventAt: Date.now() }));
    },
    [],
  );

  const closePanel = useCallback((pid: string, panelId: string) => {
    setPanels((prev) => ({ ...prev, [pid]: (prev[pid] ?? []).filter((x) => x.id !== panelId) }));
  }, []);

  const activities = useMemo<Activity[]>(() => {
    const out: Activity[] = [];
    for (const [pid, secs] of Object.entries(reviews)) {
      for (const [sid, st] of Object.entries(secs)) {
        if (st.phase === "idle") continue;
        out.push({
          key: `r:${pid}:${sid}`,
          kind: "review",
          projectId: pid,
          title: st.sectionTitle || `Section ${sid}`,
          subtitle: pid,
          status: st.status,
          phase: st.phase,
          startedAt: st.startedAt,
          lastEventAt: st.lastEventAt,
          traces: st.traces,
          log: st.log,
          verdict: st.verdict,
          citationCount: st.citations.length,
        });
      }
    }
    for (const [pid, arr] of Object.entries(panels)) {
      for (const p of arr) {
        out.push({
          key: `c:${pid}:${p.id}`,
          kind: "copilot",
          projectId: pid,
          title: p.question,
          subtitle: p.sectionTitle || pid,
          status: p.status,
          phase: p.phase,
          startedAt: p.startedAt,
          lastEventAt: p.lastEventAt,
          traces: p.traces,
          log: p.log,
          citationCount: p.citations.length,
        });
      }
    }
    out.sort((a, b) => b.startedAt - a.startedAt);
    return out;
  }, [reviews, panels]);

  const value: Store = {
    reviews,
    panels,
    activities,
    tick,
    getReview: (pid, sid) => reviews[pid]?.[sid] ?? EMPTY_REVIEW,
    runReview,
    runAll,
    askCopilot,
    closePanel,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
