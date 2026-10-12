"""Post-v1 step 2 battery over HTTP: 10 golden + the 2 typos + France.

Run: python artifacts/step2-battery.py    (server.py must be up on :8000)
Writes artifacts/step2-battery.json and artifacts/step2-battery.log.
Chunk pins come from the measured demo sheet artifacts/demo-questions.md
(2026-10-12); the typo asks also pin the phrase their quote must carry.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:8000/ask"
OUT = Path(__file__).resolve().parent / "step2-battery.json"
LOG = Path(__file__).resolve().parent / "step2-battery.log"

# (question, pinned chunk or None for the expected refusal)
GOLDEN_PINS = [
    ("What does CRUD stand for?", "ch05-019"),
    ("What is data ingestion?", "ch07-002"),
    ("What is a watermark?", "ch08-039"),
    ("When is an insert-only table useful?", "ch05-020"),
    ("Where does storage sit in the data engineering lifecycle?", "ch06-001"),
    ("What do source systems provide to the rest of the lifecycle?", "ch02-005"),
    ("How does data architecture relate to enterprise architecture?", "ch03-013"),
    ("What is the difference between batch and streaming?", "ch02-019"),
    ("What happens to data after it is extracted in ETL?", "ch07-033"),
    ("What do transformations do in the data engineering lifecycle?", "ch02-027"),
]
# (question, expected chunk, required phrase)
PROBES = [
    ("what does data engineers need to be pragmatic about", "ch04-012", "pragmatic about flexibility"),
    ("Data engineers need to be pragmatic about?", "ch04-012", "pragmatic about flexibility"),
    ("MAD data landscape", "ch04-020", "ML, AI, and data (MAD) landscape"),
    ("multicloud methodology disadvantages", "ch04-037", "dizzying array"),
]
# (question, required chunk, required phrase)
TYPOS = [
    ("What does CRU stand for?", "ch05-019", "stands for create, read, update, and delete"),
    ("What happens to data after it is extracted in ET?", "ch07-033", "once data is extracted"),
    ("what is a atermark?", "ch08-039", "watermark"),
]
FRANCE = "What is the capital of France?"
REFUSAL = "Not in this book."


def post(question, timeout=180):
    payload = json.dumps({
        "book_id": "fde",
        "question": question,
        "selection": None,
        "mode": "ask",
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
    """(pass, notes) for one ask against the pins."""
    notes = []
    first = body["citations"][0]["chunk_id"] if body["citations"] else "-"
    pins = dict(GOLDEN_PINS)
    if question in pins:
        chunk = pins[question]
        if chunk is None:
            if body["refused"]:
                return True, notes
            notes.append("answered where 2026-10-12 refused")
            return True, notes
        if body["refused"]:
            return False, ["refused"]
        if first != chunk:
            return False, [f"chunk {first} != {chunk}"]
        return True, notes
    for q, chunk, phrase in TYPOS + PROBES:
        if q == question:
            if body["refused"] or phrase.lower() not in body["answer"].lower():
                return False, ["pinned ask must answer with the pin phrase"]
            if first != chunk:
                return False, [f"chunk {first} != {chunk}"]
            return True, notes
    if question == FRANCE:
        if body["refused"] and body["answer"] == REFUSAL:
            return True, notes
        return False, ["France must be the exact refusal"]
    return False, ["no pin for this question"]


def main():
    questions = (
        [q for q, _ in GOLDEN_PINS]
        + [q for q, _, _ in TYPOS]
        + [q for q, _, _ in PROBES]
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
    typo_pass = all(r["pass"] for r in typo_results)
    probe_pass = all(r["pass"] for r in probe_results)
    france_pass = results[-1]["pass"]
    summary = [
        f"golden: {golden_answered}/10 answered, {golden_pass}/10 pass (bar 8)",
        f"typos: {'PASS' if typo_pass else 'FAIL'}",
        f"probes: {'PASS' if probe_pass else 'FAIL'}",
        f"France: {'PASS' if france_pass else 'FAIL'}",
    ]
    for line in summary:
        print(line)
        lines.append(line)
    header = [
        "# post-v1 step 2 battery + rare-word probe — 2026-10-12",
        "# Server: python server.py on :8000; model qwen2.5:7b; index data/index.json",
        "# (nomic-embed-text, 1065 chunks). PASS is judged against pins from",
        "# artifacts/demo-questions.md; typo asks pin ch05-019 / ch07-033 / ch08-039;",
        "# probes pin ch04-012 (pragmatic), ch04-020 (MAD), ch04-037 (multicloud list).",
    ]
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    LOG.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    all_ok = golden_left_ok and typo_pass and probe_pass and france_pass
    print("battery:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
