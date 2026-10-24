"""Sealed eval: 30 questions authored on 2026-10-24 from passages the x2f
training file never saw.

This is the held-out set for finetune round 2. It is frozen by the sha256 in
`SEALED_SHA256`, and `tests/test_eval_leakage.py` fails if the file changes or
if any question overlaps the training corpus.

Run: python artifacts/harnesses/sealed-eval.py [model]
Writes artifacts/evidence/sealed-eval/sealed-eval-2026-10-24.model-<model>.json
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

import answer as A
from prompt import ANSWER_MODEL, REFUSAL
from retrieve import load_index

DATASET = ROOT / "artifacts" / "datasets" / "sealed-2026-10-24.jsonl"
SEALED_SHA256 = "7f1dfd6a3ebf0db10832bf739f9175b81c6947e7a80565edb68e666b39b64889"
EVIDENCE_DIR = ROOT / "artifacts" / "evidence" / "sealed-eval"
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
    result = A.ask(
        index,
        item["question"],
        model=model,
        history=item.get("history") or None,
    )
    elapsed = round(time.perf_counter() - started, 3)

    reasons = []
    refused = bool(result.get("refused"))
    answer_text = (result.get("answer") or "").strip()
    citations = result.get("citations") or []
    cited = [c.get("chunk_id") for c in citations if c.get("chunk_id")]
    gold = item.get("gold_chunks") or []
    pin_hit = bool(gold) and any(chunk in cited for chunk in gold)

    # Two metrics, deliberately separate. `passed` asks whether the reader got
    # the content (key_fact present, no refusal). `pin_hit` asks whether the
    # exact authored chunk came first. Retrieval returns sibling chunks that
    # carry the same fact, and scoring the model on which sibling won measured
    # retrieval noise, not answers (both models scored 19/30 that way, every
    # miss a sibling).
    if item["expect"] == "refuse":
        if not refused:
            reasons.append("expected refusal but answered")
        if answer_text != REFUSAL:
            reasons.append(f"answer is not exactly '{REFUSAL}'")
    else:
        if refused:
            reasons.append("expected answer but refused")
        key_fact = item.get("key_fact")
        if key_fact and not re.search(key_fact, answer_text, re.IGNORECASE):
            reasons.append(f"answer misses key_fact /{key_fact}/")

    return {
        "id": item["id"],
        "category": item["category"],
        "book_id": item.get("book_id"),
        "question": item["question"],
        "expect": item["expect"],
        "refused": refused,
        "passed": not reasons,
        "pin_hit": pin_hit,
        "gold_chunks": gold,
        "cited": cited,
        "latency_sec": elapsed,
        "answer": answer_text,
        "citations": citations,
        "reasons": reasons,
    }


def main():
    model = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            model = arg
            break
    model = os.environ.get("ANSWER_MODEL") or model or ANSWER_MODEL

    items = load_items()
    indexes = {}
    results = []
    print(f"sealed eval — model {model} — {len(items)} items")
    for item in items:
        book = item.get("book_id") or "fde"
        if book not in indexes:
            indexes[book] = load_index(INDEXES[book])
        result = evaluate(item, indexes[book], model)
        results.append(result)
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"[{len(results):2d}/{len(items)}] {mark} {result['latency_sec']:5.2f}s "
              f"{result['id']:16} {item['question'][:56]}")
        for reason in result["reasons"]:
            print(f"          {reason}")

    passed = sum(1 for r in results if r["passed"])
    scored_for_pin = [r for r in results if r["expect"] == "answer"]
    pin_hits = sum(1 for r in scored_for_pin if r["pin_hit"])
    by_category = {}
    for result in results:
        bucket = by_category.setdefault(result["category"], [0, 0, []])
        bucket[1] += 1
        if result["passed"]:
            bucket[0] += 1
        else:
            bucket[2].append(result["id"])
    mean_latency = sum(r["latency_sec"] for r in results) / len(results)

    print("\n" + "=" * 78)
    print(f"SEALED EVAL 2026-10-24 — model {model}")
    print("=" * 78)
    for category, (ok, total, _) in sorted(by_category.items()):
        print(f"{category:18} {ok}/{total}")
    print(f"{'TOTAL':18} {passed}/{len(results)}  ({passed / len(results):.1%})  "
          f"mean {mean_latency:.2f}s")
    print(f"{'pin hit':18} {pin_hits}/{len(scored_for_pin)} answered items cite the authored chunk")
    print("=" * 78)

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    slug = model.replace("/", "_").replace(":", "_")
    payload = {
        "date": "2026-10-24",
        "model": model,
        "dataset": DATASET.name,
        "dataset_sha256": dataset_sha256(),
        "total_items": len(results),
        "total_passed": passed,
        "pass_rate": round(passed / len(results), 4),
        "pin_hits": pin_hits,
        "pin_total": len(scored_for_pin),
        "mean_latency_sec": round(mean_latency, 3),
        "results": results,
    }
    out = EVIDENCE_DIR / f"sealed-eval-2026-10-24.model-{slug}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"evidence: {out.relative_to(ROOT)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
