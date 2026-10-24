"""Post-v1 step 2 battery over HTTP: 10 golden + the 2 typos + France.

Run: python artifacts/harnesses/step2-battery.py    (server.py must be up on :8000)
With BATTERY_MODE=answer the same asks run through the free-generation mode
and four coherence probes are added; output goes to step2-battery-answer.*.
Writes artifacts/evidence/step2-battery/step2-battery.json and
artifacts/evidence/step2-battery/step2-battery.log.
Chunk pins come from the measured demo sheet artifacts/datasets/demo-questions.md
(2026-10-12); the typo asks also pin the phrase their quote must carry.
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

import answer as A
import fair_cite
from retrieve import INDEX, load_index

URL = "http://127.0.0.1:8000/ask"
MODE = os.environ.get("BATTERY_MODE", "ask")
OUT = ROOT / "artifacts" / "evidence" / "step2-battery" / (
    "step2-battery.json" if MODE == "ask" else f"step2-battery-{MODE}.json"
)
LOG = OUT.with_suffix(".log")

# Pins, terms and expected phrases live in one JSON file so the fairness test
# can check them without importing this script (its name has a hyphen).
# A citation passes when the cited passage carries the question's terms; `pin`
# is the historical chunk and is a note, not the gate. See fair_cite.py.
PIN_FILE = ROOT / "artifacts" / "datasets" / "battery-pins.json"
_PINS = json.loads(PIN_FILE.read_text(encoding="utf-8"))

GOLDEN_PINS = [(item["question"], item["pin"]) for item in _PINS["golden"]]
PROBES = [(item["question"], item["pin"], item["phrase"]) for item in _PINS["probes"]]
TYPOS = [(item["question"], item["pin"], item["phrase"]) for item in _PINS["typos"]]

TERMS = {item["question"]: item.get("terms") or [] for group in ("golden", "probes", "typos")
         for item in _PINS[group]}
PINNED = {item["question"]: item["pin"] for group in ("golden", "probes", "typos")
          for item in _PINS[group]}
# The user's coherence bar: the answer must carry the question's own subject.
# The phrase is a regex; the book's own wording wins where it differs from a
# paraphrase (ch08-051 says "Codd introduced the idea of normal forms", so
# both namings are correct). Answer mode only.
COHERENCE = [
    ("what is MAD data landscape", "ch04-020", r"\bmad\b"),
    ("what is data mesh", "ch03-099", r"data mesh"),
    ("Codd introduced the idea of what", "ch08-051", r"normal form|normalization"),
    ("what is an endpoint in streaming ingestion", "ch02-024", r"endpoint"),
]
FRANCE = "What is the capital of France?"
REFUSAL = "Not in this book."


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


def answered_with(body, phrase):
    return (not body["refused"]) and phrase.lower() in body["answer"].lower()


def judge(question, body):
    """(pass, notes) for one ask against the pins.

    Fair rule (2026-10-24): the cited passage must answer the question. The
    historical pin is a note. A model that quotes a different valid passage is
    not failed for it; a model that quotes a passage without the subject is.
    """
    if MODE != "ask":
        return judge_answer(question, body)
    notes = []
    if question == FRANCE:
        if body["refused"] and body["answer"] == REFUSAL:
            return True, notes
        return False, ["France must be the exact refusal"]
    if body["refused"]:
        return False, ["refused"]
    cited = [c.get("chunk_id") for c in body["citations"] if c.get("chunk_id")]
    if not cited:
        return False, ["no citations"]
    shown = shown_ids(question)
    stray = [cid for cid in cited if cid not in shown]
    if stray:
        return False, [f"citation not among the shown passages: {stray}"]
    terms = TERMS.get(question) or []
    ok, detail = fair_cite.judge_citation(cited, text_of, terms)
    if not ok:
        return False, [detail]
    pin = PINNED.get(question)
    if pin and pin not in cited:
        notes.append(f"pin {pin} not cited (cites {cited}); cited passage carries {terms}")
    for q, _, phrase in TYPOS + PROBES:
        if q == question and phrase.lower() not in body["answer"].lower():
            return False, [f"answer misses pinned phrase {phrase!r}"]
    return True, notes


ANSWER_PINS = {q: chunk for q, chunk in GOLDEN_PINS}
ANSWER_PINS.update({q: chunk for q, chunk, _ in TYPOS + PROBES + COHERENCE})
_INDEX = None
_TEXT_OF = None
_SHOWN = {}


def shown_ids(question):
    """The passages the engine shows for this question, recomputed locally.

    Answer mode's contract is grounded-in-retrieved: a citation must point
    at a shown passage. Ask mode now uses the same rule, so a model that
    quotes one of the shown passages is not failed for picking a different
    one than the 2026-10-12 pin.
    """
    global _INDEX, _TEXT_OF
    if _INDEX is None:
        _INDEX = load_index(INDEX)
        _TEXT_OF = fair_cite.text_lookup(_INDEX)
    if question not in _SHOWN:
        _SHOWN[question] = [
            hit["chunk_id"]
            for hit in A.retrieval_context(_INDEX, question)["passages"]
        ]
    return _SHOWN[question]


def text_of(chunk_id):
    """Chunk text for the fair citation rule; builds the index on first use."""
    global _INDEX, _TEXT_OF
    if _TEXT_OF is None:
        _INDEX = load_index(INDEX)
        _TEXT_OF = fair_cite.text_lookup(_INDEX)
    return _TEXT_OF(chunk_id)


def judge_answer(question, body):
    """Answer mode: free prose. Pass = answered, with citations pointing
    only at shown passages and the pinned chunk among them. The coherence
    probes also fail when the answer does not carry the question's subject;
    for the other asks a missing phrase is a note, because a free answer may
    paraphrase."""
    notes = []
    if question == FRANCE:
        if body["refused"] and body["answer"] == REFUSAL:
            return True, notes
        return False, ["France must be the exact refusal"]
    chunk = ANSWER_PINS.get(question)
    if chunk is None:
        return False, ["no pin for this question"]
    if body["refused"]:
        return False, ["refused"]
    shown = shown_ids(question)
    cids = [item["chunk_id"] for item in body["citations"]]
    if not cids:
        return False, ["no citations"]
    stray = [cid for cid in cids if cid not in shown]
    if stray:
        return False, [f"citation not among the shown passages: {stray}"]
    if chunk not in shown:
        return False, [f"pinned chunk {chunk} was not shown; shown {shown}"]
    notes.append(
        "pinned chunk cited" if chunk in cids
        else f"pinned chunk shown, not cited (cites {cids})"
    )
    for q, _, phrase in COHERENCE:
        if q == question and not re.search(phrase, body["answer"], re.I):
            return False, [f"answer misses the question's subject {phrase!r}"]
    for q, _, phrase in TYPOS + PROBES:
        if q == question and phrase.lower() not in body["answer"].lower():
            notes.append(f"phrase not in answer: {phrase!r}")
    return True, notes


def main():
    questions = (
        [q for q, _ in GOLDEN_PINS]
        + [q for q, _, _ in TYPOS]
        + [q for q, _, _ in PROBES]
        + ([q for q, _, _ in COHERENCE] if MODE != "ask" else [])
        + [FRANCE]
    )
    lines = []
    results = []
    for question in questions:
        body, seconds = post(question)
        ok, notes = judge(question, body)
        first = body["citations"][0]["chunk_id"] if body["citations"] else "-"
        status = "PASS" if ok else "FAIL"
        line = (f"{status} {seconds:6.2f}s refused={int(body['refused'])} "
                f"{first:8} {question}")
        if notes:
            line += "\n     " + "; ".join(notes)
        print(line)
        lines.append(line)
        results.append({
            "question": question,
            "seconds": seconds,
            "pass": ok,
            "notes": notes,
            "response": body,
        })
    golden_results = results[:len(GOLDEN_PINS)]
    golden_answered = sum(1 for r in golden_results if not r["response"]["refused"])
    golden_pass = sum(1 for r in golden_results if r["pass"])
    golden_left_ok = golden_pass >= 8
    typo_results = results[len(GOLDEN_PINS):len(GOLDEN_PINS) + len(TYPOS)]
    probe_results = results[
        len(GOLDEN_PINS) + len(TYPOS):len(GOLDEN_PINS) + len(TYPOS) + len(PROBES)
    ]
    coherence_results = (
        results[len(GOLDEN_PINS) + len(TYPOS) + len(PROBES):-1]
        if MODE != "ask" else []
    )
    typo_pass = all(r["pass"] for r in typo_results)
    probe_pass = all(r["pass"] for r in probe_results)
    coherence_pass = all(r["pass"] for r in coherence_results)
    france_pass = results[-1]["pass"]
    summary = [
        f"golden: {golden_answered}/10 answered, {golden_pass}/10 pass (bar 8)",
        f"typos: {'PASS' if typo_pass else 'FAIL'}",
        f"probes: {'PASS' if probe_pass else 'FAIL'}",
    ]
    if MODE != "ask":
        summary.append(f"coherence: {'PASS' if coherence_pass else 'FAIL'}")
    summary.append(f"France: {'PASS' if france_pass else 'FAIL'}")
    for line in summary:
        print(line)
        lines.append(line)
    header = [
        f"# post-v1 step 2 battery + rare-word probe — 2026-10-12; mode {MODE}",
        f"# Server: python server.py on :8000; model {os.environ.get('ANSWER_MODEL', 'qwen2.5:7b')}; index data/index.json",
        "# (nomic-embed-text, 1042 chunks). PASS is judged against pins from",
        "# artifacts/datasets/demo-questions.md; typo asks pin ch05-019 / ch07-033 / ch08-039;",
        "# probes pin ch04-012 (pragmatic), ch04-020 (MAD), ch04-037 (multicloud list).",
    ]
    if MODE != "ask":
        header.append(
            "# answer mode: pin must appear among the citations; coherence probes"
            " pin ch04-020, ch03-099, ch08-051, ch02-024 and require the subject word."
        )
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    LOG.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    all_ok = (
        golden_left_ok
        and typo_pass
        and probe_pass
        and france_pass
        and (coherence_pass if MODE != "ask" else True)
    )
    print("battery:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
