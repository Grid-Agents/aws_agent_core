# Grid AgentCore

AWS Bedrock AgentCore application for asking cited questions over Grid documents. The repo keeps the completed `app/SimpleAgentCore/` chatbot baseline and adds `app/GridAgentCore/` for parsed Grid artifacts, vector/PageIndex/GraphRAG retrieval, Claude Agent SDK tools/subagents, S3 artifact deployment, and a React trajectory UI.

The app exposes observable agent events: root-agent text, tool calls, retrieval results, subagent calls, selected citations, latency, metadata, and errors. It does not expose hidden model chain-of-thought.

## MVP Fast Path

Assumption: you already ran LlamaParse Agentic document parsing with VLM enrichment and the subset artifacts are in `.grid_artifacts/`.

Build the two fastest MVP indexes first:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core/app/GridAgentCore
set -a
source ../../.env
set +a

uv sync --extra build --extra dev

uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods vector,pageindex \
  --vector-provider voyage \
  --chunk-strategy semantic \
  --search-strategy hybrid
```

Upload the parsed corpus, figures, and indexes:

```bash
uv run grid-upload-artifacts \
  --artifact-dir ../../.grid_artifacts \
  --bucket "$GRID_S3_BUCKET" \
  --prefix "$GRID_S3_PREFIX"
```

Deploy and invoke:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core

python3 scripts/deploy_grid_agentcore.py

agentcore invoke \
  --runtime GridAgentCore \
  --stream \
  --prompt "Summarize Gate 2 evidence requirements with citations."
```

The deploy script reads `.env`, verifies local and S3 artifacts, stores
`VOYAGE_API_KEY` in AWS Secrets Manager, updates `agentcore/agentcore.json` with
runtime-safe env vars, runs AgentCore validation and dry-run, deploys, then
attaches S3 read access to the runtime role. Use
`python3 scripts/deploy_grid_agentcore.py --dry-run-only` to check everything
without deploying.

## What The System Does

```text
User / Web UI / CLI
  -> local API or AWS Bedrock AgentCore Runtime
  -> app/GridAgentCore/main.py
  -> Claude Agent SDK root agent and optional span-retriever subagent
  -> vector, PageIndex, GraphRAG, and exact-find retrieval tools
  -> parsed Grid corpus, raw PDFs, figure crops, and index artifacts
  -> Claude Sonnet on Amazon Bedrock
  -> cited answer plus observable trajectory
```

Runtime model calls use Amazon Bedrock through IAM. Parse-time VLM enrichment, Voyage embeddings, and local GraphRAG builds use direct provider APIs from your local machine unless noted.

## Main Components

- `app/GridAgentCore/main.py` - AgentCore streaming entrypoint.
- `app/GridAgentCore/grid_agent_core/agent.py` - Claude Agent SDK tools, subagents, citations, and image blocks.
- `app/GridAgentCore/grid_agent_core/corpus.py` - Grid PDF parsing, text corpus, manifest, page offsets, content hashes.
- `app/GridAgentCore/grid_agent_core/llama_parse_agentic.py` - LlamaParse Agentic parser wrapper.
- `app/GridAgentCore/grid_agent_core/multimodal_enrichment.py` - figure-crop detection, VLM descriptions, and figure artifacts.
- `app/GridAgentCore/grid_agent_core/indexes.py` - vector, official PageIndex, and GraphRAG index builders.
- `app/GridAgentCore/grid_agent_core/rag_compat/` - vendored compatibility layer for sibling vector retrieval plus the official PageIndex adapter.
- `app/GridAgentCore/grid_agent_core/graphrag/` - rlm-eval-style GraphRAG worker protocol, canonical chunks, metadata, and worker.
- `app/GridAgentCore/grid_agent_core/retrieval.py` - retrieval repository and figure attachment logic.
- `app/GridAgentCore/grid_agent_core/upload_artifacts.py` - S3 artifact upload CLI.
- `app/GridAgentCore/grid_agent_core/local_api.py` - FastAPI NDJSON proxy for frontend and deployed runtime.
- `app/GridAgentCore/frontend/` - Vite React Grid QA UI.
- `scripts/deploy_grid_agentcore.py` - deployment helper for GridAgentCore runtime config, secret setup, deploy, and S3 role policy.
- `agentcore/agentcore.json` - active AgentCore deployment target for `GridAgentCore`.
- `agentcore/aws-targets.json` - AWS account/region deployment target.
- `app/SimpleAgentCore/` - preserved minimal chatbot baseline.

Generated artifacts live under `.grid_artifacts/` by default and are ignored by git.

