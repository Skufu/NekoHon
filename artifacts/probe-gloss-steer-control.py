"""Attribute the two refusals in probe-gloss-steer: the same two questions,
with and without the steer, two draws each. No steer run must pass its pin.

Run: python artifacts/probe-gloss-steer-control.py
Writes artifacts/probe-gloss-steer-control.{json,log}.
"""

import json
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

CASES = [
    ("What do transformations do in the data engineering lifecycle?", "ch02-027"),
    ("multicloud methodology disadvantages", "ch04-037"),
]


def main():
    index = load_index(INDEX)
    records = []
    lines = []
    for question, expected in CASES:
        for condition in ("control", "steer"):
            for draw in (1, 2):
                A.SYSTEM = SYSTEM if condition == "control" else STEER
                body = A.ask(index, question)
                first = body["citations"][0] if body["citations"] else {}
                row = {
                    "question": question,
                    "expected": expected,
                    "condition": condition,
                    "draw": draw,
                    "refused": body["refused"],
                    "chunk": first.get("chunk_id"),
                    "quote": first.get("quote") or "",
                    "first_line": body["answer"].split("\n", 1)[0][:120],
                }
                records.append(row)
                lines.append(
                    f"{condition:7} draw{draw} refused={row['refused']!s:5} "
                    f"chunk={row['chunk']} :: {row['first_line']}"
                )
        lines.append("")
    log = "\n".join(lines)
    (HERE / "probe-gloss-steer-control.log").write_text(log, encoding="utf-8")
    (HERE / "probe-gloss-steer-control.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
