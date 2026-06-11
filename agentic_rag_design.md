# Grid Agentic RAG — Design Guide

This document explains how the Grid agentic RAG system is designed: what each
retrieval tool is for, how they are built and queried, how documents are parsed
into a multimodal corpus, and how everything is wired into the Claude Agent SDK
harness. It is meant both as an orientation for new readers and as guidance for
the agent (and its subagents) on how to use the toolbox well.

---

## 1. Philosophy

Classic RAG runs one retriever, stuffs the top-k chunks into the prompt, and
hopes the answer is in there. That breaks down on a heterogeneous corpus (UK
grid legislation, codes, standards, engineering recommendations, connections
reform documents) where the answer might be:

- a paraphrase of the question buried in prose,
- a specific numbered clause or defined term,
- a relationship that spans two documents, or
- something that only exists visually — a chart, schematic, or table.

No single retriever wins on all four. So instead of picking one, we expose
**several retrievers as tools** and let a Claude agent decide which to call,
in what order, and how to combine the evidence. The agent reasons about the
question, picks a retrieval strategy, inspects what comes back, and re-queries
or switches tools if the evidence is weak. That is the "agentic" part: retrieval
is a loop driven by the model, not a fixed pre-processing step.

Two invariants hold across every tool:

1. **Everything resolves to evidence spans.** Each tool returns `SearchHit`s
   that map to a `document_id` plus character offsets in the parsed corpus.
   These become `Evidence` objects with stable IDs (`E1`, `E2`, …) that the
   agent cites. This uniformity is what lets the agent mix tools freely.
2. **Figures travel with text.** When a retrieved span overlaps a figure, the
   figure's VLM description (and, when useful, the image itself) is attached to
   the evidence — so visual context is available no matter which text tool found
   the span.

