export type Level = "transmission" | "distribution";
export type ConnType = "generation" | "demand" | "storage" | "mixed";
export type Verdict = "PASS" | "NEEDS_REVISION" | "FAIL";

export interface ProjectSummary {
  id: string;
  name: string;
  applicant: string;
  level: Level;
  conn_type: ConnType;
  capacity: string;
  status: string;
  submitted: string;
  section_count: number;
  document_count: number;
}

export interface Section {
  id: string;
  title: string;
  requirement: string;
  submitted: string;
  docs: string[];
}

export interface ProjectDetail extends ProjectSummary {
  sections: Section[];
  documents: { name: string }[];
}

export interface Figure {
  figure_id?: string;
  page?: number;
  description?: string;
  image_path?: string;
  local_path?: string;
  s3_uri?: string;
}

export interface Evidence {
  id: string;
  title: string;
  source_path?: string;
  page?: number | null;
  section?: string;
  span_text: string;
  score?: number;
  artifact_source?: string;
  metadata?: { figures?: Figure[] };
}

export interface TraceEntry {
  id?: number;
  kind: string; // user | agent | subagent | tool-call | retrieval | error | result | agentcore
  title?: string;
  detail?: string;
  metadata?: Record<string, unknown>;
}

export interface ResultEvent {
  type: "result";
  status: string;
  answer?: string;
  citations?: Evidence[];
  evidence?: Evidence[];
  latency_ms?: number;
  error?: string;
}

export type AgentEvent =
  | { type: "trace"; entry: TraceEntry }
  | ResultEvent;
