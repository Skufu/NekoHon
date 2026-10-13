"""Stage 1 retest corpus: canonical on/off, same process, same index.

The pre-declared delta cells from query-canonicalization-2026-10-13.md:
recorded retest asks, the bare junk asks (refusal surface), a typo pair,
and a bare cue question (plain-register interplay).

Run: python artifacts/probe-canonical-retest-2026-10-13.py
Writes artifacts/probe-canonical-retest-2026-10-13.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

ASK_CASES = [
    "types of metadata",
    "hot warm cold data",
    "dark matter data",
    "capital of France",
    "IOPS",
    "watermark",
    "data mesh in simple words",
    "atermark",
    "What is normalization",
]
ANSWER_CASES = [
    "hot warm cold data",
    "dark matter data",
    "data mesh in simple words",
]


def cell(body):
    first = body["citations"][0] if body["citations"] else {}
    return {
        "refused": body["refused"],
        "chunk": first.get("chunk_id"),
        "head": " ".join(body["answer"].split())[:150],
    }


def main():
    index = load_index(INDEX)
    records = []
    lines = []
    for mode, cases in (("ask", ASK_CASES), ("answer", ANSWER_CASES)):
        run = A.ask if mode == "ask" else A.respond
        for question in cases:
            on = cell(run(index, question))
            off = cell(run(index, question, canonical=False))
            same = (on["refused"], on["chunk"]) == (off["refused"], off["chunk"])
            record = {"mode": mode, "question": question, "on": on, "off": off,
                      "same": same}
            records.append(record)
            flag = "same" if same else "CHANGED"
            lines.append(f"[{mode}] {flag:8} {question!r}")
            lines.append(
                f"   on : refused={on['refused']} chunk={on['chunk']} {on['head'][:100]}"
            )
            lines.append(
                f"   off: refused={off['refused']} chunk={off['chunk']} {off['head'][:100]}"
            )
    log = "\n".join(lines)
    (HERE / "probe-canonical-retest-2026-10-13.log").write_text(log, encoding="utf-8")
    (HERE / "probe-canonical-retest-2026-10-13.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
