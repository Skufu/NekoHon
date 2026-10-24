"""Does pseudo-relevance feedback lift the vague-register misses? Read-only.

Baseline: rank by cos(query, chunk). Feedback: take the mean unit vector of the
top-k baseline hits, then rank by cos(q, d) + alpha * cos(mean, d). This is the
cheap, model-free form of query expansion: the first pass says what the reader
probably meant, and the second pass leans toward it.

The score decomposes, so each chunk is scored once and the alpha sweep is
arithmetic on the same numbers.

Run: python artifacts/probes/probe-prf-2026-10-23.py
"""
import json
import sys
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
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5)
FEEDBACK = (1, 3, 5)
KS = (5, 10, 20)


def unit(vector):
    norm = (sum(value * value for value in vector)) ** 0.5
    return [value / norm for value in vector] if norm else vector


def main():
    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexes = {name: retrieve.load_index(path) for name, path in INDEXES.items()}

    prepared = []
    for row in rows:
        index = indexes[row["book_id"]]
        chunks = [chunk for chunk in index.get("chunks") or []
                  if chunk.get("embedding")]
        query = retrieve.embed_texts(
            [row["question"]], index["embedder"], retrieve.ollama_embed, "query")[0]
        q_unit = unit(query)
        base = []
        for chunk in chunks:
            d_unit = chunk.get("_uvec") or unit(chunk["embedding"])
            base.append((sum(a * b for a, b in zip(q_unit, d_unit)), chunk))
        base.sort(key=lambda pair: pair[0], reverse=True)
        gold = set(row["gold_chunks"])
        gold_chapters = {str(chunk.get("chapter")) for chunk in chunks
                         if chunk["chunk_id"] in gold}
        prepared.append({
            "row": row,
            "base": base,
            "chunks": chunks,
            "gold": gold,
            "gold_chapters": gold_chapters,
        })
        print(f"embedded {row['id']}")

    for feedback in FEEDBACK:
        print(f"\n== feedback top {feedback} ==")
        for alpha in ALPHAS:
            scored = []
            for item in prepared:
                if alpha == 0.0:
                    ranked = item["base"]
                else:
                    mean = [0.0] * len(item["base"][0][1]["_uvec"])
                    for _score, chunk in item["base"][:feedback]:
                        for i, value in enumerate(chunk["_uvec"]):
                            mean[i] += value / feedback
                    mean = unit(mean)
                    rescored = []
                    for score, chunk in item["base"]:
                        bonus = sum(a * b for a, b in zip(mean, chunk["_uvec"]))
                        rescored.append((score + alpha * bonus, chunk))
                    rescored.sort(key=lambda pair: pair[0], reverse=True)
                    ranked = rescored
                rank = None
                for position, (_score, chunk) in enumerate(ranked, 1):
                    if chunk["chunk_id"] in item["gold"]:
                        rank = position
                        break
                scored.append((item, rank))
            line = []
            for register in ("literal", "conversational", "vague", "all"):
                subset = [pair for pair in scored
                          if register == "all" or pair[0]["row"]["register"] == register]
                hits = " ".join(
                    f"@{k}:{sum(1 for _i, r in subset if r and r <= k)}/{len(subset)}"
                    for k in KS)
                line.append(f"{register[:4]} {hits}")
            print(f"  alpha {alpha:<4} " + "  |  ".join(line))


if __name__ == "__main__":
    main()
