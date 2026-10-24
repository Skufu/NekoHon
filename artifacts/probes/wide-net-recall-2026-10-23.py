"""Score the wide-net set with dense recall@k. No model, no generation.

Run:
    python artifacts/probes/wide-net-recall-2026-10-23.py
"""
import json
import sys
from collections import defaultdict
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
KS = (5, 10, 20, 50)


def main():
    rows = [json.loads(line) for line in
            DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    indexes = {name: retrieve.load_index(path) for name, path in INDEXES.items()}

    results = []
    for row in rows:
        index = indexes[row["book_id"]]
        ranked = retrieve.rank_chunks(index, row["question"])
        gold = set(row["gold_chunks"])
        rank = None
        for position, (_score, chunk) in enumerate(ranked, 1):
            if chunk["chunk_id"] in gold:
                rank = position
                break
        gold_chapters = {str(c.get("chapter")) for c in index.get("chunks") or []
                         if c["chunk_id"] in gold}
        chapter_rank = None
        for position, (_score, chunk) in enumerate(ranked, 1):
            if str(chunk.get("chapter")) in gold_chapters:
                chapter_rank = position
                break
        results.append({**row, "rank": rank, "chapter_rank": chapter_rank})

    def line(label, subset):
        total = len(subset)
        if not total:
            return
        hits = "  ".join(
            f"@{k}: {sum(1 for r in subset if r['rank'] and r['rank'] <= k):2d}/{total}"
            for k in KS)
        chapters = "  ".join(
            f"@{k}: {sum(1 for r in subset if r['chapter_rank'] and r['chapter_rank'] <= k):2d}/{total}"
            for k in KS)
        mean = sum(r["rank"] or 0 for r in subset) / total
        print(f"  {label:28s} n={total:3d}")
        print(f"      source chunk  {hits}  mean_rank={mean:6.1f}")
        print(f"      any in chapter {chapters}")

    print("== dense recall of the source chunk ==")
    line("all", results)
    print("\n  by register")
    for register in ("literal", "conversational", "vague"):
        line(register, [r for r in results if r["register"] == register])
    print("\n  by book")
    for book_id in INDEXES:
        line(book_id, [r for r in results if r["book_id"] == book_id])
    print("\n  by fold (1 and 2 are the sealed candidates)")
    for fold in sorted({r["fold"] for r in results}):
        line(f"fold {fold}", [r for r in results if r["fold"] == fold])

    print("\n  worst 15")
    for row in sorted(results, key=lambda r: -(r["rank"] or 10 ** 6))[:15]:
        shown = "absent" if row["rank"] is None else row["rank"]
        print(f"    {shown:>7}  {row['id']:34s} {row['question'][:70]}")


if __name__ == "__main__":
    main()
