# Golden Evaluation Set

A golden set of 15–20 question/answer pairs, each anchored to verifiable evidence
(an exact page span or a figure) in the Grid Docs corpus, used to evaluate the
Grid agent's retrieval and answer quality. Authoring is automated with Claude; a
human approves the final set.

Implemented by [`scripts/build_golden_set.py`](../scripts/build_golden_set.py).

## Why this approach

- **Manual authoring doesn't scale** — days of expert time. We automate authoring
  and reduce the human role to a short review.
- **Bias is controlled by design.** Evidence is sampled randomly from the raw
  corpus (`manifest.jsonl`) — never through the agent's own retrieval index — so
  the eval cannot be skewed toward what the agent already finds well.
- **Correctness is controlled by independent verification.** Every candidate must
  pass automated checks run as fresh, separate model calls before a human sees it.
- The generator shares no code, prompts, or context with the agent under test.

## Method

1. **Stratified sampling (mechanical, seeded — no LLM).** A fixed coverage matrix
   sets how many text, figure, and multi-hop questions to attempt, distributed
   round-robin across all documents. Pages and figures are chosen with a seeded RNG
   (`--seed`), so runs are reproducible. We oversample (`--oversample`, default
   2.5×) because verification discards a large fraction.

2. **Evidence-first generation (Claude).** For each sampled unit, Claude sees *only*
   that page text (or figure image + its vision-model description + surrounding page
   text) and writes a question, the golden answer, and verbatim supporting quote(s).
   Questions must be self-contained and name their source authority where the answer
   would otherwise be ambiguous across standards.

3. **Independent verification (separate model calls).**
   - **Grounding** — given only the question + cited evidence, the model must
     reproduce the answer. If the evidence doesn't support it, discard.
   - **Closed-book** — given the question with *no* evidence, if the model answers
     it correctly from general knowledge, the question tests world knowledge rather
     than retrieval. Discard.

4. **Human approval (~30 min).** The domain owner reviews each survivor in
   `review.md` with its evidence attached — approve or veto. This is the final
   guarantee of correctness.

5. **Versioned storage.** Survivors are written with answer, evidence anchors
   (document id, page, char span, figure path) and content hashes, plus the
   `artifact_revision` they were built against — so evidence stays verifiable even
   if the corpus is re-parsed.

## Usage

```bash
cd app/GridAgentCore
set -a; source ../../.env; set +a          # provides ANTHROPIC_API_KEY

# 1. Inspect the sampling plan with zero API spend.
uv run python ../../scripts/build_golden_set.py --dry-run

# 2. Generate + verify the full set.
uv run python ../../scripts/build_golden_set.py --target 18

# Stronger independence: verify with a different model than the generator.
uv run python ../../scripts/build_golden_set.py \
  --generator-model claude-opus-4-8 --verifier-model claude-sonnet-4-6
```

Key flags: `--target` (final count), `--oversample`, `--figure-fraction` (default
0.35), `--multihop-fraction` (default 0.12), `--seed`, `--concurrency`.

## Outputs

Written to `--out-dir` (default `.grid_artifacts/golden_set/`):

| File | Contents |
|------|----------|
| `golden_set.jsonl` | The approved-pending questions, one JSON object per line (schema below). |
| `rejected.jsonl` | Every discarded candidate with the filter reason — useful signal about where the eval has real retrieval difficulty. |
| `review.md` | Human-review checklist: each survivor with its evidence and quotes. |

### `golden_set.jsonl` record schema

```json
{
  "id": "golden-007",
  "question": "...",
  "answer": "...",
  "question_type": "numerical",
  "modality": "figure",
  "supporting_quotes": ["verbatim quote from the evidence"],
  "evidence": [
    {"document_id": "grid/04-...", "title": "...", "page": 12, "kind": "figure",
     "figure_id": "...", "figure_path": "figures/...jpg", "image_sha256": "..."}
  ],
  "verification": {"grounded": true, "grounding_evidence_answer": "...", "closed_book_answer": "UNKNOWN"},
  "generator_model": "claude-opus-4-8",
  "verifier_model": "claude-opus-4-8",
  "artifact_revision": "01359f3f..."
}
```

`evidence` is a list (multi-hop questions cite two units). For `kind: "text"`,
the anchor carries `char_start` / `char_end` / `text_sha256` instead of the
figure fields.

## Scoring with the golden set

Because evidence is anchored, retrieval and answer quality can be scored
separately:

- **Retrieval** — did the agent surface the cited page / figure for each question?
- **Answer correctness** — LLM-judge the agent's answer against the golden answer.

Two metrics are far more diagnostic than a single pass/fail.
