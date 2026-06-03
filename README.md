# Grid AgentCore

AWS Bedrock AgentCore application for asking cited questions over Grid documents. The repo keeps the completed `app/SimpleAgentCore/` chatbot baseline and adds `app/GridAgentCore/` for Grid document retrieval, Claude Agent SDK tools/subagents, S3 artifact deployment, and a React trajectory UI.

## What It Does

`GridAgentCore` parses the PDFs in `/Users/maoxunhuang/Desktop/GridAgents/Grid Docs`, writes a text/Markdown corpus and manifest, builds retrieval artifacts, uploads runtime artifacts to S3, and runs a Claude Agent SDK root agent on AgentCore Runtime. The agent can use vector, PageIndex, GraphRAG, exact-find, `inspect_evidence`, `cite_evidence`, and optional `span-retriever` subagents. Responses include a cited answer plus observable events: root-agent text, tool calls, retrieval results, subagent calls, selected citations, latency, metadata, and errors.

The app does not expose hidden model chain-of-thought.

## Design

```text
User / Frontend / CLI
  -> local API or AWS Bedrock AgentCore Runtime
  -> app/GridAgentCore/main.py
  -> Claude Agent SDK root agent
  -> MCP retrieval tools and optional span-retriever subagents
  -> Grid parsed corpus, exact-find, and vector/PageIndex/GraphRAG indexes
  -> Claude Sonnet on Amazon Bedrock
  -> streamed trace events plus cited result
```

## Main Files

- `app/GridAgentCore/main.py` - AgentCore streaming entrypoint.
- `app/GridAgentCore/grid_agent_core/corpus.py` - Grid PDF parsing, text corpus, manifest, page offsets, content hashes.
- `app/GridAgentCore/grid_agent_core/llama_parse_agentic.py` - ParseBench-compatible LlamaParse Agentic parser wrapper.
- `app/GridAgentCore/grid_agent_core/indexes.py` - vector, PageIndex, and GraphRAG index builders over the parsed corpus.
- `app/GridAgentCore/grid_agent_core/retrieval.py` - retrieval repository over parsed Grid text and optional figure metadata.
- `app/GridAgentCore/grid_agent_core/agent.py` - Claude Agent SDK session, retrieval tool responses, citations, `enable_subagents` payload knob.
- `app/GridAgentCore/grid_agent_core/local_api.py` - FastAPI NDJSON proxy for the frontend.
- `app/GridAgentCore/frontend/` - Vite React Grid QA UI.
- `agentcore/agentcore.json` - active AgentCore deployment target for `GridAgentCore`.
- `app/SimpleAgentCore/` - preserved minimal chatbot baseline.

Generated artifacts live under `.grid_artifacts/` by default and are ignored by git.

## Setup

```bash
deactivate 2>/dev/null || true
unset VIRTUAL_ENV
cp .env.example .env
cd app/GridAgentCore
uv sync --extra dev
cd frontend
npm install
cd ../../..
npm install --prefix agentcore/cdk
```

Edit `.env`:

```bash
AWS_REGION=us-west-2
AWS_PROFILE=default
CLAUDE_CODE_USE_BEDROCK=1
ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
GRID_ARTIFACT_DIR=.grid_artifacts
GRID_S3_BUCKET=your-grid-agent-artifact-bucket
GRID_S3_PREFIX=grid-agent-core
LLAMA_CLOUD_API_KEY=your-llamaparse-key-for-agentic-parsing
LLAMAPARSE_MAX_PAGES_PER_JOB=50
LLAMAPARSE_TIMEOUT_SECONDS=600
GRID_PARSE_DOCUMENT_CONCURRENCY=4
GRID_MULTIMODAL_ENRICH=0
GRID_VLM_RENDER_DPI=150
GRID_VLM_CONCURRENCY=4
GRID_VLM_MAX_FIGURE_CANDIDATES_PER_PAGE=4
GRID_VLM_MAX_OUTPUT_TOKENS=4096
GRID_VLM_MAX_RETRIES=3
GRID_VLM_RETRY_BASE_SECONDS=2
ANTHROPIC_API_KEY=your-anthropic-key-for-vlm-and-batch-indexing
```

