# grid_agents.md

## Purpose

Turn this project from the completed
Simple AgentCore chatbot into a Grid document agent deployed on AWS Bedrock
AgentCore Runtime. (Make a new folder under "app/" and do not delete the baseline "app/SimpleAgentCore/")

The target is a Claude Agent SDK agent similar to
`/Users/maoxunhuang/Desktop/GridAgents/claude_agent`, but adapted to the raw
Grid documents in `/Users/maoxunhuang/Desktop/GridAgents/Grid Docs` and
packaged with infrastructure/configuration for AWS AgentCore.

## Current State

- The simple chatbot AgentCore demo is complete.
- `docs/simple_agent_core.md` remains the baseline reference.
- `app/GridAgentCore/` now contains the Grid document agent runtime,
  corpus/index CLIs, local API, and frontend.
- The local API streams local Grid session events by default and forwards to
  deployed AgentCore when `AGENTCORE_RUNTIME_ARN` is configured.
- `README.md` documents setup, local runs, index builds, S3 upload, deployment,
  AgentCore isolation/scaling, invocation, and permissions.
- The sibling `claude_agent` project is the reference for agentic search,
  vector retrieval, PageIndex retrieval, GraphRAG retrieval, Claude Agent SDK
  tools, subagents, and trajectory UI behavior. ColiVara adds the hosted visual
  retrieval path for page-image search. You can copy and adapt useful local code
  directly from the sibling project when it applies.

## Interpretation

- The local `Grid Docs` folder is the source corpus during development.
- AWS-hosted raw documents and index artifacts are the runtime source after
  deployment.
- Documents are parsed before indexing; indexes are built before deployment.
  The AgentCore runtime should query existing artifacts instead of reparsing or
  rebuilding expensive indexes at startup.
- Start with the simplest deployable storage design: S3 for raw documents,
  manifests, and index artifacts. Move to EFS, OpenSearch Serverless, Neptune,
  or another managed store only if measured index size, latency, or concurrency
  requires it.
- "Reasoning trajectory" means observable SDK messages, tool calls, retrieval
  events, subagent calls, citations, latency, cost, and errors. Do not expose or
  claim hidden model chain-of-thought.

## Target Architecture

```text
User
  -> Frontend web app
  -> Agent API / AgentCore invocation endpoint
  -> AWS Bedrock AgentCore Runtime
  -> Python app entrypoint
  -> Claude Agent SDK root agent
  -> retrieval tools and Claude Agent SDK enabled tools and subagents
  -> Grid raw documents, vector/PageIndex/GraphRAG indexes, and ColiVara visual index
  -> Claude Sonnet on Amazon Bedrock
  -> cited answer plus observable trajectory
```

## Required Capabilities

### Corpus and Indexes
- Index all files under `/Users/maoxunhuang/Desktop/GridAgents/Grid Docs`.
- Preserve document category, filename, page metadata, content hash, and source
  path in a manifest.
- Before parsing begins, scan source PDFs and write `source_document_metadata.json`
  with page counts, file sizes, relative paths, and source hashes.
- Parse PDFs into the corpus first. Use `llamaparse-agentic` for image-heavy
  documents and `pypdf` only as the local no-API fallback.
- When multimodal enrichment is enabled, keep LlamaParse Agentic as the source
  of truth for tables and text. Send only candidate figure crops to the VLM,
  reject tables/header/footer/dark/noise crops, inject detailed figure
  descriptions into the parsed page text, and save only cropped figures under
  `figures/grid/`.
- Prefer LlamaParse layout entries labeled as figures when present; otherwise
  fall back to local PDF image/vector geometry for candidate crops.
- LlamaParse agentic parsing partitions PDFs larger than
  `LLAMAPARSE_MAX_PAGES_PER_JOB` pages, defaults to 50, and merges parsed
  pages back into the original page numbering.
- Partition waits use `LLAMAPARSE_TIMEOUT_SECONDS`, defaulting to 3600 seconds,
  and completed partition payloads are cached for resume under
  `parse_resume_cache/`.
