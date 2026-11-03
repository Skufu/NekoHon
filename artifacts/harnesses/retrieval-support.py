"""Strict vs fair retrieval scoring — which passage did the reader actually need?

    python3 artifacts/harnesses/retrieval-support.py --embedder gemma
    python3 artifacts/harnesses/retrieval-support.py --embedder nomic

`retrieval-recall.py` scores one hand-picked gold chunk. That is why gemma's
top-1 looked broken: five of its nine "losses" were the chunk immediately next to
the gold, and one was a different page that lists the same five stages. For a
reader, a neighbouring chunk of the same section is usually the same passage; for
an answer, any chunk carrying the row's key_fact answers the question.

So every hit is scored twice:

  exact@1      the gold chunk is rank 1                       (the strict metric)
  support@1    rank 1 is exact, a neighbour (position ±1 in the same source), or
               contains the row's key_fact                   (what the reader needs)
  support@5    the same, anywhere in the top five

Writes artifacts/experiments/gemma/support-<embedder>.json.
"""

import argparse
import json
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import retrieve  # noqa: E402

GEMMA_ROOT = Path("/Users/adriangabriellfrancisco/workspace/github.com/Skufu/ask-this-book-gemma")
NOMIC_ROOT = Path("/Users/adriangabriellfrancisco/workspace/github.com/Skufu/ask-this-book")
DATASET = "artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl"
MODELS = {
    "gemma": ("embeddinggemma-2:270m-bf16-text", "task: search result | query: ", GEMMA_ROOT),
    "nomic": ("nomic-embed-text", "search_query: ", NOMIC_ROOT),
}


def load_index(path):
    conn = sqlite3.connect(path)
    ids, vectors, position, source, text = [], [], {}, {}, {}
    rows = conn.execute(
        "select chunk_id, embedding, source, text from chunks "
        "where embedding is not null order by position"
    )
    for index, (chunk_id, blob, src, body) in enumerate(rows):
        vector = np.array(struct.unpack(f"<{len(blob) // 8}d", blob), dtype=np.float32)
        ids.append(chunk_id)
        vectors.append(vector / (np.linalg.norm(vector) + 1e-9))
        position[chunk_id] = index
        source[chunk_id] = src or ""
        text[chunk_id] = body or ""
    return ids, np.ascontiguousarray(np.stack(vectors)), position, source, text


def neighbours(position, source, gold_ids):
    """Gold chunks plus the chunk on either side within the same source."""
    out = set(gold_ids)
    for gold in gold_ids:
        if gold not in position:
            continue
        for step in (-1, 1):
            index = position[gold] + step
            for chunk_id, pos in position.items():
                if pos == index and source.get(chunk_id) == source.get(gold):
                    out.add(chunk_id)
    return out


def supports(chunk_id, row, position, source, text, gold_ids):
    """Does this chunk give the reader the answer, not just the hand-picked one?"""
    if chunk_id in gold_ids:
        return "exact"
    if chunk_id in neighbours(position, source, gold_ids):
        return "neighbour"
    fact = (row.get("key_fact") or "").strip()
    if fact and fact.lower() in (text.get(chunk_id) or "").lower():
        return "key_fact"
    return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedder", choices=sorted(MODELS), default="gemma")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    model, prefix, root = MODELS[args.embedder]
    rows = [json.loads(line) for line in open(GEMMA_ROOT / DATASET)]
    rows = [r for r in rows if not r.get("expected_refusal") and r.get("gold_chunk_ids")]

    cache, results = {}, []
    for row in rows:
        book = row["book"]
        if book not in cache:
            cache[book] = load_index(root / "data" / f"{book}.sqlite")
        ids, matrix, position, source, text = cache[book]
        query = retrieve.ollama_embed(
            [prefix + retrieve.normalize(row["question"])], model
        )[0]
        q = np.asarray(query, dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-9
        order = np.argsort(-(matrix @ q))[: args.limit]
        top = [ids[i] for i in order]
        gold = set(row["gold_chunk_ids"])
        reasons = [supports(chunk_id, row, position, source, text, gold) for chunk_id in top]
        results.append({
            "id": row["id"],
            "question": row["question"],
            "gold": sorted(gold),
            "top": top,
            "reasons": reasons,
            "exact1": reasons[0] == "exact",
            "support1": bool(reasons[0]),
            "support5": any(reasons),
            "support5_at": next((i + 1 for i, r in enumerate(reasons) if r), None),
        })

    total = len(results)
    summary = {
        "embedder": args.embedder,
        "model": model,
        "rows": total,
        "exact@1": sum(r["exact1"] for r in results),
        "support@1": sum(r["support1"] for r in results),
        "support@5": sum(r["support5"] for r in results),
        "exact@1_pct": round(100 * sum(r["exact1"] for r in results) / total, 1),
        "support@1_pct": round(100 * sum(r["support1"] for r in results) / total, 1),
        "support@5_pct": round(100 * sum(r["support5"] for r in results) / total, 1),
    }
    print(json.dumps(summary, indent=1))
    print("\nstrict misses that a neighbour or key_fact rescues:")
    for r in results:
        if not r["exact1"] and r["support1"]:
            print(f"  {r['id']:26} {r['reasons'][0]:10} :: {r['question'][:58]}")
    print("\nunsupported at rank 1:")
    for r in results:
        if not r["support1"]:
            print(f"  {r['id']:26} {r['question'][:58]}")

    out = GEMMA_ROOT / "artifacts" / "experiments" / "gemma" / f"support-{args.embedder}.json"
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
