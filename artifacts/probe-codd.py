"""Probe: "Codd introduced the idea of what" answers about normalization (2026-10-13)."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import answer as answer_mod
from keywords import postings
from retrieve import dense_rank, search

index = json.loads(Path("data/index.json").read_text(encoding="utf-8"))

print("chunks containing 'codd':")
for chunk in index["chunks"]:
    if re.search(r"\bcodd\b", chunk.get("text") or "", re.I):
        flat = re.sub(r"\s+", " ", chunk["text"])
        print(" ", chunk["chunk_id"], "|", flat[:300])

question = "Codd introduced the idea of what"
print("=" * 70)
print("Q:", question)
for hit in search(index, question, k=5):
    print(f"  dense {hit['chunk_id']} score={hit['score']:.3f}")
ranks = dense_rank(index, question)
word_map = postings(index)
positions = word_map.get("codd") or []
print("  'codd' df:", len(positions))
for pos in positions[:8]:
    cid = index["chunks"][pos]["chunk_id"]
    print(f"  codd chunk {cid} dense rank {ranks.get(cid)}")

seen = {}


def fake(system, user, model):
    seen["user"] = user
    return "Not in this book."


answer_mod.ask(index, question, generate_fn=fake)
print("  passage order the model receives:", re.findall(r"chunk_id=([\w.-]+)", seen["user"]))

for model in ("qwen2.5:7b", "granite4.1:3b"):
    for q in ("Codd introduced the idea of what", "next Codd introduced the idea of what"):
        body = answer_mod.ask(index, q, model=model)
        cite = body["citations"][0]["chunk_id"] if body["citations"] else "-"
        print("=" * 70)
        print("model:", model, "| Q:", q, "| refused:", body["refused"], "| cite:", cite)
        print(" ".join(body["answer"].split())[:450])
