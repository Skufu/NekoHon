"""Round 5 corpus: x3 + the audited pilot rows + the cross-book trap rows.

Why each source is in:

- `quote-refuse-2026-10-17.train-x3.jsonl` (844) — the shipped model's corpus.
- `pilot-rows-2026-10-24.jsonl` — only `premise_trap` and `simplify`. The
  entity-relation rows are excluded: the audit rejected 11 of 18 in round 1 and
  9 of 18 in round 2, because the passages are re-sent every turn and the
  history was never load-bearing.
- `trap-crossbook-rows-2026-10-24.jsonl` (11) — the same trap behaviour on
  quantization and ddia, which the fde-only corpus never covered.

Dedupe is by full-message sha256, so a row only survives once. Writes
`data/finetune/quote-refuse-2026-10-25.train-r5.jsonl` and a stats file.
"""

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"
SOURCES = [
    (FIN / "quote-refuse-2026-10-17.train-x3.jsonl", None),
    (FIN / "pilot-rows-2026-10-24.jsonl", {"premise_trap", "simplify"}),
    (FIN / "trap-crossbook-rows-2026-10-24.jsonl", None),
]
CLASSES = {
    FIN / "pilot-rows-2026-10-24.jsonl": FIN / "pilot-seeds-2026-10-24.jsonl",
    FIN / "trap-crossbook-rows-2026-10-24.jsonl": FIN / "trap-crossbook-seeds-2026-10-24.jsonl",
}
OUT = FIN / "quote-refuse-2026-10-25.train-r5.jsonl"
STATS = ROOT / "artifacts" / "evidence" / "hard-mt" / "r5-corpus-stats.json"
REFUSAL = "Not in this book."


def digest(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main():
    rows, seen = [], set()
    stats = Counter()
    for path, allowed in SOURCES:
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
        class_of = {}
        if path in CLASSES:
            class_of = {seed["id"]: seed["class"]
                        for seed in jsonl(CLASSES[path])}
            # Rows carry no id, so match by their user turn.
            by_user = {seed["user"]: seed["class"] for seed in jsonl(CLASSES[path])}
        for record in jsonl(path):
            messages = record["messages"]
            if allowed is not None:
                user = next(m["content"] for m in messages if m["role"] == "user")
                row_class = by_user.get(user)
                if row_class not in allowed:
                    stats["skipped_class"] += 1
                    continue
            key = digest(messages)
            if key in seen:
                stats["duplicate"] += 1
                continue
            seen.add(key)
            rows.append({"messages": messages})
            stats["kept"] += 1
            if messages[-1]["content"].strip() == REFUSAL:
                stats["refusal"] += 1

    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8")
    refusals = sum(1 for row in rows if row["messages"][-1]["content"].strip() == REFUSAL)
    summary = {
        "rows": len(rows),
        "refusals": refusals,
        "refusal_share": round(refusals / len(rows), 4),
        "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "sources": [path.name for path, _ in SOURCES],
        "dropped": dict(stats),
    }
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"rows {len(rows)}  refusals {refusals} ({summary['refusal_share']:.1%})")
    print("dropped:", dict(stats))
    print("sha256:", summary["sha256"])
    print("->", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
