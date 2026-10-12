"""Classify the sweep's refusals by cause, with raw completions (2026-10-13).

Writes artifacts/refusal-classes.json. In-process, real model, no server.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import answer as answer_mod
from answer import _quote_in_passage, longest_copied_span

index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
sweep = json.loads((ROOT / "artifacts" / "qa-sweep-default.json").read_text(encoding="utf-8"))
refused = [row["question"] for row in sweep if row["refused"]]
print("refused to classify:", len(refused))

PUNCT = re.compile(r"[^\w\s]")

def punctuation_plain(text):
    return " ".join(PUNCT.sub(" ", (text or "").lower()).split())

def shown_passages(user):
    parts = user.split("Passages:\n", 1)[-1].split("\n\n")
    shown = []
    for part in parts:
        match = re.match(r"\[Ch\. ([^\]]+)\] chunk_id=(\S+)\n(.*)", part, re.S)
        if match:
            shown.append({"chapter": match.group(1), "chunk_id": match.group(2),
                          "text": match.group(3)})
    return shown

rows = []
for question in refused:
    seen = []

    def spy(system, user, model):
        completion = answer_mod.ollama_generate(system, user, model)
        seen.append((completion, user))
        return completion

    body = answer_mod.ask(index, question, generate_fn=spy)
    completion, user = seen[0]
    shown = shown_passages(user)
    stripped = completion.strip()
    kind = "?"

    if stripped == answer_mod.REFUSAL:
        kind = "model-refusal"
    elif not stripped.startswith("[Ch."):
        plain = stripped.strip('"“”')
        if any(_quote_in_passage(plain, p["text"]) for p in shown):
            kind = "no-tag verbatim"
        elif any(longest_copied_span(stripped, p["text"]) for p in shown):
            kind = "no-tag span>=40"
        elif any(punctuation_plain(plain) in punctuation_plain(p["text"]) for p in shown):
            kind = "no-tag punctuation-variant"
        else:
            kind = "no-tag unmatched"
    else:
        match = re.search(r"\[Ch\.\s*([^\]]+)\]\s*(.*)", stripped)
        quoted = re.search(r"[\"“](.+?)[\"”]", match.group(2) if match else stripped)
        quote = (quoted.group(1) if quoted else (match.group(2) if match else stripped)).strip(" .")
        if len(quote) < 40:
            kind = "tag short quote (<40)"
        elif any(_quote_in_passage(quote, p["text"]) for p in shown):
            kind = "tag matched but refused"
        elif any(longest_copied_span(quote, p["text"]) for p in shown):
            kind = "tag span>=40 but refused"
        elif any(punctuation_plain(quote) in punctuation_plain(p["text"]) for p in shown):
            kind = "tag punctuation-variant"
        else:
            kind = "tag unmatched"

    rows.append({
        "question": question,
        "class": kind,
        "refused_still": body["refused"],
        "completion": stripped[:220],
    })

counts = {}
for row in rows:
    counts[row["class"]] = counts.get(row["class"], 0) + 1

print()
for kind, count in sorted(counts.items(), key=lambda item: -item[1]):
    print(f"{count:3}  {kind}")
print()
examples = {}
for row in rows:
    examples.setdefault(row["class"], row)
for kind, row in examples.items():
    print(f"--- {kind}")
    print("   Q:", row["question"])
    print("   C:", row["completion"][:180])

(Root := ROOT / "artifacts" / "refusal-classes.json").write_text(
    json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
print()
print("wrote", Root.name)
