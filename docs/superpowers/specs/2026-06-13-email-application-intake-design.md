# Email application intake (AI extraction) — design

_Date: 2026-06-13 · Status: approved, ready to plan · Repo: aws_agent_core_

## Goal

Let developers submit grid interconnection **application bundles by email** (in addition to
the planned portal upload). An email with PDF attachments arriving at an intake inbox is
turned by an **AI intake-agent** into the same structured submission the review pipeline
already consumes, parked in a **"Pending intake"** queue for an operator to **Accept or
Reject**. On Accept it becomes a normal `applications/{PROJECT_ID}/` bundle and flows into
the existing per-section review untouched.

**Definition of done (functional bar):** a real email sent to the intake inbox appears as a
Pending-intake card within ~1 min; its AI-extracted sections render next to the original
attachments with confidence/flags; Accept renders `00_application_form.pdf` and promotes the
bundle so the existing review runs on it; Reject removes it from the queue. Demonstrated
locally end-to-end against one real Gmail inbox.

## Scope (from brainstorming)

| Decision | Choice |
|---|---|
| Fidelity | **Real working intake (MVP)** — one real inbox, light validation, not hardened for scale/abuse |
| Transport | **Gmail API (polling)** — no DNS/MX/public-endpoint; runs the same on laptop and EC2 BFF |
| Normalization | **AI intake-agent extraction** against the canonical requirements schema |
| Confirm gate | **Review + Accept/Reject** (read-only extracted sections; no inline edit yet) |

Explicit **non-goals** for this MVP (named so they aren't assumed): the portal *upload* path
(separate task), inline editing of extracted fields, sender authentication / allow-listing,
virus scanning, multi-inbox / multi-tenant, push delivery (Gmail `watch` + Pub/Sub), and the
AWS SES transport. Each has a noted upgrade path below.

## Current state (starting point)

- A bundle today is a folder `review_seed/applications/{PROJECT_ID}/` with
  `00_application_form.pdf` (rigid line-anchored layout: `PROJECT ID:`, `SECTION N:`,
  `REQUIREMENT:`, `SUBMITTED:`, `SUPPORTING DOCS:`) plus supporting PDFs.
- `grid_agent_core/review_api.py::parse_submission()` parses that PDF text back into
  `{id, name, applicant, level, conn_type, capacity, status, submitted, sections[], documents[]}`.
- Bundles are **synthetic** — minted by `review_seed/generate_seed.py` from
  `review_seed/seed_data.py`. There is **no ingestion path**; the API reads whatever folders exist.
- `generate_seed.py::render_application_form(project, out)` already renders a submission dict to
  the exact parseable `00_application_form.pdf` layout. **We reuse this for Accept.**
- The operator-defined requirements live in a **canonical catalog** in a *separate* repo:
  `interactive-pages/connection-application-data/{transmission,distribution}.md` — markdown
  tables of categories (`Site & location`, `Land — control`, …) with "what the developer
  submits" + regulatory source, split by connection type (Generation / Demand / Storage /
  Mixed). `seed_data.py` cites these as the field schema.
- Backend is FastAPI (`grid-local-api`, :8000) locally; deployed to an EC2 BFF + AgentCore
  runtime. Frontend is the React/Vite `review_frontend` SPA.

## Architecture / data flow

```
Gmail inbox (e.g. applications@gridagents.com)
  │  ① poller: every ~45s  messages.list q="is:unread has:attachment"  →  messages.get
  │     download PDF attachments + body text  →  label "GridIntake/Ingested" (idempotency)
  ▼
Intake extractor (grid_agent_core/intake.py)
  │  ② infer (level, conn_type) from body + docs
  │  ③ load canonical schema for that type (vendored requirements catalog)
  │  ④ per required category → SUBMITTED answer + mapped supporting doc(s)
  │     + per-field confidence + flags (missing categories, unmapped docs, low-confidence type)
  ▼
Pending submission  review_seed/pending/{INTAKE_ID}/
  │     submission.json (extracted dict + confidence/flags + sender meta) + original *.pdf
  ▼
Portal · "Pending intake" queue (dashboard section + detail view)
  │  ⑤ operator: extracted sections (read-only) next to original PDFs + flags
  │     ├─ Reject → label "GridIntake/Rejected" (+ optional bounce email), archive pending dir
  │     └─ Accept → render_application_form(dict) → 00_application_form.pdf
  │                 move bundle into applications/{PROJECT_ID}/
  ▼
EXISTING review pipeline (parse_submission → per-section review)  — unchanged
```

