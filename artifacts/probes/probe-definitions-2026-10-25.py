"""Does the definition rule put a defining passage first? No model call.

For each question, rank the five passages with `answer.prefer_definitions` and
report where the first *defining* passage sits, before and after. A passage
defines the term when the phrase is followed within 60 characters by
is/are/refers to/means/stands for.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from retrieve import load_index, search  # noqa: E402

INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
QUESTIONS = [
    ("fde", "what is an api"),
    ("fde", "what is a schema"),
    ("fde", "what is change data capture"),
    ("fde", "what is data ingestion"),
    ("fde", "what is data management"),
    ("fde", "what is a watermark"),
    ("fde", "what is reverse ETL"),
    ("fde", "what is data architecture"),
    ("quantization", "what is per-tensor quantization"),
    ("ddia", "what is a transaction"),
    ("ddia", "what is replication"),
    ("ddia", "what is an api"),
]


def first_definition(passages, tokens):
    for index, passage in enumerate(passages, 1):
        if A.definition_passage(passage, tokens):
            return index
    return None


def main():
    indexes, rows = {}, []
    for book, question in QUESTIONS:
        if book not in indexes:
            indexes[book] = load_index(INDEXES[book])
        tokens = A._definition_tokens(question)
        hits = search(indexes[book], question, k=5)
        after = A.prefer_definitions(question, [dict(hit) for hit in hits])
        before_rank = first_definition(hits, tokens)
        after_rank = first_definition(after, tokens)
        rows.append({
            "book": book, "question": question,
            "tokens": tokens,
            "before_rank": before_rank,
            "after_rank": after_rank,
            "before_top": hits[0]["chunk_id"] if hits else None,
            "after_top": after[0]["chunk_id"] if after else None,
        })

    for row in rows:
        marker = "MOVE" if row["after_rank"] != row["before_rank"] else ""
        print(f'{row["book"]:12} {row["question"]:36} '
              f'before {str(row["before_rank"]):>4} after {str(row["after_rank"]):>4} '
              f'{row["before_top"]} -> {row["after_top"]} {marker}')

    improved = sum(1 for r in rows if r["after_rank"] and (not r["before_rank"] or r["after_rank"] < r["before_rank"]))
    worsened = sum(1 for r in rows if r["before_rank"] and (not r["after_rank"] or r["after_rank"] > r["before_rank"]))
    at_top = sum(1 for r in rows if r["after_rank"] == 1)
    print(f"\ndefining passage at rank 1: before {sum(1 for r in rows if r['before_rank'] == 1)}/{len(rows)} "
          f"after {at_top}/{len(rows)}  improved {improved}  worsened {worsened}")

    out = ROOT / "artifacts" / "evidence" / "definition-preference-2026-10-25.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    print("evidence:", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
