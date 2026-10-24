"""Same chunks, different embedder: does nomic lose the oblique questions? Read-only.

Builds a second in-memory index per book with embeddinggemma, ranks the same
wide-net questions with both, and compares source-chunk recall. Nothing is
written to disk.

Run: python artifacts/probes/probe-embedder-2026-10-23.py
"""
import copy
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
MODELS = ("nomic-embed-text", "embeddinggemma-2:270m-bf16-text")
KS = (5, 10, 20)


def stripped(index, model):
    """A copy with no vectors, so embed_index cannot skip anything."""
    fresh = copy.deepcopy(index)
    fresh["embedder"] = model
    for chunk in fresh.get("chunks") or []:
        chunk.pop("embedding", None)
        chunk.pop("_uvec", None)
    for figure in fresh.get("figures") or []:
        figure.pop("embedding", None)
        figure.pop("_uvec", None)
    return fresh


def slow_embed(texts, model):
    """Embedding with a generous timeout: a cold model load is not a failure."""
    return retrieve.ollama_embed(texts, model, timeout=900)


def main():
    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    built = {}
    for book_id, path in INDEXES.items():
        base = json.loads(path.read_text(encoding="utf-8"))
        for model in MODELS:
            target = base if model == base.get("embedder") else stripped(base, model)
            if model != base.get("embedder"):
                print(f"warm up + embedding {book_id} with {model} ...")
                retrieve.embed_texts(["warmup"], model, slow_embed, "document")
                retrieve.embed_index(target, model=model, embed_fn=slow_embed)
            built[(book_id, model)] = target

    for model in MODELS:
        print(f"\n== {model} ==")
        per_register = {"literal": [], "conversational": [], "vague": []}
        for row in rows:
            index = built[(row["book_id"], model)]
            ranked = retrieve.rank_chunks(index, row["question"], model=model,
                                          embed_fn=slow_embed)
            gold = set(row["gold_chunks"])
            rank = None
            for position, (_score, chunk) in enumerate(ranked, 1):
                if chunk["chunk_id"] in gold:
                    rank = position
                    break
            per_register[row["register"]].append(rank)
        for register, ranks in per_register.items():
            total = len(ranks)
            hits = " ".join(
                f"@{k}:{sum(1 for r in ranks if r and r <= k)}/{total}" for k in KS)
            mean = sum(r or 0 for r in ranks) / total
            print(f"  {register:16s} {hits}  mean={mean:6.1f}")
        everything = [r for ranks in per_register.values() for r in ranks]
        hits = " ".join(
            f"@{k}:{sum(1 for r in everything if r and r <= k)}/{len(everything)}"
            for k in KS)
        print(f"  {'all':16s} {hits}")


if __name__ == "__main__":
    main()
