import { streamNDJSON } from "./lib/ndjson";
import type { AgentEvent, IntakeDetail, IntakeSummary, Level, ProjectDetail, ProjectSummary } from "./types";

export async function fetchProjects(level: Level): Promise<ProjectSummary[]> {
  const r = await fetch(`/api/review/projects?level=${level}`);
  if (!r.ok) throw new Error(`projects ${r.status}`);
  return (await r.json()).projects;
}

export async function fetchProject(id: string): Promise<ProjectDetail> {
  const r = await fetch(`/api/review/projects/${id}`);
  if (!r.ok) throw new Error(`project ${r.status}`);
  return r.json();
}

/** Lifecycle hooks shared by the review + co-pilot stream callers. */
export interface StreamHooks {
  onEvent: (ev: AgentEvent) => void;
  /** Fired once the response headers arrive (connection open, before any event). */
  onOpen?: () => void;
  signal?: AbortSignal;
}

export async function streamReview(
  projectId: string,
  sectionId: string,
  hooks: StreamHooks,
): Promise<void> {
  const r = await fetch(
    `/api/review/projects/${projectId}/sections/${sectionId}/review`,
    { method: "POST", headers: { "content-type": "application/json" }, body: "{}", signal: hooks.signal },
  );
  hooks.onOpen?.();
  if (!r.ok) throw new Error(`review ${r.status}`);
  await streamNDJSON(r, hooks.onEvent);
}

export interface CopilotBody {
  project_id: string;
  section_id?: string;
  selected_text: string;
  question: string;
}

export async function streamCopilot(
  body: CopilotBody,
  hooks: StreamHooks,
): Promise<void> {
  const r = await fetch(`/api/review/copilot`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal: hooks.signal,
  });
  hooks.onOpen?.();
  if (!r.ok) throw new Error(`copilot ${r.status}`);
  await streamNDJSON(r, hooks.onEvent);
}

/** Resolve an evidence figure to a servable /artifacts URL. */
export function figureUrl(path?: string): string | null {
  if (!path) return null;
  const rel = path.includes("figures/") ? path.slice(path.indexOf("figures/")) : path;
  return `/artifacts/${rel.replace(/^\/+/, "")}`;
}

export function pdfUrl(projectId: string, doc: string): string {
  return `/review-pdfs/${projectId}/${doc}`;
}

export async function fetchIntakeQueue(): Promise<IntakeSummary[]> {
  const r = await fetch(`/api/review/intake`);
  if (!r.ok) throw new Error(`intake ${r.status}`);
  return (await r.json()).pending;
}

export async function fetchIntake(id: string): Promise<IntakeDetail> {
  const r = await fetch(`/api/review/intake/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(`intake ${r.status}`);
  return r.json();
}

export async function acceptIntake(id: string): Promise<string> {
  const r = await fetch(`/api/review/intake/${encodeURIComponent(id)}/accept`, { method: "POST" });
  if (!r.ok) throw new Error(`accept ${r.status}`);
  return (await r.json()).project_id;
}

export async function rejectIntake(id: string, reason: string): Promise<void> {
  const r = await fetch(`/api/review/intake/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) throw new Error(`reject ${r.status}`);
}

/** Original attachment PDF for a pending intake (served from review_seed/pending). */
export function intakePdfUrl(intakeId: string, doc: string): string {
  return `/intake-pdfs/${encodeURIComponent(intakeId)}/${doc}`;
}
