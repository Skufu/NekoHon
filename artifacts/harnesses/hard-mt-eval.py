"""Hard multi-turn bench: 12 items that require the history, or punish it.

Distinct from the sealed set, which is single-turn, and from the hard bench,
which is mostly single-turn. Scoring is the fair content rule from
`fair_cite.py`: the cited passage must carry the item's terms, and the answer
must show the key fact. Exact chunk identity is a note, not a gate.

The dataset is frozen by `DATASET_SHA256`; the builder is the only writer, and
`tests/test_hard_mt_leakage.py` guards both the hash and the no-overlap claim.

Run: python artifacts/harnesses/hard-mt-eval.py [model]
Writes artifacts/evidence/hard-mt/hard-mt-2026-10-24.model-<model>.json
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from fair_cite import judge_citation, text_lookup  # noqa: E402
from prompt import ANSWER_MODEL, REFUSAL  # noqa: E402
from retrieve import load_index  # noqa: E402

DATASET = ROOT / "artifacts" / "datasets" / "hard-mt-2026-10-24.jsonl"
DATASET_SHA256 = "318d3c4099c327dc933b893de4e333289b19410055059c4d6cdf29c1e5d55ade"
EVIDENCE_DIR = ROOT / "artifacts" / "evidence" / "hard-mt"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}


def dataset_sha256(path=DATASET):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_items(path=DATASET):
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def evaluate(item, index, model):
    started = time.perf_counter()
    result = A.ask(index, item["question"], model=model,
                   history=item.get("history") or None)
    elapsed = round(time.perf_counter() - started, 3)

    answer_text = (result.get("answer") or "").strip()
    refused = bool(result.get("refused"))
    citations = result.get("citations") or []
    cited = [c.get("chunk_id") for c in citations if c.get("chunk_id")]
    reasons = []

    if item["expect"] == "refuse":
        if not refused:
            reasons.append("expected refusal but answered")
        if answer_text != REFUSAL:
            reasons.append(f"answer is not exactly '{REFUSAL}'")
    else:
        if refused:
            reasons.append("expected answer but refused")
        if not reasons:
            ok, detail = judge_citation(cited, text_lookup(index), item.get("terms") or [])
            if not ok:
                reasons.append(f"citation: {detail}")
            key_fact = item.get("key_fact")
            if key_fact and not re.search(key_fact, answer_text, re.IGNORECASE):
                reasons.append(f"answer misses key_fact /{key_fact}/")
            first = cited[0] if cited else None
            if first and first in (item.get("forbid_chunks") or []):
                reasons.append(f"first citation {first} is the history passage")

    return {
        "id": item["id"],
        "category": item["category"],
        "book_id": item["book_id"],
        "question": item["question"],
        "expect": item["expect"],
        "refused": refused,
        "passed": not reasons,
        "first_citation": cited[0] if cited else None,
        "cited": cited,
        "gold_chunks": item.get("gold_chunks") or [],
        "latency_sec": elapsed,
        "answer": answer_text,
        "reasons": reasons,
    }


def main():
    model = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            model = arg
            break
    model = os.environ.get("ANSWER_MODEL") or model or ANSWER_MODEL

    actual = dataset_sha256()
    if actual != DATASET_SHA256:
        print(f"dataset hash changed: {actual} != {DATASET_SHA256}")
        print("re-run the builder, then update DATASET_SHA256 and the leakage test")
        sys.exit(2)

    items = load_items()
    indexes, results = {}, []
    print(f"hard multi-turn — model {model} — {len(items)} items")
    for item in items:
        book = item["book_id"]
        if book not in indexes:
            indexes[book] = load_index(INDEXES[book])
        result = evaluate(item, indexes[book], model)
        results.append(result)
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"[{len(results):2d}/{len(items)}] {mark} {result['latency_sec']:5.2f}s "
              f"{result['id']:16} {item['question'][:52]}")
        for reason in result["reasons"]:
            print(f"          {reason}")

    by_category = {}
    for result in results:
        bucket = by_category.setdefault(result["category"], [0, 0, []])
        bucket[1] += 1
        if result["passed"]:
            bucket[0] += 1
        else:
            bucket[2].append(result["id"])
    passed = sum(1 for r in results if r["passed"])
    mean_latency = sum(r["latency_sec"] for r in results) / len(results)

    print("\n" + "=" * 78)
    print(f"HARD MULTI-TURN 2026-10-24 — model {model}")
    print("=" * 78)
    for category, (ok, total, _) in sorted(by_category.items()):
        print(f"{category:14} {ok}/{total}")
    print(f"{'TOTAL':14} {passed}/{len(results)}  ({passed / len(results):.1%})  "
          f"mean {mean_latency:.2f}s")
    print("=" * 78)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    slug = model.replace("/", "_").replace(":", "_")
    payload = {
        "date": "2026-10-24", "model": model, "dataset": DATASET.name,
        "dataset_sha256": actual, "total_items": len(results),
        "total_passed": passed, "pass_rate": round(passed / len(results), 4),
        "by_category": {k: [v[0], v[1]] for k, v in by_category.items()},
        "mean_latency_sec": round(mean_latency, 3), "results": results,
    }
    out = EVIDENCE_DIR / f"hard-mt-2026-10-24.model-{slug}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"evidence: {out.relative_to(ROOT)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
