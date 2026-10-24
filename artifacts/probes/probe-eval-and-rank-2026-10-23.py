"""Two measurements for the 2026-10-23 reranking question. Read-only.

1. key_fact selectivity: does one item's key_fact regex match a different
   item's recorded answer? A fact pattern that fires on other answers cannot
   prove this answer is right.
2. Gold-chunk dense rank: where does the expected chunk sit in the full cosine
   ranking? That is the headroom a reranker could use, measured without one.

Run: python artifacts/probes/probe-eval-and-rank-2026-10-23.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import retrieve  # noqa: E402

DATASET = ROOT / "artifacts" / "datasets" / "hard-bench-2026-10-17.jsonl"
EVIDENCE = (ROOT / "artifacts" / "evidence" / "hard-bench"
            / "hard-bench-2026-10-17.model-nekohon_x3.json")


def load_items():
    with open(DATASET, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def key_fact_test(items, results):
    answers = {}
    for row in results:
        if not row.get("refused") and row.get("answer"):
            answers[row["id"]] = row["answer"]
    print("\n== key_fact selectivity ==")
    print(f"recorded answers: {len(answers)}")
    loose = []
    for item in items:
        pattern = item.get("key_fact")
        if not pattern:
            continue
        hits = []
        for other_id, answer in answers.items():
            if other_id == item["id"]:
                continue
            try:
                if re.search(pattern, answer, re.IGNORECASE):
                    hits.append(other_id)
            except re.error:
                hits.append("<bad regex>")
                break
        if hits:
            loose.append((len(hits), item["id"], pattern[:60], hits[:3]))
    print(f"key_facts matching at least one other answer: {len(loose)}")
    for count, item_id, pattern, sample in sorted(loose, reverse=True)[:8]:
        print(f"  {count:2d}x  {item_id:16s} {pattern!r} e.g. {sample}")


def rank_test(items, index, results):
    chunk_ids = {c["chunk_id"] for c in index.get("chunks") or []}
    cited = {r["id"]: [c.get("chunk_id") for c in (r.get("citations") or [])]
             for r in results}
    print("\n== gold-chunk dense rank ==")
    print(f"index chunks: {len(chunk_ids)}")
    usable = [i for i in items if i.get("gold_chunks") and
              any(g in chunk_ids for g in i["gold_chunks"])]
    skipped = [i["id"] for i in items if i.get("gold_chunks") and
               not any(g in chunk_ids for g in i["gold_chunks"])]
    print(f"graded items: {len(usable)}   unusable labels: {len(skipped)} {skipped[:6]}")
    if not usable:
        return
    rows = []
    for item in usable:
        ranked = retrieve.rank_chunks(index, item["question"])
        best = None
        for position, (_score, chunk) in enumerate(ranked, 1):
            if chunk["chunk_id"] in item["gold_chunks"]:
                best = position
                break
        recovered = any(g in (cited.get(item["id"]) or [])
                         for g in item["gold_chunks"])
        rows.append({
            "id": item["id"],
            "category": item["category"],
            "rank": best,
            "recovered": recovered,
            "handed_chunk": bool(item.get("chunk_id")),
        })

    def bucket(rank):
        if rank is None:
            return ">50"
        if rank <= 5:
            return "1-5"
        if rank <= 10:
            return "6-10"
        if rank <= 20:
            return "11-20"
        if rank <= 50:
            return "21-50"
        return ">50"

    order = ["1-5", "6-10", "11-20", "21-50", ">50"]
    print("\n  dense rank of the best gold chunk, all graded items")
    for name in order:
        print(f"    {name:>6s}: {sum(1 for r in rows if bucket(r['rank']) == name)}")

    print("\n  by category")
    for category in sorted({r["category"] for r in rows}):
        subset = [r for r in rows if r["category"] == category]
        counts = "  ".join(f"{name}:{sum(1 for r in subset if bucket(r['rank']) == name)}"
                           for name in order)
        recovered = sum(1 for r in subset if r["recovered"])
        print(f"    {category:32s} n={len(subset):2d}  {counts}  recovered={recovered}")

    print("\n  retrieval-free items (chunk_id handed to explain): "
          f"{sum(1 for r in rows if r['handed_chunk'])}")
    missed = [r for r in rows if not r["handed_chunk"]
              and (r["rank"] is None or r["rank"] > 5)]
    print(f"  real search items whose gold is outside top 5: {len(missed)}")
    for row in missed:
        shown = "absent" if row["rank"] is None else row["rank"]
        print(f"    {row['id']:16s} rank {shown:<7} recovered={row['recovered']}")

    print("\n  worst labels overall:")
    for row in sorted(rows, key=lambda r: -(r["rank"] or 10 ** 6))[:8]:
        shown = "absent" if row["rank"] is None else row["rank"]
        print(f"    {row['id']:16s} rank {shown} ({row['category']})")


def main():
    items = load_items()
    results = json.load(open(EVIDENCE, encoding="utf-8"))["results"]
    key_fact_test(items, results)
    index = retrieve.load_index(retrieve.INDEX)
    rank_test(items, index, results)


if __name__ == "__main__":
    main()
