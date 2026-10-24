"""Sentence-level re-scoring of the top-20, no new model. Read-only.

A chunk's cosine is averaged over the whole chunk, so one answer sentence is
diluted by its neighbours. This takes the dense top-20, splits each into
sentences, embeds them all, and scores each chunk by its best sentence. Three
rankings are compared: whole-chunk (baseline), best-sentence, and a blend.

Run: python artifacts/probes/probe-sentence-rerank-2026-10-23.py
"""
import json
import re
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
POOL = 20
TOP = 5
KS = (5, 10, 20)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def unit(vector):
    norm = (sum(value * value for value in vector)) ** 0.5
    return [value / norm for value in vector] if norm else vector


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sentences(text):
    parts = []
    for paragraph in (text or "").split("\n"):
        for piece in SENTENCE.split(paragraph):
            piece = piece.strip()
            if len(piece) >= 40:
                parts.append(piece)
    return parts


def rank_of(chunks, gold, key):
    ordered = sorted(chunks, key=key, reverse=True)
    for position, chunk in enumerate(ordered, 1):
        if chunk["chunk_id"] in gold:
            return position
    return None


def main():
    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexes = {name: retrieve.load_index(path) for name, path in INDEXES.items()}
    for index in indexes.values():
        for chunk in index["chunks"]:
            chunk["_uvec"] = chunk.get("_uvec") or unit(chunk["embedding"])

    strategies = ("baseline", "best_sentence", "blend")
    results = {name: [] for name in strategies}
    timings = []

    for row in rows:
        index = indexes[row["book_id"]]
        model = index["embedder"]
        started = time.perf_counter()
        q_unit = unit(retrieve.embed_texts(
            [row["question"]], model, retrieve.ollama_embed, "query")[0])
        chunks = index["chunks"]
        pool = sorted(chunks, key=lambda c: dot(q_unit, c["_uvec"]), reverse=True)[:POOL]
        gold = set(row["gold_chunks"])

        # One batched embedding call for every sentence in the pool.
        flat, owner = [], []
        for position, chunk in enumerate(pool):
            for sentence in sentences(chunk.get("text") or ""):
                flat.append(sentence)
                owner.append(position)
        vectors = []
        for start in range(0, len(flat), 16):
            vectors.extend(retrieve.embed_texts(
                flat[start:start + 16], model, retrieve.ollama_embed, "query"))
        best = {}
        for position, vector in zip(owner, vectors):
            score = dot(q_unit, unit(vector))
            if position not in best or score > best[position]:
                best[position] = score

        base_scores = {i: dot(q_unit, chunk["_uvec"]) for i, chunk in enumerate(pool)}
        for chunk in pool:
            chunk["_base"] = base_scores[pool.index(chunk)]
            chunk["_best"] = best.get(pool.index(chunk), chunk["_base"])

        results["baseline"].append(rank_of(pool, gold, lambda c: c["_base"]))
        results["best_sentence"].append(rank_of(pool, gold, lambda c: c["_best"]))
        results["blend"].append(
            rank_of(pool, gold, lambda c: 0.5 * c["_base"] + 0.5 * c["_best"]))
        timings.append(time.perf_counter() - started)

    def report(name, ranks):
        parts = []
        for register in ("literal", "conversational", "vague", "all"):
            subset = [rank for rank, row in zip(ranks, rows)
                      if register == "all" or row["register"] == register]
            hits = " ".join(
                f"@{k}:{sum(1 for r in subset if r and r <= k)}/{len(subset)}" for k in KS)
            parts.append(f"{register[:4]} {hits}")
        print(f"  {name:14s} " + "  |  ".join(parts))

    print(f"== re-scoring the top {POOL}, ranking by each signal ==")
    for name in strategies:
        report(name, results[name])
    print(f"\n  mean time per question including sentence embeddings: "
          f"{sum(timings) / len(timings):.2f}s (max {max(timings):.2f}s)")


if __name__ == "__main__":
    main()
