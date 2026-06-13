import { useEffect, useRef, useState } from "react";
import type { TraceEntry } from "../types";

const KIND_LABEL: Record<string, string> = {
  user: "task",
  agent: "agent",
  subagent: "sub",
  "tool-call": "tool",
  retrieval: "search",
  error: "error",
  result: "done",
  agentcore: "aws",
};

function kindClass(kind: string): string {
  if (kind === "tool-call") return "tool";
  if (kind === "retrieval") return "retrieval";
  if (kind === "subagent") return "subagent";
  if (kind === "error") return "error";
  return "";
}

export function TraceList({ traces, live }: { traces: TraceEntry[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (live && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [traces, live]);

  if (traces.length === 0) return null;
  const visible = open ? traces : traces.slice(-3);

  return (
    <>
      <div ref={ref} className={`trace ${open ? "" : "collapsed"}`}>
        {visible.map((t, i) => (
          <div key={i} className={`trace-line ${kindClass(t.kind)}`}>
            <span className="k">{KIND_LABEL[t.kind] ?? t.kind}</span>
            <span className="v">
              {t.title}
              {t.detail ? ` — ${t.detail.slice(0, 160)}` : ""}
            </span>
          </div>
        ))}
      </div>
      {traces.length > 3 && (
        <button className="trace-toggle" onClick={() => setOpen((o) => !o)}>
          {open ? "▲ collapse trajectory" : `▼ show full trajectory (${traces.length} steps)`}
        </button>
      )}
    </>
  );
}