Use `ANTHROPIC_API_KEY` for post-parse VLM enrichment and local index-time Message Batches. Runtime Claude calls use Bedrock IAM through Claude Agent SDK.

## Parse Grid Documents

All retrieval indexes (vector, PageIndex, GraphRAG, exact-find) operate on parsed Markdown/text spans. The LlamaParse Agentic implementation intentionally matches the `doc-parser-eval` / ParseBench `llamaparse_agentic` pipeline by default: it keeps parser-produced Markdown, including any image references LlamaParse emits, but does not request or save separate image crops.

For native multimodal RAG, add `--multimodal-enrich` after parsing. This is a separate VLM enrichment/materialization stage: the original PDF page is analyzed for candidate figure regions, tables/header/footer/noise candidates are filtered out, each remaining candidate is sent to an Anthropic vision model as a cropped image, and only accepted figure crops are saved as `FigureRecord` artifacts for the target agent. The VLM prompt is intentionally figure-only: ordinary tables are rejected because LlamaParse Agentic already parses them well.

### Figure Enrichment Contract

`--multimodal-enrich` keeps the visual unit small while giving the VLM enough text context to describe Grid engineering figures accurately:

1. **Candidate detection** - The parser first uses any LlamaParse layout entries labeled as figures, charts, diagrams, or images. If layout entries are unavailable, it falls back to local PyMuPDF image/vector geometry. Layout tables, headers, footers, low-confidence entries, dark/blank crops, and text-heavy noise are skipped before the VLM call.
2. **VLM input** - The VLM receives one JPEG image: the cropped candidate figure only. The text prompt also includes the document key, current page number, candidate bbox/source, nearby PDF text blocks that may contain the caption or surrounding explanation, the current page parsed Markdown, and small previous/next page snippets. This gives caption and document context without sending a noisy full-page screenshot.
3. **VLM output** - The VLM must return JSON: `{"material_figure": true|false, "figure_type": "...", "description": "..."}`. `material_figure=false` rejects tables/forms/headers/footers/logos/blank/text crops. `material_figure=true` returns a detailed 6-12 sentence description covering visible labels, topology, axes/units, callouts, legends, and why the figure matters for retrieval.
4. **Artifact output** - Accepted figures are saved as cropped JPEGs under `figures/grid/{document_key}/page-000N-figure-KK.jpg`. Full-page PDF screenshots are not saved as retrieval artifacts. Each manifest `FigureRecord` stores the crop path, hash, content type, page, `figure_crop` category, text span, and page-fraction bbox.
5. **Parsed-output insertion** - The generated block is inserted back into that page's Markdown as `### Figure context - page N figure K` plus a Markdown image link to the crop. If LlamaParse emitted a Markdown image reference, the block is inserted immediately after that reference; otherwise it is appended inside the same page block, not at the end of the document.

### Parsed Corpus

- **`corpus/grid/*.txt`** — one file per document, concatenated parsed Markdown/text with `[Page N]` markers. If LlamaParse emits Markdown image references such as `![...](page_1_image_1_v2.jpg)`, they remain in this text exactly as parser output. With `--multimodal-enrich`, the file also contains `### Figure context - page N figure K` blocks and local Markdown links such as `![Page N figure K](figures/grid/.../page-000N-figure-KK.jpg)`.
- **`manifest.jsonl`** — one record per document with source/corpus hashes, page spans, paths, and optional `figures`. In default ParseBench-compatible LlamaParse mode, `figures` is expected to be empty. With `--multimodal-enrich`, each saved figure crop is recorded with page, detailed description, local path, SHA-256, content type, size, text span, category, and page-fraction bounding box.
- **`figures/grid/**/*.jpg`** — only present when multimodal enrichment is enabled and the VLM accepts a necessary figure crop. Full PDF page screenshots are not saved as retrieval artifacts.