## Setup

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
cp .env.example .env

cd app/GridAgentCore
uv sync --extra build --extra dev

cd frontend
npm install

cd ../../..
npm install --prefix agentcore/cdk
npm install -g @aws/agentcore
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

GRID_DOCS_DIR="/Users/maoxunhuang/Desktop/GridAgents/Grid Docs"
GRID_PARSE_PROVIDER=llamaparse-agentic
GRID_MULTIMODAL_ENRICH=1

LLAMA_CLOUD_API_KEY=your-llamaparse-key
ANTHROPIC_API_KEY=your-anthropic-key-for-vlm-and-graphrag
VOYAGE_API_KEY=your-voyage-key-for-vector-and-graphrag
```

Do not commit `.env`, AWS credentials, or API keys.

## Artifact Preflight

Indexing requires a top-level manifest and revision file. Check the existing subset artifacts:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
test -f .grid_artifacts/manifest.jsonl
test -f .grid_artifacts/artifact_revision.txt
find .grid_artifacts/corpus/grid -maxdepth 1 -name '*.txt' -print
find .grid_artifacts/figures/grid -type f -name '*.jpg' | head
```

If `manifest.jsonl` or `artifact_revision.txt` is missing, regenerate the manifest from the existing subset parse sidecars:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a

uv run grid-parse-documents \
  --source-dir ../../.grid_artifacts/raw \
  --artifact-dir ../../.grid_artifacts \
  --parser llamaparse-agentic \
  --multimodal-enrich \
  --force
