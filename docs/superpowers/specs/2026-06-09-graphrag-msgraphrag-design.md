# GraphRAG (Microsoft GraphRAG) — design

_Date: 2026-06-09 · Status: approved, ready to implement · Repo: aws_agent_core_

## Goal

Make the `graphrag` retrieval method actually work, using **Microsoft GraphRAG**
(the `graphrag` PyPI package), and ship it all the way to **production** — i.e. selectable
alongside `vector` / `pageindex` / `find` in the local console **and** in the deployed
AgentCore runtime.

**Definition of done (functional bar):** GraphRAG builds, runs end-to-end, and returns
sensible **cited spans** (correct document + page) through the test console locally and
through the deployed runtime / EC2 BFF. A quality eval (golden set, lift vs other methods)
is an explicit **follow-up**, not part of this task.

## Current state (starting point)

GraphRAG is already implemented at the code level (~647 lines under
`grid_agent_core/graphrag/`) using Microsoft GraphRAG, but it has **never been built or run**:

- `graphrag_ms_worker.py` builds a `GraphRagConfig` and calls `graphrag.api.build_index`
  (index) and `graphrag.api.local_search` (query); LLM = Anthropic `claude-haiku-4-5`
  (direct API), embeddings = Voyage `voyage-law-2`, vector store = LanceDB.
- `canonical_chunks.py`, `worker_protocol.py`/`worker_lib.py`, `span_resolver.py`,
  `index_meta.py` provide chunking, the subprocess JSON protocol, span→offset mapping,
  and freshness.
- `indexes.py` wires `build_graphrag_index` / `load_graphrag_hits` (method id `graphrag_ms`).
- The `graphrag>=2.7,<4` dependency lives in the **`graphrag` extra** (not installed).
- No index artifacts exist (`graphrag_data/` absent locally and in S3); the method is
  auto-greyed in the UI. The deployed runtime does not include graphrag deps.

## Decisions (from brainstorming)

1. **End-state:** production (build locally → upload to S3 → redeploy the runtime).
2. **Models/provider:** keep as coded — Anthropic-direct + `claude-haiku-4-5` + Voyage
   `voyage-law-2`. Production adds one `ANTHROPIC_API_KEY` secret; GraphRAG LLM calls bypass
   Bedrock (accepted divergence).
3. **Quality bar:** functional only (eyeball verify). Eval is a separate follow-up.
4. **Approach:** fix the existing worker (reuse the scaffold), de-risked by a cheap 1-doc
   smoke build first. Rewrite only the functions that prove incompatible.

## Architecture / data flow (existing, made to work)

- **Build (local, one-time per artifact revision):**
  `grid-build-indexes --methods graphrag` → `build_graphrag_index` → spawn
  `graphrag_ms_worker` subprocess → canonical chunks → `graphrag.api.build_index`
  (text-units → entities/relationships → communities → community reports, Voyage embeddings)
  → parquet + LanceDB under `graphrag_data/graph_index/graphrag_ms/output/` →
  `INDEX_META.json` freshness stamp.
- **Query (runtime):** agent `graphrag_search` tool → `retrieval.search("graphrag", …)` →
  `load_graphrag_hits` → worker → `graphrag.api.local_search` over the parquet tables →
  text-unit contexts → `span_resolver` maps each to `(document_id, start_char, end_char)` →
  `Evidence` in the **same shape** as the other methods, so citations, figure attachment,
  and the UI funnel work unchanged.

## Components touched

- `grid_agent_core/graphrag/graphrag_ms_worker.py` — fix against the installed graphrag
  version (config model fields, `build_index` / `local_search` signatures, output table
  names). Primary risk surface.
- `pyproject.toml` — pin the graphrag version that actually works once verified.
- `grid_agent_core/upload_artifacts.py` + `artifacts.py` — confirm `graphrag_data/` is
  included in the S3 upload **and** pulled by `ensure_artifacts` on the runtime.
- Deploy path (`agentcore/agentcore.json`, `scripts/deploy_grid_agentcore.py`) — add the
  `graphrag` extra to the runtime package, add `ANTHROPIC_API_KEY` via Secrets Manager,
  confirm the worker subprocess can spawn inside the AgentCore container.
- `local_api.py` overview readiness already flips `graphrag` to ready when the output dir
  exists — no change expected.

## Milestones (each gates the next)

1. **Smoke build (cheap):** `uv sync --extra graphrag`; build a 1-doc subset; fix the worker
   until a tiny index builds and one `local_search` query returns ≥1 span locally.
2. **Full local build + verify:** build all 6 docs; run 2–3 representative Grid queries via
   the console with `methods=graphrag` and a mixed run; confirm graphrag spans are cited with
   correct pages. **← functional definition of done.**
3. **S3:** upload `graphrag_data/` to the `grid-agent-core` prefix; confirm `ensure_artifacts`
   downloads it; bump artifact revision if the pipeline requires it.
4. **Production:** repackage the runtime with the graphrag extra + `ANTHROPIC_API_KEY`,
   redeploy via the deploy script, verify a graphrag query end-to-end through the deployed
   runtime and the EC2 BFF.

## Error handling

- Worker subprocess failure → `RuntimeError` with captured stderr (existing); the method
  returns an error and the agent continues with the other methods.
- Missing/stale index → `load_graphrag_hits` raises; UI greys the method (existing).
- Build is idempotent via `INDEX_META.json` freshness.
- Production graceful degradation: if graphrag deps or the Anthropic key are absent, only the
  `graphrag` method errors — `vector`/`pageindex`/`find` keep working.

## Testing (functional, per decision)

- **Smoke:** 1-doc build + one query returns ≥1 span.
- **Local:** `methods=graphrag` run cites spans with correct pages; mixed run shows graphrag
  contributing in the funnel with no errors.
- **Production:** one query through the deployed runtime / EC2 BFF completes with graphrag
  spans present.

## Risks

1. **MS GraphRAG API drift** (main unknown) — mitigated by the cheap smoke build first.
2. **Runtime package size / cold-start** grows (graphrag pulls pandas/lancedb/fnllm).
3. **Subprocess worker must spawn inside the AgentCore container** — verified at milestone 4.
4. **One-time build cost** — low on haiku; runs on MaoXun's keys in `.env`.

## Out of scope (follow-ups)

- Retrieval-quality eval (golden set, GraphRAG lift vs other methods).
- GraphRAG `global_search` / DRIFT modes (local_search only here).
- Routing GraphRAG's LLM through Bedrock.
