import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { streamCopilot, streamReview } from "./api";
import type { AgentEvent, Evidence, TraceEntry, Verdict } from "./types";

/* ---------------------------------------------------------------------- */
/* state shapes                                                            */
/* ---------------------------------------------------------------------- */

export type RunStatus = "idle" | "running" | "done" | "error";

export interface ReviewState {
  status: RunStatus;
  traces: TraceEntry[];
  answer: string;
  summary: string;
  verdict: Verdict | null;
  citations: Evidence[];
  latencyMs?: number;
  error?: string;
}

export interface CopilotPanel {
  id: string;
  sectionTitle?: string;
  selectedText: string;
  question: string;
  status: RunStatus;
  traces: TraceEntry[];
  answer: string;
  citations: Evidence[];
  error?: string;
}

const EMPTY_REVIEW: ReviewState = {
  status: "idle",
  traces: [],
  answer: "",
  summary: "",
  verdict: null,
  citations: [],
};

interface Store {
  reviews: Record<string, Record<string, ReviewState>>; // [projectId][sectionId]
  panels: Record<string, CopilotPanel[]>; // [projectId]
  getReview(projectId: string, sectionId: string): ReviewState;
  runReview(projectId: string, sectionId: string): void;
  runAll(projectId: string, sectionIds: string[]): void;
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

/* ---------------------------------------------------------------------- */
/* provider                                                                */
/* ---------------------------------------------------------------------- */

export function StoreProvider({ children }: { children: ReactNode }) {
  const [reviews, setReviews] = useState<Store["reviews"]>({});
  const [panels, setPanels] = useState<Store["panels"]>({});
  // Guard against duplicate concurrent runs of the same section.
  const inflight = useRef<Set<string>>(new Set());

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
    (pid: string, sid: string) => {
      const key = `${pid}/${sid}`;
      if (inflight.current.has(key)) return;
      inflight.current.add(key);
      patchReview(pid, sid, { ...EMPTY_REVIEW, status: "running" });

      const onEvent = (ev: AgentEvent) => {
        if (ev.type === "trace") {
          const entry = ev.entry;
          setReviews((prev) => {
            const cur = prev[pid]?.[sid] ?? EMPTY_REVIEW;
            return {
              ...prev,
              [pid]: { ...prev[pid], [sid]: { ...cur, traces: [...cur.traces, entry] } },
            };
          });
        } else if (ev.type === "result") {
          if (ev.status === "error") {
            patchReview(pid, sid, { status: "error", error: ev.error || "agent error" });
            return;
          }
          const raw = ev.answer || "";
          const { verdict, summary } = parseVerdict(raw);
          patchReview(pid, sid, {
            status: "done",
            answer: cleanAnswer(raw),
            verdict,
            summary,
            citations: ev.citations || [],
            latencyMs: ev.latency_ms,
          });
        }
      };

      streamReview(pid, sid, onEvent)
        .catch((e) => patchReview(pid, sid, { status: "error", error: String(e) }))
        .finally(() => inflight.current.delete(key));
    },
    [patchReview],
  );

  // Fire a batch with a small concurrency cap (real agent calls are slow + billable).
  const runAll = useCallback(
    (pid: string, sectionIds: string[]) => {
      const queue = sectionIds.filter((sid) => {
        const st = reviews[pid]?.[sid]?.status;
        return st !== "running" && st !== "done";
      });
      const CAP = 3;
      let i = 0;
      const pump = () => {
        while (i < queue.length && inflight.current.size < CAP) {
          runReview(pid, queue[i++]);
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
      const panel: CopilotPanel = {
        id: panelId,
        sectionTitle,
        selectedText,
        question,
        status: "running",
        traces: [],
        answer: "",
        citations: [],
      };
      setPanels((prev) => ({ ...prev, [pid]: [panel, ...(prev[pid] ?? [])] }));

      const patch = (p: Partial<CopilotPanel>) =>
        setPanels((prev) => ({
          ...prev,
          [pid]: (prev[pid] ?? []).map((x) => (x.id === panelId ? { ...x, ...p } : x)),
        }));

      const onEvent = (ev: AgentEvent) => {
        if (ev.type === "trace") {
          setPanels((prev) => ({
            ...prev,
            [pid]: (prev[pid] ?? []).map((x) =>
              x.id === panelId ? { ...x, traces: [...x.traces, ev.entry] } : x,
            ),
          }));
        } else if (ev.type === "result") {
          if (ev.status === "error") {
            patch({ status: "error", error: ev.error || "agent error" });
          } else {
            patch({
              status: "done",
              answer: cleanAnswer(ev.answer || ""),
              citations: ev.citations || [],
            });
          }
        }
      };

      streamCopilot({ project_id: pid, section_id: sectionId, selected_text: selectedText, question }, onEvent)
        .catch((e) => patch({ status: "error", error: String(e) }));
    },
    [],
  );

  const closePanel = useCallback((pid: string, panelId: string) => {
    setPanels((prev) => ({ ...prev, [pid]: (prev[pid] ?? []).filter((x) => x.id !== panelId) }));
  }, []);

  const value: Store = {
    reviews,
    panels,
    getReview: (pid, sid) => reviews[pid]?.[sid] ?? EMPTY_REVIEW,
    runReview,
    runAll,
    askCopilot,
    closePanel,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
