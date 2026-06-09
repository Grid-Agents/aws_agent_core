import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const TOOL_LABELS = {
  vector: "Vector",
  pageindex: "PageIndex",
  graphrag: "GraphRAG",
  colivara: "Visual (ColiVara)",
  find: "Exact find",
};

const DEFAULT_PROMPT =
  "What do the Grid Code and connections reform documents say about Gate 2 readiness and evidence requirements?";
const SUBAGENT_ACTIVITY_KINDS = new Set(["tool-call", "retrieval", "inspect"]);

function App() {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [methods, setMethods] = useState(["vector", "pageindex", "find"]);
  const [allowSdkFileTools, setAllowSdkFileTools] = useState(false);
  const [enableSubagents, setEnableSubagents] = useState(true);
  const [events, setEvents] = useState([]);
  const [result, setResult] = useState(null);
  const [overview, setOverview] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetch("/api/overview")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((err) => {
        if (!cancelled) setError(`Overview unavailable: ${err.message}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const readyTools = useMemo(() => {
    const tools = overview?.tools || [];
    return Object.fromEntries(tools.map((tool) => [tool.id, tool.ready]));
  }, [overview]);
  const trajectory = useMemo(() => buildTrajectoryViews(events), [events]);

  async function runAgent() {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) {
      setError("Enter a Grid document question.");
      return;
    }
    setStatus("running");
    setError("");
    setEvents([]);
    setResult(null);
    try {
      const response = await fetch("/api/grid/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          prompt: cleanPrompt,
          methods,
          allow_sdk_file_tools: allowSdkFileTools,
          enable_subagents: enableSubagents,
        }),
      });
      if (!response.ok || !response.body) {
        throw new Error(`Request failed: ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "trace") {
            setEvents((current) => [...current, event.entry]);
          } else if (event.type === "result") {
            setResult(event);
            setStatus(event.status || "completed");
            if (event.status === "error" && event.error) {
              setError(event.error);
            }
          }
        }
      }
    } catch (err) {
      setStatus("error");
      setError(err.message);
    }
  }

  function toggleMethod(method) {
    setMethods((current) =>
      current.includes(method)
        ? current.filter((item) => item !== method)
        : [...current, method],
    );
  }

  return (
    <main className="app-shell">
      <aside className="query-rail">
        <div className="brand-block">
          <div className="brand-mark">GA</div>
          <div>
            <h1>Grid Agents</h1>
            <p>AgentCore QA over Grid documents</p>
          </div>
        </div>

        <label className="field-label" htmlFor="prompt">
          Question
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={9}
        />

        <section className="control-group" aria-label="Retrieval tools">
          <h2>Retrieval Tools</h2>
          {Object.entries(TOOL_LABELS).map(([method, label]) => (
            <label className="check-row" key={method}>
              <input
                type="checkbox"
                checked={methods.includes(method)}
                onChange={() => toggleMethod(method)}
              />
              <span>{label}</span>
              <small>{readyTools[method] === false ? "missing index" : "ready"}</small>
            </label>
          ))}
        </section>

        <section className="control-group" aria-label="Agent controls">
          <h2>Agent Controls</h2>
          <label className="check-row">
            <input
              type="checkbox"
              checked={enableSubagents}
              onChange={(event) => setEnableSubagents(event.target.checked)}
            />
            <span>span-retriever subagents</span>
            <small>{enableSubagents ? "enabled" : "off"}</small>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={allowSdkFileTools}
              onChange={(event) => setAllowSdkFileTools(event.target.checked)}
            />
            <span>SDK file inspection</span>
            <small>scoped</small>
          </label>
        </section>

        <button className="run-button" type="button" onClick={runAgent} disabled={status === "running"}>
          {status === "running" ? "Running search" : "Ask Grid Agents"}
        </button>

        <div className="meta-strip">
          <span>{overview?.documents?.length || 0} docs</span>
          <span>{overview?.artifact_revision?.slice(0, 8) || "no index"}</span>
          <span>{overview?.model || "model pending"}</span>
        </div>
      </aside>

      <section className="workbench">
        <header className="topbar">
          <div>
            <strong>{statusLabel(status)}</strong>
            <span>{overview?.artifact_dir || "Artifacts not loaded"}</span>
          </div>
          <div className="run-meta">
            <span>{result?.latency_ms ? `${result.latency_ms} ms` : "latency pending"}</span>
            <span>{result?.enable_subagents === false ? "subagents off" : "subagents on"}</span>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        <section className="answer-band">
          <h2>Cited Answer</h2>
          <p className={result?.answer ? "answer-text" : "empty-text"}>
            {result?.answer || "Run a question to stream root-agent turns, retrieval calls, subagent notes, citations, and run metadata."}
          </p>
        </section>

        <div className="split-grid">
          <section className="evidence-panel">
            <PanelHeader title="Source Snippets" count={result?.citations?.length || 0} />
            {(result?.citations || []).length ? (
              result.citations.map((item) => <EvidenceItem key={item.id} item={item} />)
            ) : (
              <p className="empty-text">Cited evidence appears after `cite_evidence` runs.</p>
            )}
          </section>

          <section className="trace-panel">
            <PanelHeader title="Observable Trajectory" count={events.length} />
            {events.length ? (
              <TrajectoryView trajectory={trajectory} />
            ) : (
              <p className="empty-text">Waiting for SDK events.</p>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function statusLabel(status) {
  if (status === "idle") return "Ready";
  if (status === "running") return "Running";
  if (status === "completed") return "Completed";
  if (status === "insufficient_evidence") return "Needs stronger evidence";
  if (status === "error") return "Error";
  return status;
}

function PanelHeader({ title, count }) {
  return (
    <div className="panel-header">
      <h2>{title}</h2>
      <span>{count}</span>
    </div>
  );
}

function EvidenceItem({ item }) {
  const figures = Array.isArray(item.metadata?.figures) ? item.metadata.figures : [];
  return (
    <article className="evidence-item">
      <div>
        <strong>{item.id} · {item.title}</strong>
        <span>{item.category} · page {item.page || "?"} · {item.artifact_source}</span>
      </div>
      <p>{item.span_text}</p>
      {figures.length ? (
        <ul className="figure-list" aria-label={`${item.id} attached figures`}>
          {figures.map((figure) => {
            const href = figure.s3_uri || figure.local_path || figure.image_path;
            return (
              <li key={figure.figure_id || figure.filename}>
                <span>{figure.figure_id || figure.filename}</span>
                {href ? <a href={href}>{href}</a> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </article>
  );
}

function TraceItem({ event }) {
  const owner = ownerLabel(event);
  const stage = stageLabel(event);
  return (
    <details
      className={`trace-item ${event.kind} ${owner === "Subagent" ? "owned-subagent" : "owned-root"}`}
      open={event.kind === "result" || event.kind === "error"}
    >
      <summary>
        <span className="trace-kind">{stage}</span>
        <strong>{event.title}</strong>
        <span className="owner-pill">{owner}</span>
      </summary>
      <p>{event.detail}</p>
      {event.metadata && Object.keys(event.metadata).length ? (
        <pre>{JSON.stringify(event.metadata, null, 2)}</pre>
      ) : null}
    </details>
  );
}

function TrajectoryView({ trajectory }) {
  return (
    <div className="trajectory-stack">
      <section className="trajectory-section">
        <div className="trajectory-heading">
          <h3>Root Agent Timeline</h3>
          <span>{trajectory.rootEvents.length}</span>
        </div>
        {trajectory.rootEvents.map((event) => (
          <TraceItem key={event.id} event={event} />
        ))}
      </section>

      <section className="trajectory-section subagent-section">
        <div className="trajectory-heading">
          <h3>Subagent Threads</h3>
          <span>{trajectory.subagentThreads.length}</span>
        </div>
        {trajectory.subagentThreads.length ? (
          trajectory.subagentThreads.map((thread, index) => (
            <article className="subagent-thread" key={thread.id || index}>
              <header>
                <div>
                  <strong>{thread.title}</strong>
                  <span>{thread.id ? `thread ${thread.id.slice(0, 8)}` : "unlinked thread"}</span>
                </div>
                <span>{thread.events.length} turns</span>
              </header>
              {thread.call ? <TraceItem event={thread.call} /> : null}
              {thread.events.map((event) => (
                <TraceItem key={event.id} event={event} />
              ))}
            </article>
          ))
        ) : (
          <p className="empty-text">No subagent events streamed for this run.</p>
        )}
      </section>
    </div>
  );
}

function buildTrajectoryViews(events) {
  const calls = new Map();
  const rootEvents = [];
  const orphanSubagentEvents = [];
  let activeSubagentId = "";

  for (const event of events) {
    if (event.kind === "subagent-call") {
      const id = event.metadata?.tool_use_id || `subagent-call-${event.id}`;
      calls.set(id, {
        id,
        call: event,
        title: summarizeSubagentCall(event),
        events: [],
      });
      activeSubagentId = id;
      rootEvents.push(event);
      continue;
    }

    const parentId = event.metadata?.parent_tool_use_id;
    if (parentId) {
      if (!calls.has(parentId)) {
        calls.set(parentId, {
          id: parentId,
          call: null,
          title: "span-retriever",
          events: [],
        });
      }
      calls.get(parentId).events.push(event);
      continue;
    }

    if (activeSubagentId && SUBAGENT_ACTIVITY_KINDS.has(event.kind)) {
      calls.get(activeSubagentId)?.events.push({
        ...event,
        metadata: {
          ...(event.metadata || {}),
          inferred_parent_tool_use_id: activeSubagentId,
        },
      });
      continue;
    }

    if (event.kind === "subagent") {
      orphanSubagentEvents.push(event);
      continue;
    }

    if (["agent", "user", "result", "error"].includes(event.kind)) {
      activeSubagentId = "";
    }
    rootEvents.push(event);
  }

  if (orphanSubagentEvents.length) {
    calls.set("unlinked-subagent-events", {
      id: "",
      call: null,
      title: "span-retriever",
      events: orphanSubagentEvents,
    });
  }

  return {
    rootEvents,
    subagentThreads: Array.from(calls.values()),
  };
}

function summarizeSubagentCall(event) {
  try {
    const payload = JSON.parse(event.detail || "{}");
    return payload.description || payload.prompt || payload.task || "span-retriever";
  } catch {
    return "span-retriever";
  }
}

function ownerLabel(event) {
  if (
    event.kind === "subagent" ||
    event.metadata?.parent_tool_use_id ||
    event.metadata?.inferred_parent_tool_use_id
  ) {
    return "Subagent";
  }
  return "Root Agent";
}

function stageLabel(event) {
  return {
    user: "question",
    agent: "root turn",
    subagent: "subagent turn",
    "tool-call": "tool call",
    "subagent-call": "subagent call",
    retrieval: "retrieval",
    inspect: "inspect",
    citation: "citation",
    result: "result",
    error: "error",
  }[event.kind] || event.kind;
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(<App />);
}

export { App, DEFAULT_PROMPT, TOOL_LABELS };
