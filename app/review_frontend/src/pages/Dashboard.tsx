import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { fetchProjects } from "../api";
import { TypeChip } from "../components/bits";
import { useStore } from "../store";
import type { Level, ProjectSummary } from "../types";

const LEVEL_BLURB: Record<Level, string> = {
  transmission:
    "Projects connecting directly to the GB transmission system, routed via NESO under the CUSC and the Gate 2 Criteria Methodology.",
  distribution:
    "Projects connecting via a Distribution Network Operator, governed by the Distribution Code, ER G99/G98, and DCUSA.",
};

export function Dashboard() {
  const { pathname } = useLocation();
  const level: Level = pathname.startsWith("/distribution") ? "distribution" : "transmission";
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setProjects(null);
    setErr(null);
    fetchProjects(level).then(setProjects).catch((e) => setErr(String(e)));
  }, [level]);

  return (
    <div className="page">
      <div className="page-head">
        <div className="eyebrow">{level} · application review queue</div>
        <h1>{level === "transmission" ? "Transmission" : "Distribution"} connections</h1>
        <p>{LEVEL_BLURB[level]}</p>
      </div>

      {err && <div className="empty-state"><div className="big">Cannot reach the review API</div><div>{err}</div></div>}
      {!projects && !err && (
        <div className="loading-rail"><span className="spinner" /> loading submission queue…</div>
      )}
      {projects && projects.length === 0 && (
        <div className="empty-state"><div className="big">No submissions in this queue</div></div>
      )}

      {projects && projects.length > 0 && (
        <div className="grid">
          {projects.map((p, i) => (
            <ProjectCard key={p.id} project={p} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project, index }: { project: ProjectSummary; index: number }) {
  const navigate = useNavigate();
  const { reviews } = useStore();
  const byId = reviews[project.id] ?? {};

  let pass = 0, revise = 0, fail = 0, running = 0, done = 0;
  for (const r of Object.values(byId)) {
    if (r.status === "running") running++;
    else if (r.status === "done") {
      done++;
      if (r.verdict === "PASS") pass++;
      else if (r.verdict === "NEEDS_REVISION") revise++;
      else if (r.verdict === "FAIL") fail++;
    }
  }
  const total = project.section_count;
  const pct = (n: number) => `${(n / total) * 100}%`;
  const reviewed = done;

  return (
    <motion.article
      className="card proj-card"
      onClick={() => navigate(`/project/${project.id}`)}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.35, ease: "easeOut" }}
    >
      <div className="stripe" />
      <div className="body">
        <div className="id-row">
          <span className="pid">{project.id}</span>
          <TypeChip type={project.conn_type} />
        </div>
        <h3>{project.name}</h3>
        <div className="applicant">{project.applicant}</div>

        <div className="spec-row">
          <div className="spec">
            <span className="k">Capacity</span>
            <span className="v">{project.capacity}</span>
          </div>
          <div className="spec">
            <span className="k">Submitted</span>
            <span className="v mono">{project.submitted}</span>
          </div>
          <div className="spec">
            <span className="k">Docs</span>
            <span className="v">{project.document_count}</span>
          </div>
        </div>

        <div className="meter">
          <div className="bar">
            {pass > 0 && <i className="pass" style={{ width: pct(pass) }} />}
            {revise > 0 && <i className="revise" style={{ width: pct(revise) }} />}
            {fail > 0 && <i className="fail" style={{ width: pct(fail) }} />}
            {running > 0 && <i className="running" style={{ width: pct(running) }} />}
          </div>
          <div className="legend">
            <span>{reviewed}/{total} sections reviewed</span>
            <span>{running > 0 ? `${running} running` : <Link to={`/project/${project.id}`} onClick={(e) => e.stopPropagation()}>open ›</Link>}</span>
          </div>
        </div>
      </div>
    </motion.article>
  );
}