The parsed Markdown is useful for text-only retrieval because the VLM description is searchable text. The saved `FigureRecord` crop lets the target agent attach the relevant visual unit, not a noisy whole-page screenshot, when cited evidence overlaps the figure description.

### LlamaParse Agentic Contract

With `--parser llamaparse-agentic`, the parser matches `doc-parser-eval`'s ParseBench pipeline:

- `tier="agentic"`
- `version="latest"`
- `disable_cache=True`
- `get(..., expand=["items", "text", "metadata", "debug_logs"])`
- no `output_options`
- no `images_content_metadata` expansion
- no local image download/materialization

`--multimodal-enrich` does not change the LlamaParse request. It runs after the ParseBench-compatible parse, using the original PDF pages and direct Anthropic API VLM output to add figure-only descriptions and saved cropped figure artifacts. If LlamaParse layout metadata is present in a payload, the enrichment stage prefers layout entries labeled as figures and skips layout tables/noise. Otherwise it falls back to local PDF image/vector geometry and conservative crop filters.

Parsing is a separate stage. Before parser calls begin, it scans the source PDFs and writes page-count/size metadata to `source_document_metadata.json`. It then writes copied raw PDFs under `raw/`, parsed corpus files under `corpus/grid/*.txt`, parser resume cache files under `parse_resume_cache/`, `manifest.jsonl`, `artifact_revision.txt`, and `parse_metadata.json`:

```bash
set -a
source .env
set +a
cd app/GridAgentCore
uv run grid-parse-documents \
  --source-dir "/Users/maoxunhuang/Desktop/GridAgents/Grid Docs" \
  --artifact-dir ../../.grid_artifacts \
  --parser llamaparse-agentic \
  --multimodal-enrich \
  --force
```

`--parser llamaparse-agentic` requires `LLAMA_CLOUD_API_KEY`. `--multimodal-enrich` requires `ANTHROPIC_API_KEY`; `GRID_VLM_MODEL`, when set, must be an Anthropic API model ID. If `GRID_VLM_MODEL` is unset, the parser translates Bedrock-style `ANTHROPIC_MODEL` values such as `us.anthropic.claude-sonnet-4-5-20250929-v1:0` into the corresponding direct Anthropic model ID. Use `--parser pypdf` for the local no-API fallback.

Before a full LlamaParse run, use the smoke flag to parse only the first few
pages of `02 - Industry Codes/00_The_Full_Grid_Code.pdf` and inspect the
parsed-text preview plus Markdown image-reference count. This defaults to pages `1-8` and writes to
`../../.grid_smoke_artifacts` so it does not overwrite the full corpus artifacts:

```bash
cd app/GridAgentCore
uv run grid-parse-documents \
  --source-dir "/Users/maoxunhuang/Desktop/GridAgents/Grid Docs" \
  --smoke-full-grid-code \
  --smoke-page-range 1-8 \
  --multimodal-enrich \
  --no-resume
```

Parsing shows progress by default. Completed documents are resumable: re-running the command with `--force` rebuilds the manifest but reuses matching parsed text, raw PDF copies, and parser resume cache files. Use `--no-resume` only when you intentionally want to reparse every PDF. LlamaParse agentic jobs are automatically partitioned when a PDF is larger than `LLAMAPARSE_MAX_PAGES_PER_JOB` pages, so a 1102-page PDF is submitted as multiple smaller jobs and merged back with original page numbers. Completed partition payloads are cached under `parse_resume_cache/llamaparse_agentic/grid/*.partition_cache/`. Older `parse/` caches are migrated automatically on the next parse run.