```

This command should reuse `.grid_artifacts/parse_resume_cache/.../*.record.json` when sidecars, raw parse payloads, corpus files, raw PDFs, and figure hashes are current. If those files are incomplete or stale, it may call LlamaParse or the VLM again.

The indexer builds indexes only for documents in `manifest.jsonl`. Because your current `.grid_artifacts/` contains a subset, the build/upload/deploy flow above deploys that subset only. For a later full-corpus build, use a separate artifact directory or replace `.grid_artifacts/` with the full parsed corpus before indexing.

## Parse Grid Documents

Skip this section if artifact preflight passes. A full parse from source PDFs:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a

uv run grid-parse-documents \
  --source-dir "$GRID_DOCS_DIR" \
  --artifact-dir ../../.grid_artifacts \
  --parser llamaparse-agentic \
  --multimodal-enrich \
  --force
```

Parse outputs:

- `corpus/grid/*.txt` - parsed Markdown/text with `[Page N]` markers.
- `manifest.jsonl` - one document record per parsed PDF, including page spans and optional figure records.
- `artifact_revision.txt` - content revision used for index freshness.
- `raw/**.pdf` - copied source PDFs.
- `figures/grid/**/*.jpg` - accepted figure crops.
- `parse_resume_cache/` - local parse/VLM resume cache; not uploaded to runtime.

`--multimodal-enrich` keeps LlamaParse Agentic as the text/table parser, then sends only candidate figure crops to an Anthropic vision model. Tables, headers, footers, blank crops, logos, and noisy text crops should be rejected by the VLM filter.

## Index Phase

All index builders consume `.grid_artifacts/manifest.jsonl` and `corpus/grid/*.txt`. They do not parse PDFs.

### Vector Index

Yes, the vector index now uses semantic chunking by default.

The implementation follows the sibling `/Users/maoxunhuang/Desktop/GridAgents/vector_pageindex_rag_eval/` `VectorRAG` logic through `grid_agent_core.rag_compat.vector_rag`. The default CLI settings are:

- `--chunk-strategy semantic`
- `--search-strategy hybrid`
- `--vector-provider voyage`
- `GRID_VECTOR_EMBEDDING_MODEL=voyage-law-2`
- `GRID_VECTOR_RERANKER_ENABLED=1`
- `GRID_VECTOR_RERANKER_MODEL=rerank-2`

Semantic chunking embeds paragraph/window units with the configured embedder, computes adjacent-window distance breakpoints, then packs spans with overlap. The same corpus text, including VLM figure-description blocks, is embedded. Image bytes are not embedded in the vector index.

Build vector only:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a

uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods vector \
  --vector-provider voyage \
  --chunk-strategy semantic \
  --search-strategy hybrid
```

Other vector knobs:

```bash
# Alternatives from vector_pageindex_rag_eval:
--chunk-strategy semantic|hierarchical|recursive|fixed
--search-strategy hybrid|vector
--vector-provider voyage|sentence_transformers
```

Use `sentence_transformers` only for local/offline experimentation after installing the relevant models and packages. The MVP path is Voyage.

### PageIndex

The `pageindex` method uses the sibling `/Users/maoxunhuang/Desktop/GridAgents/vector_pageindex_rag_eval/` `pageindex_official` implementation through `grid_agent_core.rag_compat.official_pageindex`. It auto-loads or clones VectifyAI's official self-hosted PageIndex repo, converts Grid text into Markdown virtual-page headings, calls the upstream Markdown tree builder, and maps returned nodes back to original Grid character offsets.

Build PageIndex:

```bash
uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods pageindex
```

PageIndex builds offset-preserving Markdown virtual pages, constructs the official PageIndex tree, optionally asks an LLM for PageIndex summaries/descriptions, and queries by selecting documents then relevant tree nodes. If `ANTHROPIC_API_KEY` is set, the compatibility LLM uses Anthropic direct API. Otherwise it uses the configured Bedrock Claude model through `bedrock-runtime`.

For a cheaper smoke build:

```bash
GRID_PAGEINDEX_BUILD_WITH_LLM=0 uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods pageindex
```

`--anthropic-batch` is intentionally unsupported for this official PageIndex adapter. Build without that flag.

### GraphRAG

GraphRAG follows the rlm-eval shape:

- canonical sentence-packed chunks with `CHUNKER_SIGNATURE=canonical_v1__sentence_pack`
- `corpus.json` plus `canonical_chunks.json`
- a worker protocol for build/query requests
- freshness checks through `INDEX_META.json`
- query-time text-unit span recovery back to corpus offsets

The worker is adapted for the current `graphrag` Python API in this project, but the retrieval contract follows the rlm-eval worker/span-resolution flow.

Install GraphRAG dependencies and build:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core/app/GridAgentCore
set -a
source ../../.env
set +a

uv sync --extra build --extra dev --extra graphrag

uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods graphrag
```

GraphRAG is slower and more dependency-heavy than vector/PageIndex. It requires `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` for the local worker. The current runtime GraphRAG retrieval path also invokes the worker at query time, so only enable the `graphrag` retrieval method in AgentCore after the deployed package and runtime environment include GraphRAG dependencies and required API keys. For the fastest MVP, deploy `vector,pageindex,find` first.

### One Command For All Indexes

```bash
uv sync --extra build --extra dev --extra graphrag

uv run grid-build-indexes \
  --artifact-dir ../../.grid_artifacts \
  --methods vector,pageindex,graphrag \
  --vector-provider voyage \
  --chunk-strategy semantic \
  --search-strategy hybrid
```

Do not include `find` in index builds. Exact find searches the parsed corpus directly at retrieval time and has no index artifact.

### Resume And Rebuild

- Re-run the same command after an interruption; VectorRAG and PageIndex reuse cache files under `indexes/*/cache/`.
- Use `--rebuild-indexes` to rebuild vector/PageIndex outputs.
- Use `--rebuild-graphrag` to rebuild GraphRAG output.
- Use `--no-resume` to ignore VectorRAG/PageIndex cache files.
- The hidden compatibility flag `--force` is treated as `--rebuild-indexes` by the index CLI.

### Verify Index Artifacts

```bash
test -f ../../.grid_artifacts/indexes/vector/index.json
test -f ../../.grid_artifacts/indexes/vector/config.json
test -f ../../.grid_artifacts/indexes/pageindex/index.json
test -f ../../.grid_artifacts/indexes/pageindex/config.json
test -d ../../.grid_artifacts/graphrag_data/graph_index/graphrag_ms/output
```

For a first deployed MVP, vector and PageIndex are enough. Add GraphRAG after the output directory exists and runtime dependencies are configured.

## Figure And Image Workflow

### Parse Time

VLM enrichment creates a `FigureRecord` only for accepted material figures:

1. Candidate detection prefers LlamaParse layout entries labeled as figure, image, chart, or diagram. If layout entries are unavailable, it falls back to local PDF image/vector geometry.
2. The VLM receives the cropped candidate image plus nearby text, page Markdown, document key, page number, and small previous/next page snippets.
3. Accepted crops are saved under `figures/grid/{document_key}/page-000N-figure-KK.jpg`.
4. A `### Figure context - page N figure K` block is inserted into the parsed page Markdown with a Markdown image link and detailed text description.
5. The manifest records figure page, image path, hash, content type, byte size, page-fraction bbox, and text span.

Full-page screenshots are not saved as retrieval artifacts. Ordinary tables are expected to be represented by LlamaParse text/Markdown, not by figure VLM enrichment.