Code anchors: tool descriptions in
[agent.py:80-123](../app/GridAgentCore/grid_agent_core/agent.py#L80-L123);
search dispatch in
[retrieval.py:36-55](../app/GridAgentCore/grid_agent_core/retrieval.py#L36-L55).

---

## 2. Two phases: build time vs. query time

Everything below splits into **build time** (offline, run once per corpus
revision, produces artifacts under `.grid_artifacts/`) and **query time**
(online, per user question, inside the agent loop).

```
BUILD TIME (offline)                         QUERY TIME (per question)
──────────────────────                       ──────────────────────────
raw PDFs                                      user question
   │                                              │
   ├─ LlamaParse (agentic) ──► markdown           ├─ agent picks tool(s)
   │                                              │
   ├─ VLM enrichment ──► figure crops +           ├─ vector / pageindex / find /
   │                     descriptions             │  colqwen2 / colivara / graphrag
   │                                              │     │
   ├─ corpus/*.txt + manifest.jsonl               │     └─► SearchHits ──► Evidence
   │                                              │
   └─ build indexes:                              ├─ agent inspects, re-queries
      vector / pageindex / colqwen2 /             │
      colivara / graphrag                         └─ cite_evidence ──► answer + [E#]
```

A content hash (`artifact_revision.txt`) tracks freshness so indexes can be
rebuilt only when the underlying documents change.

---

## 3. Document parsing — the foundation

Retrieval quality is capped by parse quality. The corpus is built in two stages.

### 3.1 LlamaParse (agentic tier)

[llama_parse_agentic.py](../app/GridAgentCore/grid_agent_core/llama_parse_agentic.py)

We use LlamaCloud's **agentic** parse tier (`tier="agentic"`), which does
layout-aware extraction — it understands page structure, columns, tables, and
labels regions (e.g. `figure`, `image`, `chart`, `diagram`) rather than
flattening the page into raw text. Output per page is Markdown plus a raw
layout payload (`ParsedPage` = page number + markdown).

Operational details that matter:

- **Partitioning.** PDFs over `LLAMAPARSE_MAX_PAGES_PER_JOB` (default 50 pages)
  are split into page-range batches so large documents don't overwhelm a single
  job ([llama_parse_agentic.py:119-192](../app/GridAgentCore/grid_agent_core/llama_parse_agentic.py#L119-L192)).
- **Resumable cache.** Each batch's raw result is cached at
  `.parse_resume_cache/pages-{start}-{end}.raw.json`. A payload validator
  detects schema drift so stale caches aren't silently reused. Parsing is the
  slowest and most expensive build step, so the cache is what makes iteration
  tolerable.

### 3.2 VLM enrichment (multimodal)

[multimodal_enrichment.py](../app/GridAgentCore/grid_agent_core/multimodal_enrichment.py)

LlamaParse gives us text; it does not give us the *meaning* of a chart or
schematic. VLM enrichment fills that gap by turning every material figure into
searchable text and a linked image.

Pipeline (`enrich_page_markdown_with_visuals`,
[multimodal_enrichment.py:171-291](../app/GridAgentCore/grid_agent_core/multimodal_enrichment.py#L171-L291)):

1. **Candidate detection.** Prefer LlamaParse layout entries labelled
   `figure|image|chart|diagram`. Fall back to geometry detection with PyMuPDF —
   image blocks, clustered vector drawings, and caption regexes
   (`fig.|figure|diagram`). Reject candidates by area ratio (must be ~0.6%–82%
   of the page), extreme aspect ratios, and header/footer bands, so logos and
   rules don't get described.
2. **VLM description.** Each cropped figure + surrounding page text is sent to
   **Claude Sonnet 4.5** (`GRID_VLM_MODEL`, default
   `claude-sonnet-4-5-20250929`). The model returns
   `{material_figure, figure_type, description}`. Non-material crops (tables,
   logos, blank/dark regions) are filtered out.
3. **Linking.** Accepted figures are written as JPEGs under
   `figures/grid/{document_key}/page-NNNN-figure-KK.jpg` and inserted back into
   the page Markdown as `### Figure context - page N figure K` blocks. Because
   the description lives *inline in the corpus text*, it is embedded by the
   vector index, walked by PageIndex, and substring-matched by Find — every text
   tool can now "see" the figure. The image path is also recorded in the figure
   manifest so it can be re-attached at query time.

Concurrency is a `ThreadPoolExecutor` (default 4 workers); results are cached
per page at `.parse_resume_cache/page-NNNN.visual.json`, keyed by SHA256 of the
markdown + context + render settings.

### 3.3 Corpus assembly

[corpus.py](../app/GridAgentCore/grid_agent_core/corpus.py) writes:

- `corpus/grid/{document_id}.txt` — enriched Markdown with `[Page N]` markers
  (these markers are how character offsets map back to page numbers).
- `manifest.jsonl` — one record per document: title, category, filename, page
  ranges, figure metadata.
- `artifact_revision.txt` — SHA256 over document content hashes (freshness key).

Everything downstream reads from this corpus, so all retrievers operate on the
same enriched text and agree on offsets.

---

## 4. The retrieval toolbox

Six retrieval methods are implemented. The four primary ones are below in
depth; ColiVara and GraphRAG are documented as the visual sibling and the
graph option. The agent sees each as a `{method}_search` tool.

### 4.1 Vector Search — the default

[rag_compat/vector_rag.py](../app/GridAgentCore/grid_agent_core/rag_compat/vector_rag.py),
loaded by `load_vector_hits` in
[indexes.py](../app/GridAgentCore/grid_agent_core/indexes.py).

**Purpose.** Conceptual / paraphrased questions where the answer's wording
differs from the query. This is the agent's default tool.

**Build time.**
- *Chunking* (default **semantic**): embed paragraph windows, detect topic
  breakpoints at the 82nd-percentile embedding distance, pack into chunks
  (~1200 chars, 120 overlap) with hierarchy metadata. Alternatives:
  `hierarchical` (section-aware), `recursive`, `fixed`.
- *Embeddings*: Voyage `voyage-law-2` (default) or SentenceTransformers
  `BAAI/bge-large-en-v1.5`. The VLM figure descriptions are embedded along with
  everything else.
- Chunks (text + `document_id` + char offsets + section title) and their vectors
  are persisted under `indexes/vector/`.

**Query time.**
1. Embed the query.
2. Score every chunk by cosine similarity **and** BM25 (in-memory BM25, k1=1.5,
   b=0.75, regex tokenizer).
3. **Hybrid fusion**: `0.65 * vector + 0.35 * BM25` (tunable). Hybrid catches
   both the semantically-similar chunk and the one that happens to contain the
   exact rare term.
4. **Rerank** the fused top set with Voyage `rerank-2` (or a SentenceTransformers
   cross-encoder) for final ordering.
5. Return top-k `SearchHit`s.

**Why this design.** Pure vector search misses exact tokens (clause IDs,
acronyms); pure BM25 misses paraphrase. Hybrid + rerank gives a strong general
default, which is why the system prompt nudges the agent here first.

### 4.2 PageIndex — structure-aware navigation

[rag_compat/official_pageindex/](../app/GridAgentCore/grid_agent_core/rag_compat/official_pageindex/),
loaded by `load_pageindex_hits` in
[indexes.py](../app/GridAgentCore/grid_agent_core/indexes.py).

**Purpose.** Questions tied to a document's *structure* — a specific clause,
numbered section, or "where in document X is Y defined?" Chunk-based retrieval
struggles here because the relevant unit is a section, not a 1200-char window.

**Build time.** Using VectifyAI's official PageIndex, we convert each Grid
document into virtual-page Markdown (≈900 target / 1200 max tokens per virtual
page) and build a hierarchical **table-of-contents tree** of nodes. With
`GRID_PAGEINDEX_BUILD_WITH_LLM=1`, an LLM summarizes each node so the tree can
be navigated by meaning. The tree is stored at `indexes/pageindex/index.json`.

**Query time** (LLM-in-the-loop retrieval, not vector lookup):
1. **Document selection.** An LLM reads the catalog of all documents (truncated
   to ~120k chars) and picks the 3–5 most likely to contain the answer (keyword
   fallback if the LLM call fails).
2. **Tree walk.** For each selected document, the LLM traverses the ToC tree
   top-down and selects terminal nodes (default ~10).
3. **Span recovery.** Selected node text is mapped back to corpus character
   offsets via the span resolver, producing `SearchHit`s.

**Why this design.** It mimics how a human finds a clause — open the right
document, scan the contents, drill into the section — rather than hoping a
chunk boundary happened to land on the answer.

### 4.3 Find — exact keyword / phrase lookup

[retrieval.py:126-165](../app/GridAgentCore/grid_agent_core/retrieval.py#L126-L165)

**Purpose.** Precise verbatim terms — a clause number (`CC.6.1.5`), defined
name, acronym, or quoted phrase — that semantic search would paraphrase past.
The tool takes an **exact term, not a question**.

**Build time.** None. Find reads the parsed corpus directly.

**Query time.** Case-insensitive literal substring search over the corpus.
Each match returns a ±`FIND_CONTEXT_CHARS` (1400) window so the agent gets
surrounding context, deduplicated by `(document_id, start, end)`, capped at
`MAX_FIND_MATCHES` (12). Exact-phrase matches score 1.0; individual token hits
score 0.65.

**Why this design.** Embeddings smear over exact identifiers — an agent
verifying that a specific clause exists or pulling the exact wording of a
defined term needs literal matching with zero ranking magic. Find is the
precision instrument that complements vector's recall.

### 4.4 ColQwen2 — self-hosted visual retrieval

Client/builder [colqwen2.py](../app/GridAgentCore/grid_agent_core/colqwen2.py);
service in [colqwen2_service/](../app/GridAgentCore/colqwen2_service/); SageMaker
IaC in [infra/colqwen2_sagemaker/](../infra/colqwen2_sagemaker/); loaded by
`load_colqwen2_hits`.

**Purpose.** Answers that live in the *pixels* — complex charts, diagrams,
schematics, dense tables, or page layout that survives parsing poorly. Uses
**multi-vector page embeddings** (ColPali-family late interaction), served from
internal AWS infrastructure (a SageMaker endpoint running
`vidore/colqwen2-v1.0`).

**Build time.**
1. Render each PDF page to JPEG at `COLQWEN2_IMAGE_DPI` (default 144) with
   PyMuPDF + Pillow → `colqwen2_pages/{slug}/page-NNNN.jpg`.
2. Send page images to the SageMaker endpoint, which returns a **multi-vector**
   embedding per page — a matrix of shape `(num_patches, 128)`, not a single
   vector. Adaptive batching splits on timeout for big documents.
3. Persist each page matrix as `.npy` under `indexes/colqwen2/embeddings/...`
   and page metadata (doc, page, char span, image path, shape) in
   `indexes/colqwen2/index.json`.

**Query time.**
1. Embed the text query through the same endpoint → query multi-vector matrix.
2. **MaxSim (late interaction)**: for each page, build the query×page similarity
   matrix, take the max over page patches per query token, and sum — the ColBERT
   scoring rule. This lets individual query tokens match individual regions of a
   page, which is exactly what you want for "find the page with this kind of
   diagram."
3. Rank pages by MaxSim, return the top pages with their full-page JPEGs.

**Why multi-vector?** A single embedding per page throws away *where* on the
page the match is. Late interaction keeps per-patch detail, which is far more
discriminative for visually complex pages — at the cost of storing a matrix per
page and doing O(query × patches) scoring.

### 4.5 ColiVara — hosted visual retrieval (sibling of ColQwen2)

[colivara.py](../app/GridAgentCore/grid_agent_core/colivara.py)

Same use case as ColQwen2 (charts, diagrams, tables, layout) and the same
ColPali-style late-interaction idea, but **hosted**: PDFs are upserted to a
ColiVara collection at build time, embeddings live in their service, and query
time is a call to ColiVara's `/v1/search/` that returns page images + scores,
which we map back to Grid `document_id`s. Use it when you don't want to operate
a SageMaker endpoint; use ColQwen2 when visual embeddings must stay on internal
AWS infrastructure.

### 4.6 GraphRAG — multi-hop / cross-document (optional)

Knowledge-graph retrieval over entities and relationships extracted from the
corpus (Microsoft GraphRAG, local-worker protocol). Best for questions that
connect entities across documents — "how does the connections reform affect
obligations in the Grid Code?" Returns graph-grounded text units. It is heavier
to build and query than the others, so treat it as a specialist tool for
explicitly relational questions.

### 4.7 Tool selection cheat-sheet (what the agent should reach for)

| Question shape | Tool | Why |
|---|---|---|
| Conceptual / paraphrased | **vector** | hybrid + rerank, best general recall |
| "Which clause / section / where is X defined" | **pageindex** | navigates document structure |
| Exact clause ID, acronym, quoted phrase | **find** | literal match, no paraphrase drift |
| Answer is in a chart/diagram/table/layout | **colqwen2** / **colivara** | page-image late interaction |
| Relationship across entities/documents | **graphrag** | entity graph, multi-hop |

---

## 5. Harness wiring — the Claude Agent SDK

[agent.py](../app/GridAgentCore/grid_agent_core/agent.py)

### 5.1 Tools as an MCP server

Each enabled method is registered as an SDK tool via `@tool()` and exposed
through an in-process MCP server named `grid_retrieval`. The agent sees tool
names like `mcp__grid_retrieval__vector_search`, plus two control tools:

- `inspect_evidence` — read the full JSON of a piece of evidence.
- `cite_evidence` — select the final citation set before answering.

Each `{method}_search` tool takes `{"query": str}`, calls
`repository.search(method, query, top_k=8)`
([retrieval.py:36](../app/GridAgentCore/grid_agent_core/retrieval.py#L36)),
and formats the hits into evidence blocks. Destructive/general tools (Bash,
Write, Edit, WebFetch, WebSearch) are disallowed; scoped SDK Read/Glob/Grep over
`corpus/grid/` can optionally be enabled for corpus inspection.

### 5.2 Evidence, figures, and images in context

`search` returns `Evidence` objects; the tool result renders each as a text
block (`document_id`, page, section, score, span text truncated to
`MAX_VISIBLE_SPAN_CHARS` = 4200) followed by figure context. When a span
overlaps a figure (or, failing that, shares a page), the figure's description is
appended and — for up to `MAX_TOOL_IMAGES` (4) figures per search, each under
`MAX_TOOL_IMAGE_BYTES` (4 MB) — the **actual image is attached as an image
block** so the model can read the chart directly
([agent.py:174-206](../app/GridAgentCore/grid_agent_core/agent.py#L174-L206)).
The SDK stdio buffer is raised to 32 MB to accommodate image-heavy results.

The system prompt
([agent.py:126-149](../app/GridAgentCore/grid_agent_core/agent.py#L126-L149))
constrains the agent to answer **only from retrieved evidence**, cite with
`[E#]`, surface uncertainty when evidence is weak or conflicting, use attached
figure images only when they materially clarify a visual, and call
`cite_evidence` before finalizing.

### 5.3 Subagent: `span-retriever`

When enabled, the root agent can delegate independent retrieval angles to a
`span-retriever` subagent
([agent.py:388-410](../app/GridAgentCore/grid_agent_core/agent.py#L388-L410)).
It has the same retrieval + `inspect_evidence` tools, runs in a bounded loop
(≈6 turns, no-ask permission mode), and returns **candidate evidence IDs and why
they matter**. The root agent collects those findings and makes the final
citation decision. This is the multi-perspective pattern: fan out several
retrieval strategies in parallel, let the root reconcile.

### 5.4 Budgets and limits

`MAX_TOOL_ACTIONS` = 28, `MAX_AGENT_TURNS` = 18, `MAX_AGENT_BUDGET_USD` = 1.0
([agent.py:28-33](../app/GridAgentCore/grid_agent_core/agent.py#L28-L33)).
These keep a single question from looping indefinitely or running up cost.

### 5.5 Observability

Every step emits a trajectory event — `user`, `tool-call`, `retrieval`
(method + query + evidence IDs), `error`, `citation`, `result`. The final
payload returns the answer, cited evidence, all retrieved evidence, the full
trajectory, latency, and the artifact revision — so any answer can be replayed
and audited.

---

## 6. Guidance for the agent and subagents (performance)

This section is operational advice, derived from the design above.

1. **Start with `vector`** for almost everything; it has the best general
   recall. Switch deliberately, not randomly.
2. **Escalate to `find` for precision.** If the question hinges on an exact
   identifier (clause number, acronym, defined term), or if you need to *verify*
   a specific string actually appears, use `find` — don't trust a paraphrase.
3. **Use `pageindex` when the question is structural** ("which section…",
   "where is … defined"). It will land you in the right section instead of a
   stray chunk.
4. **Go visual (`colqwen2`/`colivara`) when text retrieval returns thin or
   off-topic evidence and the answer plausibly lives in a figure/table.** Read
   the attached page image rather than guessing from a poor OCR span.
5. **Combine tools on hard questions.** A common strong pattern: `vector` for
   the concept → `find` to pin the exact clause → cite both. For relational
   questions, `graphrag` to find the connection → `pageindex`/`find` to ground
   each end in source text.
6. **Cross-check before citing.** If two tools surface conflicting spans, say so
   and cite both rather than picking silently. Weak/missing evidence should be
   stated, not papered over.
7. **Subagents: assign distinct angles, not duplicates.** Give each
   `span-retriever` a different tool/sub-question so their evidence sets are
   complementary; have them return evidence IDs + rationale for the root to
   reconcile.
8. **Respect the budget.** With 28 tool actions and 18 turns, prefer one
   well-aimed query over many vague ones. Inspect what you got before
   re-querying.

---

## 7. Artifact & config reference

### 7.1 Artifact layout (`.grid_artifacts/`)

```
manifest.jsonl                 document records + page/figure metadata
artifact_revision.txt          SHA256 freshness key
corpus/grid/*.txt              enriched Markdown with [Page N] markers
raw/**/*.pdf                   source PDFs
figures/grid/{doc}/*.jpg       VLM-accepted figure crops
colqwen2_pages/{slug}/*.jpg    full-page renders @ DPI
indexes/
  vector/      index.json, config.json, cache/
  pageindex/   index.json, config.json, cache/
  colqwen2/    index.json, embeddings/{slug}/*.npy
  colivara/    index.json (sync metadata)
  graphrag/    graphrag_ms/output/ (entity/relationship tables)
parse_resume_cache/            LlamaParse + VLM caches (not uploaded to S3)
```

### 7.2 Key environment variables

| Area | Vars |
|---|---|
| Setup | `GRID_DOCS_DIR`, `GRID_ARTIFACT_DIR`, `GRID_S3_BUCKET`, `GRID_S3_PREFIX` |
| Parse | `GRID_PARSE_PROVIDER=llamaparse-agentic`, `LLAMA_CLOUD_API_KEY`, `LLAMAPARSE_MAX_PAGES_PER_JOB` |
| VLM | `GRID_MULTIMODAL_ENRICH=1`, `GRID_VLM_MODEL`, `ANTHROPIC_API_KEY` |
| Vector | `GRID_VECTOR_EMBEDDING_MODEL`, `GRID_VECTOR_CHUNK_SIZE/_OVERLAP`, `GRID_VECTOR_HYBRID_VECTOR_WEIGHT/_BM25_WEIGHT`, `GRID_VECTOR_RERANKER_*`, `VOYAGE_API_KEY` |
| PageIndex | `GRID_PAGEINDEX_BUILD_WITH_LLM`, `GRID_PAGEINDEX_VIRTUAL_PAGE_TARGET_TOKENS`, `GRID_PAGEINDEX_AUTO_CLONE_REPO` |
| ColQwen2 | `COLQWEN2_ENDPOINT_NAME`, `COLQWEN2_MODEL_NAME`, `COLQWEN2_IMAGE_DPI`, `COLQWEN2_INDEX_BATCH_SIZE`, `COLQWEN2_TIMEOUT_SECONDS` |
| ColiVara | `COLIVARA_API_KEY`, `COLIVARA_API_BASE_URL`, `COLIVARA_COLLECTION_NAME` |
| Runtime | `AWS_REGION`, `ANTHROPIC_MODEL` (Bedrock model ID), `AGENTCORE_RUNTIME_ARN` |

### 7.3 Models at a glance

| Stage | Model / library |
|---|---|
| Parse | LlamaCloud agentic tier |
| VLM enrichment | Claude Sonnet 4.5 |
| Vector embeddings | Voyage `voyage-law-2` / `bge-large-en-v1.5` |
| Rerank | Voyage `rerank-2` / `bge-reranker-v2-m3` |
| BM25 | in-house in-memory |
| PageIndex tree + traversal | VectifyAI PageIndex + Claude (Bedrock/Anthropic) |
| ColQwen2 | `vidore/colqwen2-v1.0` on SageMaker |
| ColiVara | hosted ColiVara API |
| Agent runtime | Claude Agent SDK + Claude Sonnet 4.5 (Bedrock) |
| PDF render | PyMuPDF + Pillow |

---

## 8. Summary

The system is a multimodal agentic RAG over UK grid documents. A
LlamaParse-agentic + Claude-VLM pipeline produces an enriched, figure-aware
corpus where every retriever shares the same offsets and figure links. On top of
that corpus sit complementary retrievers — **vector** (default hybrid+rerank),
**pageindex** (structure), **find** (exact), **colqwen2/colivara** (visual late
interaction), and **graphrag** (relational) — exposed as MCP tools to a Claude
agent. The agent picks and combines tools, optionally fans out to
`span-retriever` subagents, attaches figure images into its own context, and
cites `Evidence` spans, all under explicit action/turn/cost budgets with a fully
recorded trajectory.