- Parsing and indexing show CLI progress bars by default.
- Parsing resumes from per-document sidecars when completed artifacts still
  match the source PDF hash and selected parser.
- Build Grid-specific indexes:
  - vector index
  - official PageIndex index
  - GraphRAG index
  - ColiVara visual page index, synced through the ColiVara API
- Vector and PageIndex builds cache per-document parts and skip fresh final
  indexes by artifact revision. Re-run the same command to resume after a
  failure; use `--rebuild-indexes` for final output rebuilds and `--no-resume`
  to ignore cached per-document parts.
- Do not build a `find` index. Exact-find searches the parsed corpus directly
  at retrieval time.
- Add a python script interface similar to the reference `claude_agent` project.
- For the all index implementation, it should be the same in the reference project `/Users/maoxunhuang/Desktop/GridAgents/claude_agent` and adapted accordingly to this project.
- In the index script, make a knob so that I can enable Claude batch API call to reduce the cost.
- Don't need to run the build index script in this session because it would take a long time. Just to make sure the code is correct and I will run it locally by myself.

Implemented entrypoints:

```bash
cd app/GridAgentCore
uv run grid-parse-documents --parser llamaparse-agentic --force
uv run grid-build-indexes --methods vector,pageindex
uv run grid-build-indexes --methods graphrag
uv run grid-build-indexes --methods colivara
```

The `pageindex` method is wired to the sibling
`vector_pageindex_rag_eval` `pageindex_official` implementation, not the custom
`PageIndexRAG` method. It loads or clones VectifyAI's official self-hosted
PageIndex repo and calls the upstream Markdown tree builder. The official
adapter does not support `--anthropic-batch`; build without that flag.

GraphRAG is built by the local `grid_agent_core.graphrag` Microsoft GraphRAG
worker copied into this project. It no longer depends on the sibling `rlm-eval`
project.

ColiVara sync uploads raw PDFs from the parsed artifact manifest into the
configured `COLIVARA_COLLECTION_NAME`, sends stable Grid document metadata, and
writes local sync metadata to `indexes/colivara/index.json`. Runtime
`colivara_search` calls the hosted ColiVara search API and maps page-level
visual hits back to parsed Grid page text, page images, and citation-ready
evidence.

### Agent and Tools

- Adapt the useful retrieval behavior from `claude_agent`:
  - `vector_search`
  - `pageindex_search`
  - `graphrag_search`
  - `colivara_search`
  - exact keyword/find search
  - Claude Agent SDK retrieval/inspection tools when safely scoped
  - focused subagent support, especially a span/document retrieval subagent
- Return citation-ready evidence from tools: document id, title/path, page or
  section when available, span text, score, and artifact source.
- The root agent should answer with citations and summarize uncertainty when
  retrieved evidence is weak or conflicting.
- For the all tools implementation, it should be the same in the reference project `/Users/maoxunhuang/Desktop/GridAgents/claude_agent` and adapted accordingly to this project.

Agent payload:

```json
{
  "prompt": "Question text",
  "methods": ["vector", "pageindex", "graphrag", "colivara", "find"],
  "allow_sdk_file_tools": false,
  "enable_subagents": true
}
```

### AWS and AgentCore

- Upload/deploy raw Grid documents and generated index artifacts to AWS.
- Configure AgentCore Runtime for session isolation and scaling.
- The README must explain these isolation and scalability choices step by step.

### Frontend

- Provide a web page for asking Grid document questions.
- Stream or poll agent events so the UI can show progress during long searches.
- Display:
  - final cited answer
  - cited source snippets
  - root agent turns
  - retrieval tool calls and responses
  - subagent threads
  - expandable detail for each turn
  - latency, errors, and run metadata
- Reuse design/behavior ideas from `claude_agent` where helpful, but remove
  LegalBench-specific benchmark UI unless it is needed for Grid QA.

## AWS References To Confirm During Implementation

- AgentCore Runtime overview and scaling/session management:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html
- AgentCore isolated sessions:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html
- AgentCore lifecycle settings:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html
- AgentCore filesystem configuration:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html
- AgentCore VPC configuration:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html