### Index Time

Indexes are text-first:

- Vector embeds semantic chunks of parsed corpus text. If a chunk contains a figure-context block, the figure description and Markdown image path are part of the embedded text.
- PageIndex indexes virtual page/tree node text. If a virtual page contains a figure-context block, the node summary and retrieval span can include that description.
- GraphRAG builds text units, entities, relationships, and communities from parsed corpus text. Figure descriptions can influence text units/entities, but image bytes are not stored in the graph.

The actual image crop is linked after retrieval through the manifest. Index nodes store or recover text spans; they do not store image bytes.

### Retrieval Time

Each retrieval hit becomes an `Evidence` object with document title, page, text span, score, method, and optional figure metadata.

The figure match is based on character offsets in the parsed corpus text:

- Each retrieval hit has `start_char` and `end_char` offsets for the returned text span.
- Each accepted figure has a `FigureRecord` in the manifest. Its `start_char` and `end_char` normally cover the inserted `### Figure context - page N figure K` block, including the Markdown image link and VLM description.
- A hit "overlaps" a figure when the two character ranges intersect: the hit starts before the figure block ends, and the figure block starts before the hit ends. For example, a retrieval span from character 10,000 to 10,900 overlaps a figure block from 10,400 to 10,750, so that evidence attaches the figure crop.

If there is no direct text-span overlap, the retrieval layer falls back to figures on the same page. This covers cases where the retriever returns nearby page text but not the exact figure-context block.

If neither span overlap nor same-page fallback finds a `FigureRecord`, the evidence is returned as text-only. The agent still receives the retrieved text chunk, title, page, score, and citation metadata, but it does not receive an image block.

When a figure is attached:

- The tool response includes the retrieved text, figure ID, VLM description, local artifact path, and S3 URI when configured.
- `agent.py` loads the local crop from the runtime artifact directory and sends up to `MAX_TOOL_IMAGES = 4` image blocks to Claude Agent SDK, capped at `MAX_TOOL_IMAGE_BYTES = 4_000_000` per image.
- In AgentCore, the local crop exists because the runtime downloads S3 artifacts into `/tmp/grid-agent-core/artifacts` on first use.
- The frontend displays cited source snippets and figure IDs/links when evidence includes figures.

So the workflow is: figure crop -> VLM description inserted into text -> text is indexed -> retrieval returns a text span -> character-span overlap, or same-page fallback, resolves the actual image from the manifest -> the agent receives both the description text and the image crop. If the parsed text contains only a raw Markdown image reference and no `FigureRecord`, retrieval can still return the surrounding text, but no actual image block is attached because there is no manifest record that maps that text back to a crop file.

## Upload Artifacts To AWS

Create the bucket once if it does not exist:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
set -a
source .env
set +a

aws s3 mb "s3://$GRID_S3_BUCKET" --region "$AWS_REGION"
```

Upload runtime artifacts:

```bash
cd app/GridAgentCore

uv run grid-upload-artifacts \
  --artifact-dir ../../.grid_artifacts \
  --bucket "$GRID_S3_BUCKET" \
  --prefix "$GRID_S3_PREFIX"
```

The upload includes raw PDFs, source metadata, manifest, artifact revision, parse metadata, corpus text, figure images, and index directories. It intentionally skips `parse_resume_cache/` and legacy `parse/` caches.

Verify:

```bash
aws s3 ls "s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/manifest.jsonl"
aws s3 ls "s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/indexes/vector/index.json"
aws s3 ls "s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/indexes/pageindex/index.json"
aws s3 ls "s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/figures/" --recursive | head
```

If you built GraphRAG:

```bash
aws s3 ls "s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/graphrag_data/graph_index/graphrag_ms/output/" --recursive | head
```

## Deploy To AgentCore Runtime

Use the deployment helper as the primary path:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
python3 scripts/deploy_grid_agentcore.py
```

The script performs the deploy preflight and runtime wiring:

- Reads `.env` and requires `AWS_REGION`, AWS credentials, `ANTHROPIC_MODEL`, `GRID_S3_BUCKET`, `GRID_S3_PREFIX`, and `VOYAGE_API_KEY`.
- Verifies local parsed artifacts and vector/PageIndex indexes under `.grid_artifacts/`.
- Creates or updates the Secrets Manager secret `grid-agent-core/voyage-api-key`.
- Updates `agentcore/agentcore.json` so runtime env vars match `.env`.
- Sets `GRID_ARTIFACT_DIR=/tmp/grid-agent-core/artifacts` for the remote AgentCore Linux runtime.
- Sets `VOYAGE_API_KEY={{resolve:secretsmanager:grid-agent-core/voyage-api-key}}` so the plaintext key is not written to the repo.
- Verifies required objects exist under `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX`.
- Runs `agentcore validate`, `agentcore deploy --dry-run`, `agentcore deploy -y`, and `agentcore status`.
- Attaches `s3:ListBucket` and `s3:GetObject` access for the artifact prefix to the deployed GridAgentCore runtime role.
- Prints the frontend commands for testing the deployed runtime through the local API proxy.

