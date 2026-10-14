"""The nonrelational "?" case: same question with and without the question
mark, full pipeline, live. Dumps the pool, the quote, the citation chunks,
and locates both candidate sentences in the index.

Run: python artifacts/probes/probe-nonrelational-ask.py
Writes artifacts/evidence/probe-nonrelational-ask/probe-nonrelational-ask.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-nonrelational-ask"

import answer as A
from retrieve import INDEX, load_index

QUESTIONS = ["What is nonrelational database", "What is nonrelational database?"]
MARKERS = [
    "Enter nonrelational or NoSQL databases",
    "NoSQL remains vague in 2022",
    "abandon the relational paradigm",
]


def main():
    index = load_index(INDEX)
    chunks = index["chunks"]
    marker_chunks = {}
    for marker in MARKERS:
        marker_chunks[marker] = [
            c["chunk_id"] for c in chunks if marker.lower() in c["text"].lower()
        ]

    records = []
    lines = ["== marker sentences live in"]
    for marker, ids in marker_chunks.items():
        lines.append(f"  {ids} :: {marker}")
    lines.append("")

    for question in QUESTIONS:
        ctx = A.retrieval_context(index, question)
        pool = [
            {"chunk_id": h["chunk_id"],
             "score": None if h.get("score") is None else round(float(h["score"]), 4)}
            for h in ctx["passages"]
        ]
        calls = []

        def logged(system, user, model, *a, **kw):
            out = A.ollama_generate(system, user, model, *a, **kw)
            calls.append(" ".join(out.split()))
            return out

        body = A.ask(index, question, generate_fn=logged)
        record = {
            "question": question,
            "pool": pool,
            "raw": calls,
            "answer": body["answer"],
            "citations": [c["chunk_id"] for c in body["citations"]],
            "quotes": [c.get("quote") for c in body["citations"]],
            "figures": [f.get("id") for f in body["figures"]],
            "refused": body["refused"],
        }
        records.append(record)
        lines.append(f"== {question}")
        for p in pool:
            lines.append(f"  [{p['chunk_id']} {p['score']}]")
        lines.append(f"  RAW   : {record['raw'][0][:600] if record['raw'] else '(none)'}")
        lines.append(f"  cites : {record['citations']}  figures: {record['figures']}")
        lines.append(f"  quotes: {record['quotes']}")
        lines.append("")

    log = "\n".join(lines)
    (EVIDENCE / "probe-nonrelational-ask.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-nonrelational-ask.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
