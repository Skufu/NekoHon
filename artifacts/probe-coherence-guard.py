"""Guard evidence: the two known coherence misses, both models (2026-10-13)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import answer as answer_mod

index = json.loads(Path("data/index.json").read_text(encoding="utf-8"))

CASES = [
    "Codd introduced the idea of what",
    "next Codd introduced the idea of what",
    "what is MAD data landscape",
    "MAD data landscape",
]

for model in ("granite4.1:3b", "qwen2.5:7b"):
    for question in CASES:
        body = answer_mod.ask(index, question, model=model)
        cite = body["citations"][0]["chunk_id"] if body["citations"] else "-"
        flat = " ".join(body["answer"].split())
        print(f"{model} | {question} | cite {cite} | refused {body['refused']}")
        print("   ", flat[:280])
        print()
