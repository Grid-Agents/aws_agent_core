import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchProject } from "../api";
import { CopilotTab } from "../components/CopilotTab";
import { DocumentsTab } from "../components/DocumentsTab";
import { SectionReviewCard } from "../components/SectionReviewCard";
import { TypeChip } from "../components/bits";
import { useStore } from "../store";
import type { ProjectDetail } from "../types";

type Tab = "review" | "copilot" | "documents";

export function ProjectPage() {
  const { id = "" } = useParams();
  const { runAll, reviews, panels } = useStore();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("review");

  useEffect(() => {
    setProject(null);
    fetchProject(id).then(setProject).catch((e) => setErr(String(e)));
  }, [id]);

  const backTo = useMemo(
    () => (project ? `/${project.level}` : "/transmission"),
    [project],
  );

  if (err)
    return (
      <div className="page">
        <div className="empty-state"><div className="big">Project not found</div><div>{err}</div></div>
      </div>
    );
  if (!project)
    return <div className="page"><div className="loading-rail"><span className="spinner" /> loading submission…</div></div>;

  const sectionStates = reviews[project.id] ?? {};
  const runningCount = Object.values(sectionStates).filter((s) => s.status === "running").length;
  const panelCount = (panels[project.id] ?? []).length;

  return (
    <div className="page">
      <div className="crumb">
        <Link to={backTo}>{project.level} queue</Link> &nbsp;/&nbsp; {project.id}
      </div>

      <div className="proj-header">
        <div>
          <div className="eyebrow">{project.level} · {project.conn_type}</div>
          <h1>{project.name}</h1>
          <div className="applicant" style={{ color: "var(--muted)" }}>{project.applicant}</div>
          <div className="meta-row">
            <Spec k="Project ID" v={project.id} mono />
            <Spec k="Capacity" v={project.capacity} />
            <Spec k="Status" v={project.status} />
            <Spec k="Submitted" v={project.submitted} mono />
            <Spec k="Sections" v={String(project.section_count)} />
            <Spec k="Documents" v={String(project.document_count)} />
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-end" }}>
          <TypeChip type={project.conn_type} />
          <button
            className="btn primary"
            onClick={() => runAll(project.id, project.sections.map((s) => s.id))}
            disabled={runningCount > 0}
          >
            {runningCount > 0 ? <><span className="spinner" /> {runningCount} running…</> : "⚡ Review all sections"}
          </button>
        </div>
      </div>

      <div className="tabs">
        <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}>
          Section review <span className="count">{project.section_count}</span>
        </button>
        <button className={tab === "copilot" ? "active" : ""} onClick={() => setTab("copilot")}>
          Co-pilot {panelCount > 0 && <span className="count">{panelCount}</span>}
        </button>
        <button className={tab === "documents" ? "active" : ""} onClick={() => setTab("documents")}>
          Documents <span className="count">{project.document_count + 1}</span>
        </button>
      </div>

      {tab === "review" &&
        project.sections.map((s, i) => (
          <SectionReviewCard key={s.id} projectId={project.id} section={s} index={i} />
        ))}
      {tab === "copilot" && <CopilotTab project={project} />}
      {tab === "documents" && <DocumentsTab project={project} />}
    </div>
  );
}

function Spec({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="spec">
      <span className="k">{k}</span>
      <span className={`v ${mono ? "mono" : ""}`}>{v}</span>
    </div>
  );
}
