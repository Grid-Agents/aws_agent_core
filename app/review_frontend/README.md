# GridReview — Application Review MVP

Operator-facing frontend for reviewing grid interconnection application bundles
with the Grid agent. Transmission / Distribution dashboards, an offline
section-by-section review report (parallel agent runs with cited verdicts), a
span-select co-pilot, and a document-bundle viewer.

## Architecture

```
React + Vite SPA  ──>  FastAPI (grid-local-api, :8000)  ──>  Grid agent
  /api/review/*          grid_agent_core/review_api.py        run_grid_agent_events
                         parses review_seed bundles           (local or deployed AgentCore)
```

The SPA calls the review API on the FastAPI proxy. Dev proxy forwards `/api`,
`/artifacts`, and `/review-pdfs` to `http://127.0.0.1:8000` (override with
`GRID_API_URL`). When `AGENTCORE_RUNTIME_ARN` is set in the backend's `.env`,
reviews run against the deployed AWS indexes; otherwise they run the local agent.

## Run

1. **Seed bundles** (once) — generate the filled application + supporting PDFs:
   ```bash
   cd ../GridAgentCore && uv run python review_seed/generate_seed.py
   ```

2. **Backend** — the review API + PDF host:
   ```bash
   cd ../GridAgentCore
   set -a && source ../../.env && set +a
   uv run grid-local-api --port 8000
   ```

3. **Frontend**:
   ```bash
   npm install
   npm run dev          # http://localhost:5174
   ```

## Agent observability

The deployed AgentCore runtime can cold-start for a minute-plus before its first
byte, which used to look like a hang. Two surfaces make a run legible end-to-end:

- **Agent Console** (docked at the bottom, always mounted) — lists every in-flight
  and recent run with a live phase chip (connecting → waiting → working → done /
  stalled / failed), elapsed timer, a **Reasoning thread** view (thinking, parallel
  searches, evidence inspection, citations — what the agent is doing to which
  section) and a **Backend log** view (the raw connection/heartbeat/event feed).
- **Inline status strip** on each section card / co-pilot panel — shows the same
  phase + elapsed so a single run never reads as frozen, and a genuine silence
  (no signal past ~18 s) is surfaced as "stalled".

The backend emits a `heartbeat` event every ~5 s while waiting on AgentCore
(`grid_agent_core/review_api.py::_with_heartbeat`), so "alive but warming up" is
distinguishable from "crashed".

## Source map

- `src/pages/Dashboard.tsx` — TX/DX queue, project cards + review-progress meters.
- `src/pages/ProjectPage.tsx` — header, tabs (review / co-pilot / documents).
- `src/components/SectionReviewCard.tsx` — per-section review: trace, verdict, citations.
- `src/components/CopilotTab.tsx` — span-select popover + parallel Q&A panels.
- `src/components/AgentConsole.tsx` — global ops console: reasoning thread + backend log.
- `src/components/RunStatusLine.tsx` — inline phase/elapsed/stall strip.
- `src/components/DocumentsTab.tsx` — bundle PDF viewer.
- `src/store.tsx` — review/co-pilot state + run phase/log/activities (kept at app root
  so runs continue across in-app navigation); small concurrency pool for "Review all".
- `src/api.ts`, `src/lib/ndjson.ts` — REST + NDJSON stream client.
