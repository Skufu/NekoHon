"""Steer attempt #4, measured: does a gloss-content rule fix meta-glosses
("The passage mentions ...") without breaking the golden pins?

One shape only. Kill criterion: any golden pin loses its chunk, its key, or
refuses -> the steer is dead, report the failure. The MAD asks are judged by
inspection; the battery questions by pin, key, refusal.

Run: python artifacts/probe-gloss-steer.py
Writes artifacts/probe-gloss-steer.{json,log}.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from prompt import SYSTEM
from retrieve import INDEX, load_index

STEER = SYSTEM + (
    "\nThe gloss answers the question. It never describes the passage or the "
    "quote: do not write \"The passage\" or \"The quote\"."
)

MAD_QUESTIONS = ["MAD data landscape", "what is MAD data landscape"]
REFUSAL_QUESTION = "What is the capital of France?"


def battery_lists():
    spec = importlib.util.spec_from_file_location(
        "step2_battery", HERE / "step2-battery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GOLDEN_PINS, module.TYPOS, module.PROBES, module.COHERENCE


def body_of(body):
    first = body["citations"][0] if body["citations"] else {}
    return {
        "refused": body["refused"],
        "answer": body["answer"],
        "chunk": first.get("chunk_id"),
        "quote": first.get("quote") or "",
    }


def main():
    index = load_index(INDEX)
    golden, typos, probes, coherence = battery_lists()
    cases = []
    for question, chunk_id in golden:
        cases.append({"question": question, "chunk_id": chunk_id, "kind": "pin"})
    for question, chunk_id, key in list(typos) + list(probes):
        cases.append({"question": question, "chunk_id": chunk_id, "key": key,
                      "kind": "pin"})
    for question, chunk_id, pattern in coherence:
        cases.append({"question": question, "chunk_id": chunk_id, "key": pattern,
                      "kind": "regex"})
    cases.append({"question": REFUSAL_QUESTION, "kind": "refusal"})

    records = []
    lines = []
    fails = 0
    for case in cases:
        A.SYSTEM = STEER
        body = A.ask(index, case["question"])
        row = body_of(body)
        verdict = "?"
        if case["kind"] == "refusal":
            verdict = "ok" if row["refused"] else "FAIL"
        else:
            pinned = row["chunk"] == case["chunk_id"]
            if case["kind"] == "regex":
                keyed = bool(re.search(case["key"], row["answer"], re.I))
            else:
                key = case.get("key")
                keyed = True if key is None else key.lower() in row["quote"].lower()
            verdict = "ok" if (pinned and keyed and not row["refused"]) else "FAIL"
        if verdict == "FAIL":
            fails += 1
        record = {**case, **row, "verdict": verdict}
        records.append(record)
        lines.append(
            f"{verdict:4} {case['question'][:52]:52} chunk={row['chunk']} "
            f"expected={case.get('chunk_id', '-')} refused={row['refused']}"
        )

    lines.append("")
    lines.append(f"pin/refusal failures: {fails}")
    lines.append("")
    for question in MAD_QUESTIONS:
        A.SYSTEM = STEER
        body = A.ask(index, question)
        row = body_of(body)
        meta = "the passage" in row["answer"].lower()
        lines.append(f"== MAD {question}: meta='the passage' present: {meta}")
        lines.append(f"   {row['answer']}")
        lines.append("")

    log = "\n".join(lines)
    (HERE / "probe-gloss-steer.log").write_text(log, encoding="utf-8")
    (HERE / "probe-gloss-steer.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