Key property: **Accept produces the same `00_application_form.pdf` the seed generator
produces**, so every downstream code path (`_load_project`, `parse_submission`, section review,
co-pilot) is identical to today and needs no changes.

## Components

### 1. Gmail poller — `grid_agent_core/intake_gmail.py`
- OAuth user credentials stored as a token file path from env; obtained once via an offline
  OAuth flow. Scopes: `gmail.modify` (read messages + add labels) — and **only when acks are
  enabled** also `gmail.send` (`gmail.modify` does not grant send on its own).
- Runs as an asyncio background task started on FastAPI startup, **gated by env**
  (`GRID_GMAIL_INTAKE=1` + creds present); a no-op otherwise. Structured as a small class so it
  can later be lifted into a standalone `grid-intake-worker` process or the EC2 BFF.
- Poll loop: `messages.list q="is:unread has:attachment"` (optionally narrowed by recipient or
  a subject tag) → for each: `messages.get(format=full)`, walk MIME parts, download PDF
  attachments via `messages.attachments.get`, capture `From`/`Subject`/body text.
- **Idempotency via Gmail labels** (no local cursor DB): on success add `GridIntake/Ingested`
  and mark read; on extractor error add `GridIntake/Failed`; on operator reject add
  `GridIntake/Rejected`. The list query excludes already-labeled messages.
- Backoff + structured logging on auth expiry / API errors; never crashes the API process.

### 2. Intake extractor — `grid_agent_core/intake.py`
- Input: the schema for the inferred `(level, conn_type)`, the attachment texts
  (reuse `review_api._extract_text` / fitz), and the email body.
- **One structured-output call** to Claude on Bedrock (same model as review,
  `us.anthropic.claude-sonnet-4-5`), *not* the retrieval agent — extraction reads the provided
  docs and does not need the regulatory corpus. Forced JSON output (tool/schema-constrained).
- Two-stage prompt within the call (or two calls if cleaner): (a) classify `(level, conn_type)`
  with confidence; (b) for each required category in that schema, produce `submitted` (the
  developer's answer synthesized/quoted from their docs or `""` if absent), `docs` (filenames of
  attachments that support it), and a per-section `confidence` ∈ {high, medium, low}.
- Output = the submission dict (`parse_submission` shape) **plus** an `intake` block:
  `{level_confidence, sections:[{id,confidence}], flags:[...], unmapped_docs:[...], raw_email:{from,subject}}`.
  Flags include: missing required categories, attachments mapped to no section, low type
  confidence, zero-attachment email.
- Robustness: a non-PDF attachment is ignored (flagged); an unreadable PDF is flagged; total
  extraction failure yields a minimal dict with status `extraction_failed` + raw attachment list
  so the operator can still reject from the UI.

