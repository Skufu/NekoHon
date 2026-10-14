"""Probe: refusals with the answer text in the shown set (2026-10-13)."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

import answer as answer_mod

index = json.loads(Path("data/index.json").read_text(encoding="utf-8"))

QUESTIONS = [
    "what is normalization",
    "crud stands for what",
    "types of metadata",
    "hot warm cold data",
    "why should you plan for failure",
]

for question in QUESTIONS:
    seen = []

    def spy(system, user, model):
        completion = answer_mod.ollama_generate(system, user, model)
        seen.append(completion)
        return completion

    body = answer_mod.ask(index, question, generate_fn=spy)
    print("=" * 70)
    print("Q:", question, "| refused:", body["refused"])
    print("RAW COMPLETION:", json.dumps(seen[0][:600], ensure_ascii=False))
    print("FINAL:", json.dumps(body["answer"][:220], ensure_ascii=False))
