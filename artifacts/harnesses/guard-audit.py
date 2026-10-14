"""Guard audit: every swap the coherence guard made across the sweep set (2026-10-13).

Run: python artifacts/harnesses/guard-audit.py
Reads artifacts/datasets/qa-sweep-default.json (the sweep set).
Writes artifacts/evidence/guard-audit/guard-audit.json.
"""

import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import answer as answer_mod

index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
sweep = json.loads((ROOT / "artifacts" / "datasets" / "qa-sweep-default.json").read_text(encoding="utf-8"))
questions = [row["question"] for row in sweep]

real = answer_mod.parse_completion
swaps = []
count = {"asks": 0, "swapped": 0, "refused": 0, "guard_word_none": 0}

for question in questions:
    record = {}

    def spy(completion, passages, figures=None, anchors=None, rare_word=""):
        pre = real(completion, passages, figures, anchors, "")
        post = real(completion, passages, figures, anchors, rare_word)
        record["pre"] = pre
        record["post"] = post
        record["word"] = rare_word
        return post

    with mock.patch.object(answer_mod, "parse_completion", spy):
        body = answer_mod.ask(index, question, model="qwen2.5:7b")
    count["asks"] += 1
    if body["refused"]:
        count["refused"] += 1
        continue
    if not record.get("word"):
        count["guard_word_none"] += 1
        continue
    pre = record["pre"]
    post = record["post"]
    if pre["refused"] or not post["citations"]:
        continue
    pre_quote = pre["citations"][0]["quote"] if pre["citations"] else ""
    post_quote = post["citations"][0]["quote"]
    if pre_quote != post_quote:
        count["swapped"] += 1
        swaps.append({
            "question": question,
            "word": record["word"],
            "before": pre_quote[:160],
            "after": post_quote[:160],
        })

print(json.dumps(count))
for swap in swaps:
    print("=" * 60)
    print(swap["question"], "| guard word:", swap["word"])
    print("  before:", swap["before"])
    print("  after :", swap["after"])

(ROOT / "artifacts" / "evidence" / "guard-audit" / "guard-audit.json").write_text(
    json.dumps(swaps, indent=2, ensure_ascii=False), encoding="utf-8")
print("wrote guard-audit.json |", len(swaps), "swaps")
