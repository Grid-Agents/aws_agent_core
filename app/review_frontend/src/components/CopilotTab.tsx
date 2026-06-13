import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useState } from "react";
import { useStore } from "../store";
import type { ProjectDetail } from "../types";
import { Citations } from "./Citations";
import { Markdown } from "./Markdown";
import { RunStatusLine } from "./RunStatusLine";
import { TraceList } from "./TraceList";

interface Pending {
  text: string;
  sectionId?: string;
  sectionTitle?: string;
  x: number;
  y: number;
}

export function CopilotTab({ project }: { project: ProjectDetail }) {
  const { panels, askCopilot, closePanel } = useStore();
  const [pending, setPending] = useState<Pending | null>(null);
  const [question, setQuestion] = useState("");
  const myPanels = panels[project.id] ?? [];

  const onSelect = useCallback((sectionId: string, sectionTitle: string) => {
    const sel = window.getSelection();
    const text = sel?.toString().trim() ?? "";
    if (!sel || text.length < 4) {
      setPending(null);
      return;
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    setPending({
      text,
      sectionId,
      sectionTitle,
      x: Math.min(rect.left, window.innerWidth - 360),
      y: rect.bottom + 8,
    });
    setQuestion("");
  }, []);

  const submit = () => {
    if (!pending || !question.trim()) return;
    askCopilot(project.id, pending.sectionId, pending.sectionTitle, pending.text, question.trim());
    setPending(null);
    setQuestion("");
  };

  return (
    <>
      <div className="copilot-hint">
        ✶ Highlight any phrase in a section below, then ask the agent a question about it.
        Queries run in parallel — fire several at once.
      </div>

      <div className="copilot-wrap">
        <div className="copilot-source">
          {project.sections.map((s) => (
            <div className="sec" key={s.id}>
              <div className="sec-body" style={{ borderTop: "none", paddingTop: 16 }}>
                <div className="sectitle">{s.title}</div>
                <div
                  className="selectable"
                  onMouseUp={() => onSelect(s.id, s.title)}
                >
                  {s.submitted}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="panels">
          {myPanels.length === 0 && (
            <div className="empty-state" style={{ padding: "48px 20px" }}>
              <div className="big" style={{ fontSize: 18 }}>No queries yet</div>
              <div>Select text and ask to launch a co-pilot thread.</div>
            </div>
          )}
          <AnimatePresence>
            {myPanels.map((p) => (
              <motion.div
                className="panel"
                key={p.id}
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.25 }}
              >
                <div className="phead">
                  <span className="quoted">“{p.selectedText.slice(0, 180)}”</span>
                  <button className="pclose" onClick={() => closePanel(project.id, p.id)}>×</button>
                </div>
                <div className="question">{p.question}</div>
                <div className="pbody">
                  {p.status === "running" && (
                    <RunStatusLine phase={p.phase} startedAt={p.startedAt} lastEventAt={p.lastEventAt} />
                  )}
                  {p.status === "running" && <TraceList traces={p.traces} live />}
                  {p.status === "error" && <div className="summary fail">⚠ {p.error}</div>}
                  {p.status === "done" && (
                    <>
                      <div className="answer"><Markdown text={p.answer} /></div>
                      <Citations items={p.citations} />
                    </>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>

      {pending && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 55 }} onMouseDown={() => setPending(null)} />
          <div className="sel-pop" style={{ left: pending.x, top: pending.y }} onMouseDown={(e) => e.stopPropagation()}>
            <div className="q">Ask the agent</div>
            <div className="quote">“{pending.text.slice(0, 160)}”</div>
            <textarea
              autoFocus
              placeholder="e.g. Does this satisfy the Gate 2 land-control criterion?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
              }}
            />
            <div className="actions">
              <button className="ghost" onClick={() => setPending(null)}>Cancel</button>
              <button className="ask" onClick={submit} disabled={!question.trim()}>Ask ↵</button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