To run the same checks without deploying:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
python3 scripts/deploy_grid_agentcore.py --dry-run-only
```

The installed AgentCore CLI in this workspace exposes `agentcore deploy --dry-run`.
Some AWS docs and CLI versions use `--plan` for preview, so check
`agentcore deploy --help` if your CLI differs.

Manual preflight, if you want to inspect the same inputs:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
set -a
source .env
set +a

aws sts get-caller-identity
python3 -m json.tool agentcore/agentcore.json >/dev/null
python3 -m json.tool agentcore/aws-targets.json >/dev/null
agentcore validate
agentcore deploy --dry-run
```

Also verify `agentcore/aws-targets.json` uses the AWS account and region where the selected Bedrock Claude model is available.

If CDK has not been bootstrapped in the target account/region:

```bash
cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core
set -a
source .env
set +a

npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/$AWS_REGION"
```

After deployment, the script attaches the runtime S3 read policy automatically. If you deploy manually, attach the equivalent policy yourself:

```bash
ROLE_ARN=$(jq -r '.targets.default.resources.runtimes.GridAgentCore.roleArn' agentcore/.cli/deployed-state.json)
ROLE_NAME="${ROLE_ARN##*/}"

cat > /tmp/grid-agent-artifacts-read-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::$GRID_S3_BUCKET",
      "Condition": {"StringLike": {"s3:prefix": ["$GRID_S3_PREFIX", "$GRID_S3_PREFIX/*"]}}
    },
    {
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$GRID_S3_BUCKET/$GRID_S3_PREFIX/*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name GridAgentArtifactsRead \
  --policy-document file:///tmp/grid-agent-artifacts-read-policy.json
```

## Invoke And Test Deployed Runtime

CLI payload:

```bash
agentcore invoke \
  --runtime GridAgentCore \
  --stream \
  --prompt "What does Gate 2 readiness require? Cite sources."
```

Boto3 payload:

```bash
python3 - <<'PY'
import json
import os
import uuid

import boto3

payload = {
    "prompt": "What does Gate 2 readiness require? Cite sources.",
    "methods": ["vector", "pageindex", "find"],
    "enable_subagents": True,
    "allow_sdk_file_tools": False,
}

client = boto3.client("bedrock-agentcore", region_name=os.environ["AWS_REGION"])
response = client.invoke_agent_runtime(
    agentRuntimeArn=os.environ["AGENTCORE_RUNTIME_ARN"],
    runtimeSessionId=str(uuid.uuid4()),
    payload=json.dumps(payload).encode("utf-8"),
    contentType="application/json",
    accept="application/json",
    qualifier=os.getenv("AGENTCORE_RUNTIME_QUALIFIER") or "DEFAULT",
)

body = response.get("response", [])
if hasattr(body, "iter_lines"):
    chunks = body.iter_lines()
else:
    chunks = body

for chunk in chunks:
    if chunk:
        print(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)
PY
```

Set `AGENTCORE_RUNTIME_ARN` in `.env` to make the local FastAPI proxy forward frontend requests to the deployed runtime.

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

`enable_subagents` defaults to `true`. Use `--disable-subagents` in `local_chat.py` to keep retrieval in the root agent only.

## Run The Frontend

Terminal 1:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a
export AGENTCORE_RUNTIME_ARN=$(jq -r '.targets.default.resources.runtimes.GridAgentCore.runtimeArn' ../../agentcore/.cli/deployed-state.json)
export AGENTCORE_RUNTIME_QUALIFIER=DEFAULT
uv run grid-local-api --port 8000
```

Terminal 2:

```bash
cd app/GridAgentCore/frontend
npm run dev
```

Open `http://127.0.0.1:5173`.

The local API forwards `/api/grid/run` to the deployed AgentCore runtime when
`AGENTCORE_RUNTIME_ARN` is set. The UI posts the same payload, streams NDJSON
events, and displays the answer, citations, root-agent turns, retrieval calls,
separate subagent threads, latency, and errors. Each trajectory turn is
expandable; root-agent and subagent-owned turns are labeled separately. When
cited evidence has attached figures, the source snippet card shows figure IDs
and S3/local artifact links.

