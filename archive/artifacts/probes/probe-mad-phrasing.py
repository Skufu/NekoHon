"""Probe: "what is MAD data landscape" pulls the data-mesh passage (2026-10-13).

Reproduces the user-reported miss, in-process, no server. Prints for both
phrasings: the dense top five, anchor ranks, every figure-caption cosine, the
seed's gate decision, the passage order the model actually receives, and the
real answer from the live default and the old default.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

import answer as answer_mod
from captions import caption_seed
from retrieve import (
    DEFAULT_EMBEDDER,
    cosine,
    dense_rank,
    embed_texts,
    ollama_embed,
    search,
)

index = json.loads(Path("data/index.json").read_text(encoding="utf-8"))
print("chunks", len(index["chunks"]), "figures", len(index.get("figures") or []))

for question in ("MAD data landscape", "what is MAD data landscape"):
    print("=" * 70)
    print("Q:", question)
    hits = search(index, question, k=5)
    print("dense top-5:")
    for hit in hits:
        print(f"  {hit['chunk_id']} score={hit['score']:.3f}")
    orders = dense_rank(index, question)
    for cid in ("ch04-020", "ch04-019", "ch03-099", "ch03-102"):
        print(f"  dense rank {cid}: {orders.get(cid)}")
    query = embed_texts([question], DEFAULT_EMBEDDER, ollama_embed, "query")[0]
    scored = []
    for figure in index.get("figures") or []:
        vector = figure.get("embedding")
        if vector:
            scored.append((cosine(query, vector), figure))
    scored.sort(key=lambda pair: -pair[0])
    for score, figure in scored[:3]:
        print(f"  caption {figure['id']} {figure['caption'][:48]!r} cos={score:.3f}")
    top = max((hit.get("score") or 0.0) for hit in hits)
    print(f"  best chunk score in set: {top:.3f}")
    print("  caption_seed order:", [h["chunk_id"] for h in caption_seed(index, question, hits)])

    seen = {}

    def fake(system, user, model):
        seen["user"] = user
        return "Not in this book."

    answer_mod.ask(index, question, generate_fn=fake)
    ids = re.findall(r"chunk_id=([\w.-]+)", seen["user"])
    print("  passage order the model receives:", ids)

for model in ("granite4.1:3b", "granite4.1:8b", "qwen2.5:7b"):
    for question in ("what is MAD data landscape", "MAD data landscape"):
        body = answer_mod.ask(index, question, model=model)
        cite = body["citations"][0]["chunk_id"] if body["citations"] else "-"
        flat = " ".join(body["answer"].split())
        print("=" * 70)
        print(model, "|", question, "| refused:", body["refused"], "| cite:", cite)
        print(flat[:220])

print("=" * 70)
print("determinism: granite4.1:3b on 'what is ...' x2 more")
for _ in range(2):
    body = answer_mod.ask(index, "what is MAD data landscape", model="granite4.1:3b")
    cite = body["citations"][0]["chunk_id"] if body["citations"] else "-"
    flat = " ".join(body["answer"].split())
    print("  cite:", cite, "|", flat[:120])
