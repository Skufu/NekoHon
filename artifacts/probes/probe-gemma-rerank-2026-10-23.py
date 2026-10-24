"""Gemma first stage + cross-encoder second stage. Read-only.

The gemma index puts the gold chunk at mean rank 8.5 on vague questions but
only matches nomic at @5, so the ordering at the top is the weak part. This
runs the cross-encoder over gemma's top-20 and compares every combination.

Run: python artifacts/probes/probe-gemma-rerank-2026-10-23.py
"""
import copy
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
GEMMA = "embeddinggemma-2:270m-bf16-text"
POOL = 20
KS = (5, 10, 20)


def slow_embed(texts, model):
    return retrieve.ollama_embed(texts, model, timeout=900)


def stripped(index, model):
    fresh = copy.deepcopy(index)
    fresh["embedder"] = model
    for chunk in fresh.get("chunks") or []:
        chunk.pop("embedding", None)
        chunk.pop("_uvec", None)
    for figure in fresh.get("figures") or []:
        figure.pop("embedding", None)
        figure.pop("_uvec", None)
    return fresh


def rank_of(chunks, gold):
    for position, chunk in enumerate(chunks, 1):
        if chunk["chunk_id"] in gold:
            return position
    return None


def main():
    from sentence_transformers import CrossEncoder

    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    print("building gemma indexes ...")
    indexes = {}
    for book_id, path in INDEXES.items():
        base = json.loads(path.read_text(encoding="utf-8"))
        target = stripped(base, GEMMA)
        retrieve.embed_index(target, model=GEMMA, embed_fn=slow_embed)
        indexes[book_id] = target

    reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device="cuda", max_length=512)
    reranker.model.half()

    outcomes = {name: [] for name in ("nomic", "gemma", "gemma+rerank",
                                      "gemma+keep1", "gemma@10+rerank")}
    timings = []

    for row in rows:
        index = indexes[row["book_id"]]
        gold = set(row["gold_chunks"])
        tick = time.perf_counter()
        gemma_ranked = retrieve.rank_chunks(index, row["question"], model=GEMMA,
                                            embed_fn=slow_embed)
        pool = [chunk for _score, chunk in gemma_ranked[:POOL]]
        outcomes["gemma"].append(rank_of(pool, gold))
        outcomes["gemma@10+rerank"].append(rank_of(pool[:10], gold))

        scores = reranker.predict([(row["question"], chunk.get("text") or "")
                                   for chunk in pool], batch_size=8,
                                  show_progress_bar=False)
        by_rerank = [chunk for _score, chunk in
                     sorted(zip(scores, pool), key=lambda pair: pair[0], reverse=True)]
        outcomes["gemma+rerank"].append(rank_of(by_rerank, gold))
        outcomes["gemma+keep1"].append(
            rank_of([pool[0]] + [chunk for chunk in by_rerank if chunk is not pool[0]], gold))
        timings.append(time.perf_counter() - tick)

    def report(name, ranks):
        parts = []
        for register in ("literal", "conversational", "vague", "all"):
            subset = [rank for rank, row in zip(ranks, rows)
                      if register == "all" or row["register"] == register]
            hits = " ".join(
                f"@{k}:{sum(1 for r in subset if r and r <= k)}/{len(subset)}"
                for k in KS)
            parts.append(f"{register[:4]} {hits}")
        print(f"  {name:18s} " + "  |  ".join(parts))

    print("\n== source-chunk recall ==")
    for name in outcomes:
        if name == "nomic":
            continue
        report(name, outcomes[name])

    print("\n== by fold (0 = dev, 1-2 = sealed) ==")
    for fold in sorted({row["fold"] for row in rows}):
        subset = [i for i, row in enumerate(rows) if row["fold"] == fold]
        line = []
        for name in ("gemma", "gemma+rerank", "gemma+keep1"):
            hits = sum(1 for i in subset if (outcomes[name][i] or 999) <= 5)
            line.append(f"{name} {hits}/{len(subset)}")
        print(f"  fold {fold}: " + "   ".join(line))
    print(f"\n  mean dense+rerank {sum(timings) / len(timings):.2f}s per question")


if __name__ == "__main__":
    main()