### How The Frontend Connects To Deployed AgentCore

The React frontend does not call AWS directly. It talks to the local FastAPI
proxy in `grid_agent_core/local_api.py`.

```text
Browser frontend
  -> POST /api/grid/run on local FastAPI
  -> boto3 bedrock-agentcore.invoke_agent_runtime
  -> deployed GridAgentCore runtime
  -> streamed NDJSON trace/result events
  -> frontend trajectory, citations, and answer
```

The switch between local execution and deployed execution is controlled by
`AGENTCORE_RUNTIME_ARN`:

- If `AGENTCORE_RUNTIME_ARN` is set, `/api/grid/run` forwards the request to the
  deployed AgentCore runtime.
- If `AGENTCORE_RUNTIME_ARN` is not set, `/api/grid/run` runs the local Python
  agent process against local/S3-backed artifacts.

For deployed testing, start the proxy with:

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a
export AGENTCORE_RUNTIME_ARN=$(jq -r '.targets.default.resources.runtimes.GridAgentCore.runtimeArn' ../../agentcore/.cli/deployed-state.json)
export AGENTCORE_RUNTIME_QUALIFIER=DEFAULT
uv run grid-local-api --port 8000
```

The local proxy requires AWS credentials with
`bedrock-agentcore:InvokeAgentRuntime`. The browser does not need AWS
credentials.

### Terms Used In This Flow

- **AgentCore** - AWS Bedrock AgentCore, the AWS service hosting and invoking
  this deployed agent application.
- **Runtime** - the deployed AgentCore application instance. For this project,
  the runtime runs `app/GridAgentCore/main.py`, which starts the Grid agent and
  streams events back to the caller.
- **Runtime ARN** - the AWS identifier for the deployed runtime. The local proxy
  reads it from `AGENTCORE_RUNTIME_ARN` so it knows which deployed agent to
  invoke.
- **Qualifier** - the deployed runtime version/alias to invoke. This project
  uses `AGENTCORE_RUNTIME_QUALIFIER=DEFAULT` unless a different AgentCore
  qualifier is created.
- **boto3** - the official AWS SDK for Python. `grid-local-api` uses boto3 to
  call `bedrock-agentcore.invoke_agent_runtime` from your local machine.
- **FastAPI proxy / local API** - the local Python server started by
  `uv run grid-local-api --port 8000`. It gives the browser a simple HTTP API
  and hides AWS credentials from frontend JavaScript.
- **Vite frontend** - the local React development server started by
  `npm run dev`. It serves the browser UI at `http://127.0.0.1:5173`.
- **NDJSON** - newline-delimited JSON. The server sends one JSON object per
  line, so the frontend can render events as they arrive instead of waiting for
  one large final JSON response.
- **Trace event** - an intermediate streamed event with observable agent
  activity such as a root-agent turn, tool call, retrieval result, subagent
  call, citation selection, or error.
- **Result event** - the final streamed event for a run. It includes status,
  answer, citations, full trajectory, latency, model, artifact revision, and
  errors.
- **Trajectory** - the visible sequence of observable trace events. It is not
  hidden model chain-of-thought.
- **Subagent thread** - a grouped set of events created after the root agent
  delegates a retrieval task to the `span-retriever` subagent.
- **Artifact** - a parsed document, text corpus, figure crop, manifest, or index
  file used by retrieval.
- **Index** - a retrieval data structure built from Grid documents, such as the
  vector index, PageIndex index, GraphRAG index, or exact-find text corpus.
- **S3 artifact prefix** - the S3 location configured by `GRID_S3_BUCKET` and
  `GRID_S3_PREFIX` where deployed runtimes download Grid artifacts.
- **AWS credentials** - local IAM credentials from `.env` or your AWS profile.
  They are required by the local proxy and AWS CLI, but should never be exposed
  to frontend browser code.

### Connect Another Frontend

Build another frontend by using the same local/API-server contract. The frontend
should call:

```http
POST http://127.0.0.1:8000/api/grid/run
Content-Type: application/json
```

Request body:

```json
{
  "prompt": "What does Gate 2 readiness require?",
  "methods": ["vector", "pageindex", "find"],
  "allow_sdk_file_tools": false,
  "enable_subagents": true,
  "runtime_session_id": "optional-stable-session-id"
}
```

The response is `application/x-ndjson`. Read it as a stream and split on
newlines. Each line is one JSON object:

