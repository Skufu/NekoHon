"""How much of the 60-item bench survives a stricter key_fact rule? Read-only.

Current rule (hard-bench.py:294): the answer must match the key_fact regex,
which is an alternation. A broad alternative ("load", "available") lets a wrong
answer pass. Variant A keeps only alternatives that are not shared with other
items' answers. Variant B keeps only the longest alternative.

Scores the recorded x3 answers, so no model runs.

Run: python artifacts/probes/probe-strict-keyfact-2026-10-23.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "artifacts" / "datasets" / "hard-bench-2026-10-17.jsonl"
EVIDENCE = (ROOT / "artifacts" / "evidence" / "hard-bench"
            / "hard-bench-2026-10-17.model-nekohon_x3.json")
SHARED_LIMIT = 2


def alternatives(pattern):
    return [part.strip() for part in pattern.split("|") if part.strip()]


def main():
    items = [json.loads(line) for line in
             DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = json.loads(EVIDENCE.read_text(encoding="utf-8"))["results"]
    answers = {row["id"]: (row.get("answer") or "") for row in results}
    passed = {row["id"]: row.get("passed") for row in results}

    rows = []
    for item in items:
        pattern = item.get("key_fact")
        if not pattern:
            continue
        own = answers.get(item["id"], "")
        others = [answer for other_id, answer in answers.items()
                  if other_id != item["id"] and answer]
        current = bool(re.search(pattern, own, re.I)) and passed.get(item["id"])

        specificity = []
        for alternative in alternatives(pattern):
            try:
                if not re.search(alternative, own, re.I):
                    continue
                shared = sum(1 for answer in others
                             if re.search(alternative, answer, re.I))
            except re.error:
                continue
            specificity.append((alternative, shared))

        # Strict = the pattern still matches its own answer, and the pattern as
        # a whole is not a free pass: at most SHARED_LIMIT other answers match.
        others_matching = sum(1 for answer in others
                              if re.search(pattern, answer, re.I))
        strict = bool(re.search(pattern, own, re.I)) and others_matching <= SHARED_LIMIT
        longest = max(alternatives(pattern), key=len)
        try:
            longest_ok = bool(re.search(longest, own, re.I)) and bool(passed.get(item["id"]))
        except re.error:
            longest_ok = False

        rows.append({
            "id": item["id"],
            "current": current,
            "strict": strict,
            "longest": longest_ok,
            "pattern": pattern,
            "others_matching": others_matching,
            "kept": [alternative for alternative, _ in specificity],
            "dropped": [],
        })

    print(f"items with key_fact: {len(rows)}")
    print(f"pass under current rule:  {sum(1 for row in rows if row['current'])}")
    print(f"pass under strict rule:   {sum(1 for row in rows if row['strict'])}")
    print(f"pass under longest-only:  {sum(1 for row in rows if row['longest'])}")

    print("\nitems the strict rule would fail (these are the loose ones):")
    for row in rows:
        if row["current"] and not row["strict"]:
            print(f"  {row['id']:18s} other_answers_matching={row['others_matching']:2d} "
                  f"pattern={row['pattern']!r}")

    print("\nitems where a broad alternative is shared by many answers:")
    broad = []
    for row in rows:
        for alternative in alternatives(row["pattern"]):
            shared = 0
            for other_id, answer in answers.items():
                if other_id == row["id"] or not answer:
                    continue
                try:
                    if re.search(alternative, answer, re.I):
                        shared += 1
                except re.error:
                    pass
            if shared >= 4:
                broad.append((shared, row["id"], alternative))
    for shared, item_id, alternative in sorted(broad, reverse=True)[:15]:
        print(f"  {shared:2d}x  {item_id:18s} {alternative!r}")


if __name__ == "__main__":
    main()
