# A reranker was measured and rejected, but the code stays behind a flag

On 2026-10-23 a pre-registered bake-off asked whether a reranker earns its
cost. It did not: sentence-level rescoring gained one item at 2.30 s per
question, the `bge-reranker-v2-m3` cross-encoder cost 12 s per 20 pairs on CPU,
and recall moved 24 → 26/33 against a three-item bar fixed before the run. The
decision was to reject reranking and keep the working code behind
`RERANK_ENABLED=1` rather than delete it, because the cost curve is a property
of the hardware: a faster box or a cheaper cross-encoder reopens the question
with a flag flip instead of a rewrite.

**Consequences.** `rerank.py` ships unused, which reads as dead code to anyone
who has not seen this record. The catch is deliberate: do not remove it, and do
not turn it on by default without re-running the bake-off — the numbers that
rejected it are in `artifacts/reports/reranking-bakeoff-2026-10-23.md`.