Document parsing runs up to `GRID_PARSE_DOCUMENT_CONCURRENCY` PDFs in parallel by default. When `--multimodal-enrich` is enabled, `GRID_VLM_CONCURRENCY` is a run-wide cap on Anthropic VLM calls over cropped figure candidates, not a per-document multiplier. `GRID_VLM_MAX_FIGURE_CANDIDATES_PER_PAGE` limits how many candidate crops can be sent per page. The post-parse VLM phase shows document/page progress, writes per-page figure-candidate decisions under `parse_resume_cache/llamaparse_agentic/grid/*.visual_cache/`, and preserves page order when aggregating parallel results. This cache includes both saved figure crops and pages where no necessary figure was accepted, so interrupted runs can resume without repeating completed Anthropic VLM calls. Anthropic rate limits/timeouts are retried with exponential backoff controlled by `GRID_VLM_MAX_RETRIES` and `GRID_VLM_RETRY_BASE_SECONDS`. If Anthropic rate-limits the run, reduce `--vlm-concurrency`.

Pressing Ctrl+C cancels queued document/page work and exits the CLI with status `130`. Python cannot gracefully interrupt an already in-flight API request inside a worker thread, so the CLI uses an immediate process exit after flushing the interruption message to avoid leaving background requests running.

Older LlamaParse cache entries that used image extraction or Markdown/image metadata expansions are invalidated once because they do not match the ParseBench-compatible parser contract. Older visual caches are also invalidated when the VLM prompt contract changes, such as the switch to context-aware figure-crop descriptions. After a compatible parse completes, subsequent `--force` runs can resume from the new sidecars as long as the source PDF hash, parsed text, raw PDF copy, raw parse payload, multimodal-enrichment flag, and saved figure hashes still match.

## Retrieval Behavior

Retrieval is text-first. All indexes search against the parsed Markdown/text corpus.

### Step 1 - Text Retrieval

Vector, PageIndex, GraphRAG, and exact-find all return evidence hits as `(start_char, end_char, page)` spans over a document's `.txt` corpus file.

### Step 2 - Evidence Response

The MCP retrieval tools build text evidence blocks with document title, page range, evidence ID, retrieved passage text, and any attached `FigureRecord` entries whose page/span overlaps the evidence.

### Multimodal Note

The default ParseBench-compatible LlamaParse path has no native image content blocks because no local image artifacts are saved. With `--multimodal-enrich`, the VLM figure description is embedded in the parsed Markdown and the saved cropped JPEG is attached to matching evidence. The target agent can then include both searchable visual text and the actual figure image block in the model context.

## Build Grid Indexes

Indexing is the second stage and consumes the parsed corpus from `--artifact-dir`. It does not parse PDFs and does not need `--source-dir`.

Build the vector index:

```bash
cd app/GridAgentCore
uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods vector \
  --vector-provider voyage
```

Use `--vector-provider local` for a deterministic no-API fallback during development.

Index builds show progress by default, cache per-document parts under `indexes/*/parts/`, and skip final indexes that already match the current `artifact_revision.txt`. If a run stops midway, rerun the same command to continue from completed parts. Use `--rebuild-indexes` to rebuild final vector/PageIndex outputs, and `--no-resume` only when you want to ignore cached per-document index parts. The hidden compatibility flag `--force` is treated as `--rebuild-indexes` during indexing.

Build PageIndex. Enable Anthropic direct Message Batches to reduce summary cost:

```bash
uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods pageindex \
  --anthropic-batch
```

