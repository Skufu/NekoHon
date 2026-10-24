"""Print what actually ranked above the gold chunk for the worst misses.

Read-only. For each question whose gold chunk sits past rank 50, show the top
three passages so a reader can judge whether the gold label was the only
correct answer.

Run: python artifacts/probes/probe-miss-audit-2026-10-23.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import retrieve  # noqa: E402

DATASET = ROOT / "artifacts" / "datasets" / "wide-net-2026-10-23.jsonl"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
TARGETS = {
    "quantization-3-conversational", "quantization-5-literal",
    "quantization-5-conversational", "quantization-7-vague",
    "fde-2-conversational", "ddia-5-vague",
}


def main():
    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexes = {name: retrieve.load_index(path) for name, path in INDEXES.items()}
    for row in rows:
        if row["id"] not in TARGETS:
            continue
        index = indexes[row["book_id"]]
        ranked = retrieve.rank_chunks(index, row["question"])
        chunk_map = {chunk["chunk_id"]: chunk for chunk in index["chunks"]}
        print(f"\n{'=' * 74}\n{row['id']}  [{row['register']}]")
        print(f"Q: {row['question']}")
        gold = chunk_map.get(row["source_chunk"], {})
        print(f"GOLD {row['source_chunk']}  heading={gold.get('heading')!r}")
        print(f"     {' '.join((gold.get('text') or '').split())[:180]}")
        for position, (score, chunk) in enumerate(ranked[:3], 1):
            print(f"  #{position} {score:.3f} {chunk['chunk_id']}  "
                  f"heading={chunk.get('heading')!r}")
            print(f"      {' '.join((chunk.get('text') or '').split())[:180]}")


if __name__ == "__main__":
    main()
