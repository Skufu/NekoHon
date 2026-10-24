"""Rerank the dense top-20 with a cross-encoder on GPU. Read-only.

Baseline: dense top-5 of the whole book. Candidate: dense top-20, reordered by
bge-reranker-v2-m3 (fp16, CUDA), keep 5. Both scored against the audited gold
set in artifacts/datasets/wide-net-2026-10-23.jsonl.

Run: python artifacts/probes/probe-rerank-bge-2026-10-23.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import retrieve  # noqa: E402

DATASET = ROOT / "artifacts" / "datasets" / "wide-net-2026-10-23.jsonl"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
MODEL = "BAAI/bge-reranker-v2-m3"
POOL = 20
KS = (5, 10, 20)


def rank_of(chunks, gold):
    for position, chunk in enumerate(chunks, 1):
        if chunk["chunk_id"] in gold:
            return position
    return None


def main():
    from sentence_transformers import CrossEncoder

    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexes = {name: retrieve.load_index(path) for name, path in INDEXES.items()}

    started = time.perf_counter()
    reranker = CrossEncoder(MODEL, device="cuda", max_length=512)
    reranker.model.half()
    load_seconds = time.perf_counter() - started

    baseline, reranked, guarded, fused, oracle = [], [], [], [], []
    dense_seconds, rerank_seconds = [], []

    for row in rows:
        index = indexes[row["book_id"]]
        gold = set(row["gold_chunks"])
        tick = time.perf_counter()
        ranked = retrieve.rank_chunks(index, row["question"])
        dense_seconds.append(time.perf_counter() - tick)

        pool = [chunk for _score, chunk in ranked[:POOL]]
        baseline.append(rank_of(pool, gold))
        oracle.append(rank_of(pool, gold) is not None)

        tick = time.perf_counter()
        scores = reranker.predict([(row["question"], chunk.get("text") or "")
                                   for chunk in pool], batch_size=8,
                                  show_progress_bar=False)
        rerank_seconds.append(time.perf_counter() - tick)
        order = sorted(zip(scores, pool), key=lambda pair: pair[0], reverse=True)
        by_rerank = [chunk for _score, chunk in order]
        reranked.append(rank_of(by_rerank, gold))

        # Keep the dense leader on top; rerank decides positions 2..N.
        guarded_order = [pool[0]] + [chunk for chunk in by_rerank
                                     if chunk is not pool[0]]
        guarded.append(rank_of(guarded_order, gold))

        # RRF over dense rank and rerank rank, the repo's own constant.
        fused_scored = []
        for dense_position, chunk in enumerate(pool, 1):
            rerank_position = by_rerank.index(chunk) + 1
            fused_scored.append(
                (1.0 / (60 + dense_position) + 1.0 / (60 + rerank_position), chunk))
        fused_scored.sort(key=lambda pair: pair[0], reverse=True)
        fused.append(rank_of([chunk for _score, chunk in fused_scored], gold))

    def report(name, ranks, rows_subset):
        parts = []
        for register in ("literal", "conversational", "vague", "all"):
            subset = [rank for rank, row in zip(ranks, rows_subset)
                      if register == "all" or row["register"] == register]
            hits = " ".join(
                f"@{k}:{sum(1 for r in subset if r and r <= k)}/{len(subset)}"
                for k in KS)
            parts.append(f"{register[:4]} {hits}")
        print(f"  {name:14s} " + "  |  ".join(parts))

    print(f"model load {load_seconds:.2f}s   pool {POOL}")
    print("\n== source-chunk recall ==")
    report("baseline", baseline, rows)
    report("reranked", reranked, rows)
    report("keep dense #1", guarded, rows)
    report("rrf(dense,rr)", fused, rows)

    print("\n== by fold (0 = dev, 1-2 = sealed) ==")
    for fold in sorted({row["fold"] for row in rows}):
        subset = [i for i, row in enumerate(rows) if row["fold"] == fold]
        for name, ranks in (("baseline", baseline), ("reranked", reranked),
                            ("keep dense #1", guarded), ("rrf", fused)):
            hits = sum(1 for i in subset if (ranks[i] or 999) <= 5)
            print(f"  fold {fold}  {name:14s} @5 {hits}/{len(subset)}")
    print(f"\n  oracle ceiling (gold in top {POOL}): "
          f"{sum(1 for hit in oracle if hit)}/{len(oracle)}")
    print(f"  dense mean {sum(dense_seconds) / len(dense_seconds):.2f}s   "
          f"rerank mean {sum(rerank_seconds) / len(rerank_seconds):.2f}s   "
          f"total mean {(sum(dense_seconds) + sum(rerank_seconds)) / len(rows):.2f}s")

    print("\n== per question, changed verdicts ==")
    for row, before, after in zip(rows, baseline, reranked):
        if (before or 999) <= 5 and (after or 999) <= 5:
            continue
        print(f"  {row['id']:34s} {row['register'][:4]:4s} "
              f"pool_rank={before or 'absent':>6} -> reranked={after or 'absent':>6}")


if __name__ == "__main__":
    main()