```json
{"type":"trace","entry":{"id":1,"kind":"user","title":"Grid question","detail":"...","metadata":{}}}
{"type":"trace","entry":{"id":2,"kind":"tool-call","title":"Requested mcp__grid_retrieval__vector_search","detail":"...","metadata":{"tool_use_id":"..."}}}
{"type":"result","status":"completed","answer":"...","citations":[],"trajectory":[],"latency_ms":1234}
```

Important event fields:

- `trace.entry.kind` tells the UI stage: `user`, `agent`, `subagent-call`,
  `subagent`, `tool-call`, `retrieval`, `inspect`, `citation`, `result`, or
  `error`.
- `trace.entry.detail` is the expandable detail text or JSON string.
- `trace.entry.metadata.tool_use_id` identifies a subagent/tool call.
- `trace.entry.metadata.parent_tool_use_id` links explicit subagent child turns
  to a root `subagent-call`.
- Some deployed SDK streams omit `parent_tool_use_id` on subagent retrieval
  tool events. The current React UI groups retrieval/tool/inspect events after a
  `subagent-call` and before the next root-agent text turn as subagent-managed
  activity.
- `result.answer` is the final cited answer.
- `result.citations` are the source snippets to show beside the answer.
- `result.trajectory` is the final full trajectory copy.

Do not label this as hidden model chain-of-thought. The stream exposes
observable agent events: user prompt, root-agent text, subagent calls, tool
requests, retrieval results, citations, latency, and errors.

For a browser app hosted somewhere other than `127.0.0.1:5173` or
`localhost:5173`, add that origin to the CORS allow list in
`grid_agent_core/local_api.py`.

## Test Console (single page, no build)

`grid-local-api` also serves a self-contained test console — a single static page at `app/GridAgentCore/test_ui/index.html`. No `npm` build is required: just start the API and open the page.

```bash
cd app/GridAgentCore
set -a
source ../../.env
set +a
uv run grid-local-api --port 8000
```

Open **`http://127.0.0.1:8000/ui/`** (the root `/` also redirects there).

It streams the same NDJSON events as the React UI, plus:

- **Live / Retrieval Map / Answer / Trajectory** tabs.
- **Run history** — every completed run is auto-saved to S3 under `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/runs/` (full record at `runs/<id>.json`, summary list at `runs/index.json`, capped at 200) and is reloadable from the **Saved runs** dropdown. Because it is S3-backed, history is durable and shared across machines.
- **View by method** — split the Retrieval Map by retrieval method: see all methods at once, or isolate one of `vector` / `pageindex` / `find`.

`graphrag` is auto-disabled in the method picker unless its index is present. Cited figure crops are served over HTTP from `/artifacts/`.

## How The Agent Works Internally

1. `main.py` receives a JSON payload from AgentCore Runtime.
2. `GridAgentSession` normalizes requested methods and ensures artifacts exist locally.
3. If local artifacts are missing, `ensure_artifacts()` downloads from `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX`.
4. Claude Agent SDK starts a root agent with MCP tools for each enabled retrieval method.
5. Retrieval tools return citation-ready evidence IDs and optional figure image blocks.
6. Optional `span-retriever` subagents can independently search and report candidate evidence.
7. The root agent calls `cite_evidence` before finalizing.
8. The app streams trace events and a final result with answer, citations, evidence, trajectory, model, artifact revision, methods, latency, and errors.

## Isolation And Scalability

- AgentCore Runtime provides isolated sessions. Preserve `runtimeSessionId` for multi-turn continuity; use a new session ID for independent questions.
- This MVP uses immutable S3 artifact prefixes. Rebuild indexes into a new prefix for safer production updates, then redeploy or update runtime env vars to point at the new prefix.
- Runtime artifact download is lazy: the first request downloads artifacts to `/tmp/grid-agent-core/artifacts`. Larger artifacts increase cold-start latency.
- Keep `networkMode` as `PUBLIC` while the runtime only needs Bedrock and S3 for vector/PageIndex/find.
- Move to VPC only for private dependencies.
- Move from S3 download-on-start to mounted filesystems/EFS only if artifact size, cold-start time, or concurrent download pressure requires it.
- Keep runtime IAM read-only for artifacts. Build and upload permissions should stay with local/deployment users, not the runtime role.

## Environment Variables

Runtime:

