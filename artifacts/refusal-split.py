"""Split the model-refusals: was the question's evidence shown? (2026-10-13)."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import answer as answer_mod
from answer import _rarest_word
from keywords import postings
from preprocess import words as tokenize

index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
word_map = postings(index)
classes = json.loads((ROOT / "artifacts" / "refusal-classes.json").read_text(encoding="utf-8"))
refusals = [row for row in classes if row["class"] == "model-refusal"]
print("model-refusals:", len(refusals))


def shown_passages(user):
    parts = user.split("Passages:\n", 1)[-1].split("\n\n")
    shown = []
    for part in parts:
        match = re.match(r"\[Ch\. ([^\]]+)\] chunk_id=(\S+)\n(.*)", part, re.S)
        if match:
            shown.append({"chunk_id": match.group(2), "text": match.group(3)})
    return shown


with_guard = []
without_guard = []
other = []

for row in refusals:
    question = row["question"]
    seen = []

    def spy(system, user, model):
        completion = answer_mod.ollama_generate(system, user, model)
        seen.append(user)
        return completion

    answer_mod.ask(index, question, generate_fn=spy)
    shown = shown_passages(seen[0])
    shown_text = " ".join(p["text"] for p in shown).lower()
    guard = _rarest_word(question, word_map)
    candidate = guard
    if not candidate:
        rare_any = [
            word for word in set(tokenize(question))
            if 0 < len(word_map.get(word, ())) <= 20
        ]
        candidate = rare_any[0] if rare_any else ""
    hit = bool(candidate) and re.search(rf"\b{re.escape(candidate)}\b", shown_text) is not None
    entry = {
        "question": question,
        "word": candidate,
        "chunks": [p["chunk_id"] for p in shown],
        "completion": row["completion"][:140],
    }
    if not candidate:
        other.append(entry)
    elif hit:
        with_guard.append(entry)
    else:
        without_guard.append(entry)

print("evidence word shown:", len(with_guard))
print("evidence word NOT shown:", len(without_guard))
print("no candidate word:", len(other))
print()
for entry in with_guard[:20]:
    print("SHOWN  ", entry["question"], "| word:", entry["word"], "|", entry["chunks"][:3])
print()
for entry in without_guard[:20]:
    print("ABSENT ", entry["question"], "| word:", entry["word"], "|", entry["chunks"][:3])

(ROOT / "artifacts" / "refusal-split.json").write_text(
    json.dumps({"shown": with_guard, "absent": without_guard, "none": other},
               indent=2, ensure_ascii=False), encoding="utf-8")
print()
print("wrote refusal-split.json")
