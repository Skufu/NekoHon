"""Probe: what the answer to a bare word "endpoint" is made of (2026-10-13)."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import answer as answer_mod
from keywords import anchor_words, postings

index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
word_map = postings(index)
print("'endpoint' df:", len(word_map.get("endpoint", ())))

for question in ("endpoint", "what is an endpoint", "streaming ingestion endpoint",
                 "multicloud methodology disadvantages"):
    seen = {}

    def spy(system, user, model):
        completion = answer_mod.ollama_generate(system, user, model)
        seen["completion"] = completion
        seen["user"] = user
        return completion

    body = answer_mod.ask(index, question, generate_fn=spy)
    print("=" * 70)
    print("Q:", question, "| anchors:", sorted(anchor_words(question, word_map)))
    print("shown:", re.findall(r"chunk_id=([\w.-]+)", seen["user"]))
    print("RAW:", json.dumps(seen["completion"][:400], ensure_ascii=False))
    print("FINAL:", json.dumps(body["answer"][:320], ensure_ascii=False))
