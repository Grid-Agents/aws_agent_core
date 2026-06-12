# Golden-set eval report

- corpus revision: 27 docs (c7dc7b51104d), methods: vector, pageindex, find
- questions scored: 15/15
- **answer accuracy: 100%**
- retrieval hit rate: 100%
- citation hit rate: 100%

| id | type | ans | ret | cit | status |
|---|---|---|---|---|---|
| golden-001 | numerical | ✅ | ✅ | ✅ | completed |
| golden-002 | numerical | ✅ | ✅ | ✅ | completed |
| golden-003 | figure_numerical | ✅ | ✅ | ✅ | completed |
| golden-004 | numerical | ✅ | ✅ | ✅ | completed |
| golden-005 | figure_reading | ✅ | ✅ | ✅ | completed |
| golden-006 | figure_reading | ✅ | ✅ | ✅ | completed |
| golden-007 | numerical | ✅ | ✅ | ✅ | completed |
| golden-008 | procedural | ✅ | ✅ | ✅ | completed |
| golden-009 | figure_reading | ✅ | ✅ | ✅ | completed |
| golden-010 | procedural | ✅ | ✅ | ✅ | completed |
| golden-011 | figure_reading | ✅ | ✅ | ✅ | completed |
| golden-012 | figure_reading | ✅ | ✅ | ✅ | completed |
| golden-013 | procedural | ✅ | ✅ | ✅ | completed |
| golden-014 | multi_hop | ✅ | ✅ | ✅ | completed |
| golden-015 | figure_numerical | ✅ | ✅ | ✅ | completed |

- figure: 100% (7 q)

- multihop: 100% (1 q)

- text: 100% (7 q)

## Adversarial analysis (post-hoc audit)

**Hard cheating: ruled out.**
- All 15 trajectories audited: every tool call was a `grid_retrieval` MCP tool; file tools off, subagents off, no web. Golden file unreachable from the agent's sandbox.
- Strict re-judge (sonnet-4-6, adversarial prompt, full answers): 15/15 — answer quality is real.

**Where 100% flatters:**
- Strict char-span citation scoring: 8/15; the other 7 (all figure questions) pass only via the page-+/-1 fallback — agent cites the right page/figure but different chunk boundaries than the golden span.
- All 15 questions name their source document and usually the exact section/figure: the eval measures look-up more than search. Redaction ablation (n=3): scores held (3/3), so this advantage was not load-bearing on the sample, but question phrasing is still generated from the corpus itself.
- Figure questions are circular w.r.t. the VLM: golden answers were generated from the same parse-time figure descriptions the agent retrieves — they verify pipeline consistency, not visual ground truth.
- 3/15 questions were closed-book answerable by the generator model (golden-004/007/014).
- n=15; all evidence from the 6 original docs (the 21 new docs act only as distractors).

**Recommendations for golden set v2:** human-paraphrased questions (no doc/section names), human-verified figure answers from the source PDFs, cross-document multi-hop questions, unanswerable/negative controls, n>=50, and strict char-span scoring as the headline metric.
