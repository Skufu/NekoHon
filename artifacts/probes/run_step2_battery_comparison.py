import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

_INDEX = load_index(INDEX)

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

PROBES = [
    ("what does data engineers need to be pragmatic about", "ch04-012", "pragmatic about flexibility"),
    ("Data engineers need to be pragmatic about?", "ch04-012", "pragmatic about flexibility"),
    ("MAD data landscape", "ch04-020", "ML, AI, and data (MAD) landscape"),
    ("multicloud methodology disadvantages", "ch04-037", "dizzying array"),
]

TYPOS = [
    ("What does CRU stand for?", "ch05-019", "stands for create, read, update, and delete"),
    ("What happens to data after it is extracted in ET?", "ch07-033", "once data is extracted"),
    ("what is a atermark?", "ch08-039", "watermark"),
]

COHERENCE = [
    ("what is MAD data landscape", "ch04-020", r"\bmad\b"),
    ("what is data mesh", "ch03-099", r"data mesh"),
    ("Codd introduced the idea of what", "ch08-051", r"normal form|normalization"),
    ("what is an endpoint in streaming ingestion", "ch02-024", r"endpoint"),
]

FRANCE = "What is the capital of France?"
REFUSAL = "Not in this book."

ANSWER_PINS = {q: chunk for q, chunk in GOLDEN_PINS}
ANSWER_PINS.update({q: chunk for q, chunk, _ in TYPOS + PROBES + COHERENCE})

_SHOWN = {}

def shown_ids(question):
    if question not in _SHOWN:
        _SHOWN[question] = [
            hit["chunk_id"]
            for hit in A.retrieval_context(_INDEX, question)["passages"]
        ]
    return _SHOWN[question]

def judge_ask(question, body):
    notes = []
    first = body["citations"][0]["chunk_id"] if body.get("citations") else "-"
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
            if body["refused"] or phrase.lower() not in body.get("answer", "").lower():
                return False, ["pinned ask must answer with the pin phrase"]
            if first != chunk:
                return False, [f"chunk {first} != {chunk}"]
            return True, notes
    if question == FRANCE:
        if body["refused"] and body.get("answer") == REFUSAL:
            return True, notes
        return False, ["France must be the exact refusal"]
    return False, ["no pin for this question"]

def judge_answer(question, body):
    notes = []
    if question == FRANCE:
        if body["refused"] and body.get("answer") == REFUSAL:
            return True, notes
        return False, ["France must be the exact refusal"]
    chunk = ANSWER_PINS.get(question)
    if chunk is None:
        return False, ["no pin for this question"]
    if body["refused"]:
        return False, ["refused"]
    shown = shown_ids(question)
    cids = [item["chunk_id"] for item in body.get("citations", [])]
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
        if q == question and not re.search(phrase, body.get("answer", ""), re.I):
            return False, [f"answer misses the question's subject {phrase!r}"]
    for q, _, phrase in TYPOS + PROBES:
        if q == question and phrase.lower() not in body.get("answer", "").lower():
            notes.append(f"phrase not in answer: {phrase!r}")
    return True, notes

def run_battery(model, mode):
    print(f"\n==================== RUNNING {model} [{mode} mode] ====================")
    fn = A.ask if mode == "ask" else A.respond
    judge_fn = judge_ask if mode == "ask" else judge_answer

    questions = (
        [q for q, _ in GOLDEN_PINS]
        + [q for q, _, _ in TYPOS]
        + [q for q, _, _ in PROBES]
        + ([q for q, _, _ in COHERENCE] if mode != "ask" else [])
        + [FRANCE]
    )

    passed = 0
    total = len(questions)
    results = []

    for q in questions:
        t0 = time.time()
        body = fn(_INDEX, q, model=model)
        elapsed = round(time.time() - t0, 2)
        ok, notes = judge_fn(q, body)
        if ok:
            passed += 1
        status = "PASS" if ok else "FAIL"
        note_str = "; ".join(notes) if notes else ""
        print(f"[{status}] {q[:45]:<45} ({elapsed:>4}s) {note_str}")
        results.append({
            "question": q,
            "pass": ok,
            "notes": notes,
            "elapsed": elapsed,
            "refused": body.get("refused"),
            "answer": body.get("answer", "")[:120],
        })

    print(f"--- SUMMARY {model} [{mode}]: {passed}/{total} passed ({passed/total*100:.1f}%) ---")
    return {"passed": passed, "total": total, "results": results}

def main():
    report = {}
    for m in ["smallbook_x2g", "smallbook_x2g_mobile"]:
        report[m] = {}
        for mode in ["ask", "answer"]:
            report[m][mode] = run_battery(m, mode)

    out = ROOT / "artifacts" / "evidence" / "battery-comparison-x2g-2026-10-16.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nFull report written to {out}")

if __name__ == "__main__":
    main()