- `AWS_REGION`
- `CLAUDE_CODE_USE_BEDROCK=1`
- `ANTHROPIC_MODEL`
- `GRID_ARTIFACT_DIR` - local path for local runs; `/tmp/grid-agent-core/artifacts` in deployed AgentCore Runtime.
- `GRID_S3_BUCKET`
- `GRID_S3_PREFIX`
- `VOYAGE_API_KEY` - required at runtime for the current Voyage-backed vector index; `scripts/deploy_grid_agentcore.py` stores it in Secrets Manager and writes a dynamic reference to `agentcore/agentcore.json`.
- `AGENTCORE_RUNTIME_ARN` and `AGENTCORE_RUNTIME_QUALIFIER` for optional local API forwarding.

Vector/PageIndex index-time:

- `VOYAGE_API_KEY`
- `GRID_VECTOR_EMBEDDING_MODEL`
- `GRID_VECTOR_RERANKER_ENABLED`
- `GRID_VECTOR_RERANKER_MODEL`
- `GRID_VECTOR_CHUNK_SIZE`
- `GRID_VECTOR_CHUNK_OVERLAP`
- `GRID_VECTOR_SEMANTIC_BREAK_PERCENTILE`
- `GRID_VECTOR_SEMANTIC_WINDOW_SIZE`
- `GRID_VECTOR_SEMANTIC_MIN_CHUNK_SIZE`
- `GRID_PAGEINDEX_REPO_URL`
- `GRID_PAGEINDEX_REPO_REF`
- `GRID_PAGEINDEX_REPO_PATH`
- `GRID_PAGEINDEX_AUTO_CLONE_REPO`
- `GRID_PAGEINDEX_BUILD_WITH_LLM`
- `GRID_PAGEINDEX_*` budget and selection controls

Parse/figure index-time:

- `GRID_DOCS_DIR`
- `GRID_PARSE_PROVIDER`
- `LLAMA_CLOUD_API_KEY`
- `LLAMAPARSE_MAX_PAGES_PER_JOB`
- `LLAMAPARSE_TIMEOUT_SECONDS`
- `GRID_PARSE_DOCUMENT_CONCURRENCY`
- `GRID_MULTIMODAL_ENRICH`
- `GRID_VLM_MODEL`
- `GRID_VLM_RENDER_DPI`
- `GRID_VLM_CONCURRENCY`
- `GRID_VLM_MAX_FIGURE_CANDIDATES_PER_PAGE`
- `GRID_VLM_MAX_OUTPUT_TOKENS`
- `GRID_VLM_MAX_RETRIES`
- `GRID_VLM_RETRY_BASE_SECONDS`
- `ANTHROPIC_API_KEY`

GraphRAG:

- `ANTHROPIC_API_KEY`
- `VOYAGE_API_KEY`
- `GRID_GRAPHRAG_MODEL`
- `GRID_GRAPHRAG_EMBED_MODEL`
- `GRID_GRAPHRAG_QUERY_TIMEOUT_SECONDS`

## IAM Permissions

Local/deploy caller:

- AgentCore/CDK deployment permissions.
- CloudFormation, IAM role/policy, S3 asset, and CloudWatch Logs permissions required by the AgentCore CLI.
- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for the selected Claude Sonnet model.
- S3 read/write to `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/*`.
- `bedrock-agentcore:InvokeAgentRuntime` for deployed runtime testing.

Runtime execution role:

- Bedrock invoke permissions for the configured model.
- `s3:ListBucket` on the artifact bucket with the configured prefix condition.
- `s3:GetObject` on `s3://$GRID_S3_BUCKET/$GRID_S3_PREFIX/*`.
- Secrets Manager dynamic reference resolution for the deployed `VOYAGE_API_KEY` value is handled by CloudFormation during deployment.

## Verification

Do not run full Grid index builds unless you intend to pay for and wait on them. For code and frontend checks:

```bash
cd app/GridAgentCore
uv run pytest
python3 -m py_compile main.py local_chat.py grid_agent_core/*.py grid_agent_core/graphrag/*.py grid_agent_core/rag_compat/*.py

cd frontend
npm test
npm run build

cd ../../SimpleAgentCore
uv run pytest

cd ../..
agentcore validate
```

## AWS References

- AgentCore CLI setup, deploy, invoke, and Boto3 payload shape: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html
- AgentCore Runtime invocation and streaming responses: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html
- AgentCore CLI command reference: https://aws.github.io/bedrock-agentcore-starter-toolkit/api-reference/cli.html

## SimpleAgentCore Baseline

The minimal chatbot baseline is still available in `app/SimpleAgentCore/` and documented in `docs/simple_agent_core.md`. To deploy the baseline instead of Grid Agents, change `agentcore/agentcore.json` `codeLocation` back to `app/SimpleAgentCore/` and the runtime name back to `SimpleAgentCore`.