GraphRAG uses a local copy of the Microsoft GraphRAG worker under
`grid_agent_core/graphrag/`. Install the optional build-time dependencies in
this project before indexing:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core/app/GridAgentCore
uv sync --extra dev --extra graphrag
uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods graphrag
```

Do not include `find` in index builds. Exact-find is keyword search over the parsed corpus at retrieval time and has no index artifact.

If GraphRAG dependencies or API keys are missing, the script reports the missing
project-local dependency instead of silently skipping it.

## Upload Raw Documents And Artifacts To AWS

Create the S3 bucket once, then upload the ignored local artifacts:

```bash
set -a
source .env
set +a
aws s3 mb "s3://$GRID_S3_BUCKET" --region "$AWS_REGION"
cd app/GridAgentCore
uv run grid-upload-artifacts \
  --artifact-dir ../../.grid_artifacts \
  --bucket "$GRID_S3_BUCKET" \
  --prefix "$GRID_S3_PREFIX"
```

The upload includes copied raw PDFs, `source_document_metadata.json`, `manifest.jsonl`, `artifact_revision.txt`, `parse_metadata.json`, text corpus files, optional `figures/` image artifacts, and index directories. Parser resume caches under `parse_resume_cache/` and legacy `parse/` are intentionally skipped because they are local-only and may contain temporary LlamaParse URLs that are not needed by AgentCore runtime.

## Run Locally

Direct CLI:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a
uv run python local_chat.py \
  --methods vector,pageindex,find \
  "What does Gate 2 readiness require?"
```

Payload shape:

```json
{
  "prompt": "What does Gate 2 readiness require?",
  "methods": ["vector", "pageindex", "graphrag", "find"],
  "allow_sdk_file_tools": false,
  "enable_subagents": true
}
```

`enable_subagents` defaults to `true`; set it to `false` to keep retrieval in the root agent only.

## Run The Frontend

Terminal 1:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a
uv run grid-local-api --port 8000
```

Terminal 2:

```bash
cd app/GridAgentCore/frontend
npm run dev
```

Open `http://127.0.0.1:5173`. The UI posts the same payload, streams NDJSON events from `/api/grid/run`, and displays the answer, citations, root-agent turns, retrieval calls, subagent threads, latency, and errors. When cited evidence has attached figures, the source snippet card also shows the figure IDs and S3/local artifact links.

Set `AGENTCORE_RUNTIME_ARN` in `.env` to make the local API forward `/api/grid/run` to a deployed AgentCore runtime instead of running the local SDK session. The optional request field `runtime_session_id` is passed as AgentCore `runtimeSessionId`; when omitted, the proxy creates one for the request.

## Deploy To AgentCore

`agentcore/agentcore.json` is configured for `app/GridAgentCore/`. Replace `GRID_S3_BUCKET` in that file before deployment, or keep it synchronized with `.env`.

```bash
set -a
source .env
set +a
python3 -m json.tool agentcore/agentcore.json
python3 -m json.tool agentcore/aws-targets.json
agentcore validate
agentcore deploy --dry-run
agentcore deploy
```

Invoke:

```bash
agentcore invoke --payload '{
  "prompt": "Summarize Gate 2 evidence requirements with citations.",
  "methods": ["vector", "pageindex", "find"],
  "enable_subagents": true
}'
```

## Isolation And Scalability

- AgentCore Runtime gives isolated sessions; preserve session IDs for continued conversations.
- The v1 storage design uses S3. Each runtime downloads artifacts into `/tmp/grid-agent-core/artifacts` on first use and verifies the manifest/revision.
- Keep `networkMode` as `PUBLIC` while using Bedrock plus S3. Move to VPC only when private dependencies require it.
- Move from S3 download-on-start to AgentCore mounted filesystems/EFS only if artifact size, cold-start time, or concurrency requires it. AgentCore filesystem mounts require VPC/NFS configuration.
- For higher concurrency, keep retrieval artifacts immutable by revision and upload a new S3 prefix for each rebuild. Deploy/runtime env vars can then point to the new prefix without mutating existing sessions.

## Environment Variables

Runtime:

- `AWS_REGION`
- `CLAUDE_CODE_USE_BEDROCK=1`
- `ANTHROPIC_MODEL`
- `GRID_ARTIFACT_DIR`
- `GRID_S3_BUCKET`
- `GRID_S3_PREFIX`
- `AGENTCORE_RUNTIME_ARN` and `AGENTCORE_RUNTIME_QUALIFIER` for optional local API forwarding to a deployed runtime.

