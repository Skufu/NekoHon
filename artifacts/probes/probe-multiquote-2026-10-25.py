"""Does the multi-quote rule add a useful second quote? Model run, one flag.

Run twice and diff:
    python artifacts/probes/probe-multiquote-2026-10-25.py > before.json
    MULTI_QUOTE=1 python artifacts/probes/probe-multiquote-2026-10-25.py > after.json

Questions are the low-margin asks measured on 2026-10-25 (top1-top2 under 0.02)
plus two mid-margin controls.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from retrieve import load_index, search  # noqa: E402

QUESTIONS = [
    ("fde", "What is change data capture?"),
    ("fde", "What is a schema?"),
    ("fde", "What is data architecture?"),
    ("fde", "What is orchestration?"),
    ("fde", "What is data management?"),
    ("fde", "What is reverse ETL?"),
]


def main():
    indexes, rows = {}, []
    for book, question in QUESTIONS:
        if book not in indexes:
            indexes[book] = load_index(ROOT / "data" / ("index.json" if book == "fde" else f"index.{book}.json"))
        hits = search(indexes[book], question, k=2)
        margin = round(hits[0]["score"] - hits[1]["score"], 4) if len(hits) > 1 else None
        started = time.perf_counter()
        result = A.ask(indexes[book], question, model="nekohon_q35_2b_x3_2e")
        rows.append({
            "question": question,
            "margin": margin,
            "seconds": round(time.perf_counter() - started, 1),
            "refused": bool(result.get("refused")),
            "citations": [c.get("chunk_id") for c in result.get("citations") or []],
            "answer": result.get("answer") or "",
        })
        print(json.dumps(rows[-1], ensure_ascii=False))

    with_second = sum(1 for r in rows if len(r["citations"]) > 1)
    print(json.dumps({
        "questions": len(rows),
        "answers_with_two_or_more_quotes": with_second,
        "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
    }))


if __name__ == "__main__":
    main()
