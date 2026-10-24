"""Query rewriting with the shipped answerer, then dense search. Read-only.

For each wide-net question, ask nekohon_x3 for a short index-friendly rewrite,
embed both the original and the rewrite, and compare four rankings:
original, rewrite, the mean of the two query vectors, and the best score per
chunk from either. Also records rewrite latency.

Run: python artifacts/probes/probe-rewrite-2026-10-23.py
"""
import json
import sys
import time
import urllib.request
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
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "nekohon_x3"
KS = (5, 10, 20)
PROMPT = (
    "Rewrite the question below so a technical book's index would find the "
    "right section. Keep the meaning. Use short technical wording. "
    "Output only the rewritten question, no explanation.\n\nQuestion: "
)


def unit(vector):
    norm = (sum(value * value for value in vector)) ** 0.5
    return [value / norm for value in vector] if norm else vector


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def rewrite(question):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT + question}],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 40},
        "keep_alive": "24h",
    }).encode()
    request = urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode())
    elapsed = time.perf_counter() - started
    text = ((payload.get("message") or {}).get("content") or "").strip()
    return " ".join(text.splitlines()[:1]).strip('" '), elapsed


def rank_of(ranked, gold):
    for position, chunk in enumerate(ranked, 1):
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

    results = []
    latencies = []
    for row in rows:
        index = indexes[row["book_id"]]
        model = index["embedder"]
        chunks = index["chunks"]
        original = unit(retrieve.embed_texts(
            [row["question"]], model, retrieve.ollama_embed, "query")[0])
        text, elapsed = rewrite(row["question"])
        latencies.append(elapsed)
        if not text:
            text = row["question"]
        rewritten = unit(retrieve.embed_texts(
            [text], model, retrieve.ollama_embed, "query")[0])
        mean = unit([(a + b) / 2 for a, b in zip(original, rewritten)])
        gold = set(row["gold_chunks"])

        def ranked_by(vector):
            return [chunk for _score, chunk in sorted(
                ((dot(vector, chunk["_uvec"]), chunk) for chunk in chunks),
                key=lambda pair: pair[0], reverse=True)]

        def fused():
            scored = []
            for chunk in chunks:
                score = max(dot(original, chunk["_uvec"]),
                            dot(rewritten, chunk["_uvec"]))
                scored.append((score, chunk))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [chunk for _score, chunk in scored]

        results.append({
            "row": row,
            "rewrite": text,
            "original": rank_of(ranked_by(original), gold),
            "rewritten": rank_of(ranked_by(rewritten), gold),
            "mean": rank_of(ranked_by(mean), gold),
            "fused": rank_of(fused(), gold),
        })

    print("== rewrites ==")
    for item in results:
        print(f"  {item['row']['id']:22s} {item['rewrite'][:70]}")

    print("\n== source-chunk recall ==")
    for strategy in ("original", "rewritten", "mean", "fused"):
        parts = []
        for register in ("literal", "conversational", "vague", "all"):
            subset = [item for item in results
                      if register == "all" or item["row"]["register"] == register]
            hits = " ".join(
                f"@{k}:{sum(1 for item in subset if (item[strategy] or 999) <= k)}/{len(subset)}"
                for k in KS)
            parts.append(f"{register[:4]} {hits}")
        print(f"  {strategy:10s} " + "  |  ".join(parts))
    print(f"\n  rewrite latency: mean {sum(latencies) / len(latencies):.2f}s "
          f"max {max(latencies):.2f}s")


if __name__ == "__main__":
    main()
