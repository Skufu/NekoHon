# Wide-net recall, before and after the label audit — 2026-10-23

Probe: `artifacts/probes/wide-net-recall-2026-10-23.py`
Dataset: `artifacts/datasets/wide-net-2026-10-23.jsonl` (33 hand-written
questions; 11 passages across all three books x literal / conversational /
vague). Command: `python artifacts/probes/wide-net-recall-2026-10-23.py`.

## What changed

Seven rows carried a single gold chunk that was too strict: a second passage
answers the same question. Those rows now list both. The audit read the top
three hits for every question whose gold sat outside the top 5; a sibling was
added only when it plainly answered the question.

| Rows extended | Sibling added |
| --- | --- |
| `quantization-5-literal` | `chapter-5-048` |
| `quantization-5-conversational` | `chapter-3-027` |
| `quantization-5-vague` | `chapter-5-057` |
| `quantization-3-vague` | `chapter-3-018` |
| `ddia-8-conversational` | `text00014-022` |
| `ddia-8-vague` | `text00014-022` |
| `ddia-10-vague` | `text00020-002` |

Five of the seven now count as hits at rank 5.

**Pooling caveat.** Siblings were drawn from the current system's top 10. That
is standard IR pooling, but it biases recall upward for the same system that
produced the pool. Treat the after number as an upper bound until a second
system produces candidates the pool never saw.

## Recall of an answer-bearing passage

| Register | Before @5 | After @5 | After @10 | After @20 | After @50 |
| --- | --- | --- | --- | --- | --- |
| literal | 10/11 | 11/11 | 11/11 | 11/11 | 11/11 |
| conversational | 6/11 | 6/11 | 6/11 | 8/11 | 9/11 |
| vague | 3/11 | 7/11 | 8/11 | 9/11 | 10/11 |
| **all** | **19/33** | **24/33** | 25/33 | 28/33 | 30/33 |

Mean rank fell from 58.1 to 37.4. Literal questions are now at mean rank 1.6.

## What the remaining misses are

| Question | Rank | Read |
| --- | --- | --- |
| `fde-8-vague` | 710 | "at which part of the work do you touch the most people at once" — no lexical anchor to "stakeholders" |
| `fde-8-conversational` | 206 | accountability phrasing, answered by a section titled "Whom You'll Work With" |
| `ddia-8-conversational` | 176 | "deal with a cluster where some machines work" — the practical answer is in the timeouts section |
| `fde-2-vague` | 37 | trust/quality, collides with the chapter 9 "Trust" section |
| `quantization-3-conversational` | 25 | "long conversation eats memory" — the KV cache section loses to chapter 1 scaling |
| `fde-2-conversational`, `quantization-5-conversational`, `quantization-7-vague`, `ddia-5-vague` | 6-13 | close; a reranker over the top 20 could promote them |

## What this means for reranking

A reranker sees a candidate pool. With a top-20 pool, four of the current
misses sit inside it (ranks 6, 11, 13, 13) and two more sit between 21 and 50.
The ceiling is therefore **4 items at rank 5 with a top-20 pool** (24 -> 28),
or 6 with a top-50 pool. Three misses (ranks 176, 206, 710) are unreachable by
any reranker; they need a better first stage or a query the book's vocabulary
can match.

That ceiling is above the 3-item threshold pre-registered in
`artifacts/plans/reranking-odp-2026-10-23.md`. The reranking bake-off (gate B)
is now justified. It was not before the label audit.
