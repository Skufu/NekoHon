"""Overnight QA sweep: run question sets through the live server (2026-10-13).

Run: python artifacts/harnesses/qa-sweep.py <label>   (server must be up on :8000)
With SWEEP_MODE=answer the same questions run through the free-generation
mode and coherence means the answer carries the question's rarest book word.
Writes artifacts/runs/qa-sweep/qa-sweep-<label>.{json,log}. The question
set: the authored set (datasets/qa-questions-overnight.json), what-is asks
for the 120 rarest book words, and what-is asks for up to 60 distinct headings.
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.retrieval.keywords import RARE_DF, postings
from engine.retrieval.preprocess import STOPWORDS, stem

URL = "http://127.0.0.1:8000/ask"
MODE = os.environ.get("SWEEP_MODE", "ask")
label = sys.argv[1] if len(sys.argv) > 1 else "default"
OUT = ROOT / "artifacts" / "runs" / "qa-sweep" / f"qa-sweep-{label}.json"
LOG = ROOT / "artifacts" / "runs" / "qa-sweep" / f"qa-sweep-{label}.log"

index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
word_map = postings(index)

questions = []

authored = ROOT / "artifacts" / "datasets" / "qa-questions-overnight.json"
if authored.exists():
    for item in json.loads(authored.read_text(encoding="utf-8")):
        if isinstance(item, dict) and item.get("question"):
            questions.append(item["question"])

rare = sorted(
    (
        word
        for word, positions in word_map.items()
        if 0 < len(positions) <= RARE_DF and word.isalpha() and len(word) >= 3
    ),
    key=lambda word: (len(word_map[word]), word),
)
for word in rare[:120]:
    questions.append(f"what is {word}")

headings = []
seen_headings = set()
for chunk in index["chunks"]:
    heading = (chunk.get("heading") or "").strip()
    if heading and heading.lower() not in seen_headings and 3 < len(heading) <= 60:
        seen_headings.add(heading.lower())
        headings.append(heading)
for heading in headings[:60]:
    questions.append(f"what is {heading}")

unique = []
seen_questions = set()
for question in questions:
    key = question.strip().lower()
    if key and key not in seen_questions:
        seen_questions.add(key)
        unique.append(question.strip())

print("questions:", len(unique))


def rarest_word(question, word_map):
    """The question's rarest book word: lowest document frequency, then
    alphabetical. Stopwords are skipped — their df says how the book talks,
    not what the question is about ("what is data engineering" must not
    guard on "what"; measured in the 2026-10-13 sweep: guard words were
    mostly function words before this filter). Empty when no content word is
    in the book. The answer is coherent when it carries this word (answer
    mode) or the quote does (ask mode)."""
    words = set(re.findall(r"[a-z0-9]+", question.lower())) - STOPWORDS
    candidates = [
        (len(word_map[word]), word) for word in words if word_map.get(word)
    ]
    if not candidates:
        return ""
    return min(candidates)[1]


def carries(answer, word):
    """True when the text carries the word, inflections included.

    A word-for-word regex flags "relate" missing when the answer says
    "relates" or "differ" when it says "differs"; the vendored Snowball
    stemmer (stage 9) makes the coherence check morphology-proof: the guard
    word and each answer word compare as stems."""
    wanted = stem(word)
    return any(stem(token) == wanted for token in re.findall(r"[a-z]+", answer.lower()))


def post(question, timeout=180):
    payload = json.dumps({
        "book_id": "fde",
        "question": question,
        "selection": None,
        "mode": MODE,
    }).encode("utf-8")
    request = urllib.request.Request(
        URL, data=payload, headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body, round(time.perf_counter() - started, 2)


rows = []
for position, question in enumerate(unique, start=1):
    body, seconds = post(question)
    cite = body["citations"][0]["chunk_id"] if body["citations"] else "-"
    quote = body["citations"][0].get("quote", "") if body["citations"] else ""
    answer = body.get("answer") or ""
    guard = rarest_word(question, word_map)
    if MODE == "ask":
        gloss = next((line for line in answer.splitlines()[1:] if line.strip()), "")
        coherent = (not guard) or (not body["refused"] and carries(quote, guard))
    else:
        # answer mode: the free prose is what is measured; the question's
        # rarest book word must appear in the answer, not in a quote. A free
        # answer has no gloss line.
        gloss = ""
        coherent = (not guard) or (not body["refused"] and carries(answer, guard))
    rows.append({
        "question": question,
        "refused": body["refused"],
        "cite": cite,
        "quote": quote[:200],
        "gloss": gloss[:160],
        "seconds": seconds,
        "guard_word": guard,
        "coherent": bool(coherent),
    })
    if position % 25 == 0:
        print(f"  {position}/{len(unique)}")

refused = [row for row in rows if row["refused"]]
incoherent = [row for row in rows if not row["refused"] and not row["coherent"]]
glossless = [
    row for row in rows
    if MODE == "ask" and not row["refused"] and not row["gloss"]
]

lines = [
    f"# qa sweep — {label} — {len(rows)} asks — mode {MODE}",
    f"# refused: {len(refused)} | incoherent: {len(incoherent)} | no gloss: {len(glossless)}",
    "",
    "## incoherent (answer/quote missing the question's rarest book word)",
]
for row in incoherent:
    lines.append(
        f"- {row['question']} | {row['cite']} | guard {row['guard_word']} | {row['quote'][:120]}"
    )
lines.append("")
lines.append("## refused")
for row in refused:
    lines.append(f"- {row['question']} | {row['cite']} | {row['quote'][:100]}")
lines.append("")
lines.append("## glossless")
for row in glossless:
    lines.append(f"- {row['question']} | {row['cite']}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines[:2]))
print("wrote", OUT.name, "and", LOG.name)
