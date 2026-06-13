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

## Email intake (Gmail)

The backend can poll a Gmail inbox for application bundles submitted by email. PDF attachments are extracted with Claude (Bedrock) and land in a "Pending intake" queue. An operator then accepts (promotes to a reviewable bundle) or rejects each submission. **Send-acknowledgement emails are OFF by default** — the operator gate is the trust boundary, not the inbox.

### OAuth setup (one-time)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. Under **APIs & Services → Credentials**, create an OAuth 2.0 client (type: Desktop app).
3. Download the client-secret JSON. Run the one-off consent flow to mint a token file (scope `https://www.googleapis.com/auth/gmail.modify`):
   ```bash
   pip install google-auth-oauthlib google-api-python-client
   python - <<'PY'
   from google_auth_oauthlib.flow import InstalledAppFlow
   import json, pathlib
   flow = InstalledAppFlow.from_client_secrets_file(
       "client_secret.json",
       scopes=["https://www.googleapis.com/auth/gmail.modify"])
   creds = flow.run_local_server(port=0)
   pathlib.Path("gmail_token.json").write_text(creds.to_json())
   print("Token written to gmail_token.json")
   PY
   ```
4. Store `gmail_token.json` somewhere safe (not in the repo).

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `GRID_GMAIL_INTAKE` | `0` | Set to `1` to enable the poller. |
| `GRID_GMAIL_TOKEN_FILE` | _(empty)_ | Absolute path to the OAuth token JSON. |
| `GRID_GMAIL_QUERY` | `is:unread has:attachment` | Gmail search query for intake messages. |
| `GRID_GMAIL_POLL_SECONDS` | `45` | Polling interval in seconds. |
| `GRID_GMAIL_SEND_ACKS` | `0` | Set to `1` to send acknowledgement emails (off by default). |

Add these to `.env` in the repo root (already in `.gitignore`):

```bash
GRID_GMAIL_INTAKE=1
GRID_GMAIL_TOKEN_FILE=/absolute/path/to/gmail_token.json
```

The poller starts when the FastAPI app starts. Without `GRID_GMAIL_INTAKE=1` and a valid `GRID_GMAIL_TOKEN_FILE`, it logs "disabled" and exits silently — the app starts normally either way.