Index-time only:

- `GRID_DOCS_DIR` for the local source PDF folder used by `grid-parse-documents`.
- `GRID_PARSE_PROVIDER` optional default parser: `llamaparse-agentic` or `pypdf`.
- `LLAMA_CLOUD_API_KEY` for `grid-parse-documents --parser llamaparse-agentic`.
- `LLAMAPARSE_MAX_PAGES_PER_JOB` optional page partition size for large LlamaParse PDFs. Defaults to `50`.
- `LLAMAPARSE_TIMEOUT_SECONDS` optional wait timeout for each LlamaParse job. Defaults to `600`.
- `GRID_PARSE_DOCUMENT_CONCURRENCY` controls how many PDFs are parsed in parallel. Defaults to `4`.
- `GRID_MULTIMODAL_ENRICH=1` optionally enables post-parse Anthropic VLM descriptions and saved cropped figure artifacts.
- `GRID_VLM_MODEL` optionally overrides the Anthropic API model used for multimodal enrichment. If unset, Bedrock-style `ANTHROPIC_MODEL` values are translated for direct Anthropic API use.
- `GRID_VLM_RENDER_DPI` controls figure-crop render resolution for enrichment. Defaults to `150`.
- `GRID_VLM_CONCURRENCY` controls the run-wide parallel Anthropic VLM figure-crop call cap. Defaults to `4`.
- `GRID_VLM_MAX_FIGURE_CANDIDATES_PER_PAGE` controls how many candidate figure crops can be sent to the VLM for each parsed page. Defaults to `4`.
- `GRID_VLM_MAX_OUTPUT_TOKENS` caps each VLM figure-description response. Defaults to `4096`; keep this far below the model maximum so non-streaming smoke parses do not trigger long-request streaming requirements.
- `GRID_VLM_MAX_RETRIES` controls extra Anthropic VLM retries after SDK retries. Defaults to `3`.
- `GRID_VLM_RETRY_BASE_SECONDS` controls VLM retry backoff base delay. Defaults to `2`.
- `ANTHROPIC_API_KEY` for Anthropic direct VLM enrichment and Message Batches.
- `GRID_BATCH_MODEL` for batch summary model selection.
- `VOYAGE_API_KEY` for Voyage vector indexing and the local GraphRAG worker embeddings.
- `GRID_GRAPHRAG_MODEL` and `GRID_GRAPHRAG_EMBED_MODEL` to override local GraphRAG worker defaults.

## IAM Permissions

Local/deploy caller:

- AgentCore/CDK deployment permissions.
- CloudFormation, IAM role/policy, S3 asset, and CloudWatch Logs permissions required by the AgentCore CLI.
- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for the selected Claude Sonnet model.
- S3 read/write to `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/*`.

Runtime execution role:

- Bedrock invoke permissions for the configured model.
- `s3:ListBucket` on the artifact bucket with the configured prefix condition.
- `s3:GetObject` on `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/*`.

No local AWS credentials or API keys should be committed.

## Verify

Do not run the full Grid index build unless you intend to pay for and wait on it. Run these checks:

```bash
cd app/GridAgentCore
uv run pytest
python3 -m py_compile main.py local_chat.py grid_agent_core/*.py grid_agent_core/graphrag/*.py

cd frontend
npm test
npm run build

cd ../../SimpleAgentCore
uv run pytest

cd ../..
agentcore validate
```

## SimpleAgentCore Baseline

The minimal chatbot baseline is still available in `app/SimpleAgentCore/` and documented in `docs/simple_agent_core.md`. To deploy the baseline instead of Grid Agents, change `agentcore/agentcore.json` `codeLocation` back to `app/SimpleAgentCore/` and the runtime name back to `SimpleAgentCore`.
