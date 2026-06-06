import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./main.jsx";

function ndjsonStream(lines) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const line of lines) {
        controller.enqueue(encoder.encode(`${JSON.stringify(line)}\n`));
      }
      controller.close();
    },
  });
}

describe("Grid Agents UI", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts the subagent payload knob and renders streamed events", async () => {
    const fetchMock = vi.fn(async (url, options) => {
      if (url === "/api/overview") {
        return {
          json: async () => ({
            artifact_dir: "/tmp/grid",
            artifact_revision: "abcdef123456",
            model: "model",
            documents: [{ document_id: "grid/a.txt", title: "A", category: "Code", pages: 1 }],
            tools: [
              { id: "vector", ready: true },
              { id: "pageindex", ready: true },
              { id: "graphrag", ready: false },
              { id: "find", ready: true },
            ],
          }),
        };
      }
      expect(JSON.parse(options.body).enable_subagents).toBe(false);
      return {
        ok: true,
        body: ndjsonStream([
          { type: "trace", entry: { id: 1, kind: "retrieval", title: "Searched find", detail: "Gate 2", metadata: {} } },
          {
            type: "trace",
            entry: {
              id: 2,
              kind: "subagent-call",
              title: "Requested Agent",
              detail: JSON.stringify({ description: "Check Gate 2 evidence" }),
              metadata: { tool_use_id: "subagent-1" },
            },
          },
          {
            type: "trace",
            entry: {
              id: 3,
              kind: "retrieval",
              title: "Searched vector",
              detail: "Gate 2 evidence requirements",
              metadata: { evidence_ids: ["E1"], span_count: 1 },
            },
          },
          {
            type: "trace",
            entry: {
              id: 4,
              kind: "subagent",
              title: "Subagent",
              detail: "Subagent evidence note.",
              metadata: { parent_tool_use_id: "subagent-1" },
            },
          },
          {
            type: "result",
            status: "completed",
            answer: "Gate 2 requires evidence [E1].",
            citations: [
              {
                id: "E1",
                title: "Gate 2 Criteria",
                category: "Connections",
                page: 4,
                artifact_source: "find",
                span_text: "Evidence text",
              },
            ],
            latency_ms: 120,
            enable_subagents: false,
          },
        ]),
      };
    });
    global.fetch = fetchMock;

    render(<App />);
    await screen.findByText("Grid Agents");
    fireEvent.click(screen.getByLabelText(/span-retriever subagents/i));
    fireEvent.click(screen.getByRole("button", { name: /Ask Grid Agents/i }));

    await waitFor(() => expect(screen.getByText("Gate 2 requires evidence [E1].")).toBeTruthy());
    expect(screen.getByText("Searched find")).toBeTruthy();
    expect(screen.getByText("Root Agent Timeline")).toBeTruthy();
    expect(screen.getByText("Subagent Threads")).toBeTruthy();
    expect(screen.getByText("Check Gate 2 evidence")).toBeTruthy();
    expect(screen.getByText("2 turns")).toBeTruthy();
    expect(screen.getByText("Subagent evidence note.")).toBeTruthy();
    expect(screen.getByText(/Evidence text/)).toBeTruthy();
  });

  it("validates empty prompt", async () => {
    global.fetch = vi.fn(async () => ({
      json: async () => ({ documents: [], tools: [], artifact_revision: "" }),
    }));
    render(<App />);
    const textarea = await screen.findByLabelText("Question");
    fireEvent.change(textarea, { target: { value: " " } });
    fireEvent.click(screen.getByRole("button", { name: /Ask Grid Agents/i }));
    expect(screen.getByText("Enter a Grid document question.")).toBeTruthy();
  });
});
