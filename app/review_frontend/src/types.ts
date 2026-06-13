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

export interface HeartbeatEvent {
  type: "heartbeat";
  waited_ms?: number;
}

export type AgentEvent =
  | { type: "trace"; entry: TraceEntry }
  | HeartbeatEvent
  | ResultEvent;

/**
 * Lifecycle of a single agent run as observed by the client.
 *  connecting — request issued, awaiting response headers
 *  waiting    — connection open / backend alive, but no reasoning yet (AWS warm-up)
 *  active     — agent is reasoning / searching (trace steps streaming)
 *  stalled    — running but no signal for a while (possible crash) — derived, never stored
 *  done | error — terminal
 */
export type Phase =
  | "idle"
  | "connecting"
  | "waiting"
  | "active"
  | "stalled"
  | "done"
  | "error";

export type LogLevel =
  | "info"
  | "wait"
  | "agent"
  | "search"
  | "cite"
  | "warn"
  | "error"
  | "done";

export interface LogLine {
  t: number; // epoch ms
  level: LogLevel;
  text: string;
}

export type Confidence = "high" | "medium" | "low";

export interface IntakeSummary {
  id: string;
  name: string;
  applicant: string;
  level: Level;
  conn_type: ConnType;
  sender: string;
  subject: string;
  status: string; // extracted | extraction_failed
  section_count: number;
  flag_count: number;
}

export interface IntakeSection extends Section {
  confidence: Confidence;
}

export interface IntakeBlock {
  status: string;
  level_confidence: Confidence;
  flags: string[];
  unmapped_docs: string[];
  sender?: string;
  subject?: string;
  intake_id?: string;
  error?: string;
}

export interface IntakeDetail {
  id?: string;
  name: string;
  applicant: string;
  level: Level;
  conn_type: ConnType;
  capacity: string;
  sections: IntakeSection[];
  documents: { name: string }[];
  intake: IntakeBlock;
}
