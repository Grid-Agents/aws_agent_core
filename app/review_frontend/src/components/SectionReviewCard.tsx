import { motion } from "framer-motion";
import { pdfUrl } from "../api";
import { useStore } from "../store";
import type { Section } from "../types";
import { Citations } from "./Citations";
import { Markdown } from "./Markdown";
import { RunStatusLine } from "./RunStatusLine";
import { TraceList } from "./TraceList";
import { VerdictBadge, verdictClass } from "./bits";

export function SectionReviewCard({
  projectId,
  section,
  index,
}: {
  projectId: string;
  section: Section;
  index: number;
}) {
  const { getReview, runReview } = useStore();
  const r = getReview(projectId, section.id);
  const running = r.status === "running";
  const active = running || r.status === "done" || r.status === "error";

  return (
    <motion.div
      className={`sec ${active ? "active" : ""}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.035, duration: 0.3 }}
    >
      <div className="sec-head">
        <span className="num">{String(index + 1).padStart(2, "0")}</span>
        <span className="title">{section.title}</span>
        {section.docs.length > 0 && (
          <span className="docs-flag">▣ {section.docs.length} doc{section.docs.length > 1 ? "s" : ""}</span>
        )}
        <VerdictBadge status={r.status} verdict={r.verdict} />
        <button
          className="btn sm"
          onClick={() => runReview(projectId, section.id, section.title)}
          disabled={running}
        >
          {running ? <><span className="spinner" /> Running</> : r.status === "done" ? "Re-review" : "Review"}
        </button>
      </div>

      <div className="sec-body">
        <div className="field">
          <div className="label">Requirement</div>
          <div className="req">{section.requirement}</div>
        </div>
        <div className="field">
          <div className="label">Developer submitted</div>
          <div className="submitted">{section.submitted}</div>
          {section.docs.length > 0 && (
            <div className="doc-pills">
              {section.docs.map((d) => (
                <a key={d} className="doc-pill" href={pdfUrl(projectId, d)} target="_blank" rel="noreferrer">
                  ▣ {d}
                </a>
              ))}
            </div>
          )}
        </div>

        {running && (
          <RunStatusLine phase={r.phase} startedAt={r.startedAt} lastEventAt={r.lastEventAt} />
        )}

        {(running || r.traces.length > 0) && <TraceList traces={r.traces} live={running} />}

        {r.status === "error" && (
          <div className="review-out">
            <div className="summary fail">⚠ {r.error}</div>
          </div>
        )}

        {r.status === "done" && (
          <div className="review-out">
            {r.answer && <div className="answer"><Markdown text={r.answer} /></div>}
            {r.summary && (
              <div className={`summary ${verdictClass(r.verdict)}`}>
                <VerdictBadge status="done" verdict={r.verdict} />
                <span>{r.summary}</span>
              </div>
            )}
            <Citations items={r.citations} />
            {r.latencyMs != null && (
              <div className="trace-toggle" style={{ paddingLeft: 0 }}>
                completed in {(r.latencyMs / 1000).toFixed(1)}s
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
