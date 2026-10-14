"""The prefix rule's blast radius: bare single/two-word asks that the
structural trigger would rewrite (no "?", no wh-word). Same pins as the
golden battery. V0 = raw, V2 = "What is X?" before retrieval and prompt.

Run: python artifacts/probes/probe-prefix-bare-terms.py
Writes artifacts/evidence/probe-prefix-bare-terms/probe-prefix-bare-terms.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-prefix-bare-terms"

import answer as A
from retrieve import INDEX, load_index

CASES = [
    ("watermark", "ch08-039"),
    ("CRUD", "ch05-019"),
    ("data ingestion", "ch07-002"),
    ("data mesh", "ch03-099"),
]


def main():
    index = load_index(INDEX)
    records = []
    lines = []
    for question, pin in CASES:
        toe = f"What is {question}?"
        ask_raw = A.ask(index, question)
        ask_pre = A.ask(index, toe)
        ans_raw = A.respond(index, question)
        ans_pre = A.respond(index, toe)

        def cell(body):
            first = body["citations"][0] if body["citations"] else {}
            return {
                "refused": body["refused"],
                "chunk": first.get("chunk_id"),
                "cites": [c["chunk_id"] for c in body["citations"]][:5],
                "head": " ".join(body["answer"].split())[:140],
            }

        record = {
            "question": question,
            "pin": pin,
            "ask_raw": cell(ask_raw),
            "ask_pre": cell(ask_pre),
            "answer_raw": cell(ans_raw),
            "answer_pre": cell(ans_pre),
        }
        records.append(record)
        lines.append(f"== {question}  (pin {pin})")
        lines.append(f"  ask raw : refused={record['ask_raw']['refused']} chunk={record['ask_raw']['chunk']}")
        lines.append(f"  ask pre : refused={record['ask_pre']['refused']} chunk={record['ask_pre']['chunk']}")
        lines.append(f"  ans raw : refused={record['answer_raw']['refused']} cites={record['answer_raw']['cites']}")
        lines.append(f"  ans pre : refused={record['answer_pre']['refused']} cites={record['answer_pre']['cites']}")
        lines.append(f"  ans pre text: {record['answer_pre']['head']}")
        lines.append("")

    log = "\n".join(lines)
    (EVIDENCE / "probe-prefix-bare-terms.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-prefix-bare-terms.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