### 3. Vendored requirements schema — `review_seed/schema/`
- **Copy** `transmission.md` and `distribution.md` into the backend repo (do not depend on the
  sibling `interactive-pages` path). Add a tiny loader that parses the markdown tables into a
  per-`(level, conn_type)` list of `{category, what_submitted, source}`. Storage = Generation +
  storage-specific rows; Mixed is its own table (per the catalog's own structure).
- A `make`/script note to re-vendor when the catalog changes (low churn; manual is fine for MVP).

### 4. Review API additions — `grid_agent_core/review_api.py`
- `GET  /api/review/intake` — list pending cards (id, sender, subject, inferred type, section
  count, flag count, status, received-at).
- `GET  /api/review/intake/{intake_id}` — detail: extracted sections + confidence/flags +
  attachment filenames (served via the existing PDF host for the viewer).
- `POST /api/review/intake/{intake_id}/accept` — assign `PROJECT_ID`, `render_application_form`
  → `00_application_form.pdf`, move the bundle from `pending/` into `applications/`, return the
  new project id.
- `POST /api/review/intake/{intake_id}/reject` — `{reason?}`; archive the pending dir, label the
  Gmail message rejected, optionally send a bounce.
- Pending bundles live under `review_seed/pending/{INTAKE_ID}/`, distinct from the live queue;
  attachments are PDF-hosted read-only for the viewer.

### 5. Portal — `review_frontend`
- **Dashboard**: a new "Pending intake" section above/beside the TX/DX queues — a list of
  pending cards with sender, inferred type, and a flag badge.
- **Intake detail view**: extracted sections (read-only, with per-section confidence chips and a
  flags panel) on one side; the original attachment PDFs on the other (reuse `DocumentsTab`'s
  viewer). Footer: **Accept** (→ navigates to the new project) and **Reject** (reason modal).
- Heavy reuse of existing components/styles; new state slice in `store.tsx` for the intake queue;
  new client calls in `api.ts`.

## Smaller decisions (defaulted, from brainstorming)

- **Project ID** — auto-generated on Accept as `{TX|DX}-{GEN|DEM|STO|MIX}-{NNN}` (matches
  existing IDs); next sequence number scanned from `applications/`. Name/applicant/capacity come
  from extraction.
- **(level, conn_type)** — AI-inferred, shown with confidence; low confidence is a flag. Not
  operator-overridable in accept/reject-only (if wrong → reject). The editable-draft upgrade
  fixes this.
- **Ack / bounce emails** — implemented but **OFF by default** behind `GRID_GMAIL_SEND_ACKS=0`.
  Auto-sending from the user's inbox is an outward side-effect; opt-in only. When on: an ack on
  successful intake and a bounce-with-reason on reject, via `messages.send`.
- **Extraction failure** — lands as a Pending card in `extraction_failed` state with raw
  attachments; operator rejects. Gmail message labeled `GridIntake/Failed`.

## Security / permissions

- OAuth token covers **one** inbox: `gmail.modify` (read + label), and `gmail.send` added only
  if acks are enabled. Token file path from env, not committed; documented in the run notes.
  Rotate if shared.
- No sender authentication in MVP — **anyone** who emails the inbox creates a pending card. This
  is acceptable because nothing auto-promotes; the operator gate is the trust boundary. Sender
  allow-listing / SPF checks are a named follow-up.
- Outbound email is gated (`GRID_GMAIL_SEND_ACKS`) and off by default.

## Error handling / edge cases

- No PDF attachments → message labeled ingested, skipped (or flagged-empty card if body looks
  like a submission). Non-PDF attachments ignored + flagged.
- Extractor/model error → `extraction_failed` pending card, never blocks the poll loop.
- Gmail auth expiry / quota → log, back off, surface a health line; poller keeps the API alive.
- Duplicate sends (same message re-listed) → prevented by labels.
- Accept collision on `PROJECT_ID` → sequence re-scan picks the next free id.

## Testing

- **Round-trip**: `render_application_form(extracted)` → `parse_submission` loads and matches the
  extracted sections (guards the format contract).
- **Extractor**: fixtures built by *reversing* existing seed bundles — feed a seed bundle's
  supporting docs (+ a plausible cover email) into `intake.py`, assert it reconstructs sane
  sections, maps docs, and flags the deliberately-missing category.
- **Schema loader**: parse `transmission.md`/`distribution.md`, assert category counts per type.
- **Poller**: mocked Gmail client — assert attachments downloaded, labels applied, labeled
  messages skipped on the next poll (idempotency).
- **E2E (manual)**: send a real email to the inbox → card appears → Accept → bundle in
  `applications/` → existing review runs.

## Future / upgrade paths (out of scope now)

- **Editable draft** confirm gate (operator fixes a field before Accept).
- **Sender auth / allow-list**, virus scan, rate limits — hardening toward production.
- **Push delivery** — Gmail `users.watch` → Pub/Sub for instant intake (needs a public endpoint).
- **AWS SES inbound** transport — same extractor + pending model behind it; all-AWS, event-driven.
- **Portal upload** path — shares the extractor + pending queue (upload is just another way
  attachments arrive).

## Rollout / config

- New env: `GRID_GMAIL_INTAKE` (enable poller), `GRID_GMAIL_TOKEN_FILE`, `GRID_GMAIL_QUERY`
  (default `is:unread has:attachment`), `GRID_GMAIL_POLL_SECONDS` (default 45),
  `GRID_GMAIL_SEND_ACKS` (default 0). All unset = feature dormant; zero impact on current demo.
- New deps: `google-api-python-client` + `google-auth-oauthlib` (Gmail). fitz already present.
