"""Leakage audit: does any eval question also appear in the finetune corpus?

Read-only. Compares the shipped finetune file against every eval set under
artifacts/datasets/ and datasets/, on three axes:

1. exact question match (case, punctuation and spacing folded)
2. near-duplicate question (difflib ratio >= 0.85)
3. gold-passage overlap (a gold chunk id also appears in a training row)

Passage overlap is not leakage by itself: the student is trained to answer
from passages, and seeing a passage in training is expected. Question overlap
is the leak. Both are printed so the difference is visible.

Run: python artifacts/probes/leakage-audit-2026-10-24.py
Writes artifacts/evidence/leakage-audit/leakage-audit-2026-10-24.{json,log}
"""

import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAIN = ROOT / "data" / "finetune" / "quote-refuse-2026-10-16.train-x2f.jsonl"
DATASETS = ROOT / "artifacts" / "datasets"
EVAL_DIR = ROOT / "artifacts" / "evidence" / "leakage-audit"
NEAR_RATIO = 0.85
NEAR_CONTENT_JACCARD = 0.7
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can",
}

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
CHUNK_RE = re.compile(r"chunk_id=([a-z0-9-]+)")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(folded):
    return {word for word in folded.split() if word not in STOPWORDS}


def load_jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def train_rows(path=TRAIN):
    rows = []
    for record in load_jsonl(path):
        messages = record.get("messages") or []
        user = next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")
        match = QUESTION_RE.search(user)
        question = match.group(1).strip() if match else ""
        rows.append({
            "question": question,
            "folded": fold(question),
            "chunks": sorted(set(CHUNK_RE.findall(user))),
        })
    return rows


def adrian_questions(path):
    for scenario in json.load(path.open(encoding="utf-8")):
        for turn in scenario.get("turns") or []:
            question = turn.get("question") or ""
            if not question and turn.get("selection"):
                question = f"[selection] {turn['selection']}"
            if question:
                yield {
                    "id": scenario.get("id"),
                    "category": scenario.get("category"),
                    "question": question,
                    "gold": [turn["chunk_id"]] if turn.get("chunk_id") else [],
                }


def simple_questions(path, id_key="id"):
    for record in load_jsonl(path):
        question = record.get("question") or record.get("prompt") or ""
        if not question and record.get("selection"):
            question = f"[selection] {record['selection']}"
        if question:
            yield {
                "id": record.get(id_key),
                "category": record.get("category") or record.get("register") or "",
                "question": question,
                "gold": list(record.get("gold_chunks") or []),
            }


def qa_overnight(path):
    data = json.load(path.open(encoding="utf-8"))
    records = data if isinstance(data, list) else data.get("questions", [])
    for record in records:
        question = record.get("question") or ""
        if question:
            yield {
                "id": record.get("id"),
                "category": "overnight",
                "question": question,
                "gold": list(record.get("gold_chunks") or record.get("chunks") or []),
            }


def eval_sets():
    """(name, iterator) for every eval surface that scores the answer model."""
    yield "hard-bench", simple_questions(DATASETS / "hard-bench-2026-10-17.jsonl")
    yield "wide-net", simple_questions(DATASETS / "wide-net-2026-10-23.jsonl")
    yield "adrian", adrian_questions(DATASETS / "adrian-realworld-eval-2026-10-17.json")
    yield "sealed-2026-10-24", simple_questions(DATASETS / "sealed-2026-10-24.jsonl")
    yield "highlight-golden", simple_questions(DATASETS / "highlight-golden-2026-10-16.jsonl")
    yield "qa-overnight", qa_overnight(DATASETS / "qa-questions-overnight.json")


def audit(rows, items):
    train_folded = [row["folded"] for row in rows]
    train_entries = [(text, content(text)) for text in train_folded]
    train_chunks = set()
    for row in rows:
        train_chunks.update(row["chunks"])
    exact, near, passage_only = [], [], []
    total = 0
    gold_seen = 0
    gold_total = 0
    for item in items:
        total += 1
        folded = fold(item["question"])
        if not folded:
            continue
        if folded in train_folded:
            exact.append(item)
        else:
            words = content(folded)
            best = (0.0, "")
            if words:
                for text, text_words in train_entries:
                    if not text_words:
                        continue
                    overlap = len(words & text_words) / len(words | text_words)
                    if overlap < NEAR_CONTENT_JACCARD:
                        continue
                    ratio = difflib.SequenceMatcher(None, folded, text).ratio()
                    if ratio > best[0]:
                        best = (ratio, text)
            if best[0] >= NEAR_RATIO:
                near.append({**item, "ratio": round(best[0], 3), "nearest": best[1]})
        if item["gold"]:
            gold_total += len(item["gold"])
            hits = [chunk for chunk in item["gold"] if chunk in train_chunks]
            gold_seen += len(hits)
            if hits and folded not in train_folded:
                passage_only.append({"id": item["id"], "chunks": hits})
    return {
        "items": total,
        "exact_question_matches": exact,
        "near_duplicate_questions": near,
        "gold_chunks_seen_in_training": {
            "hits": gold_seen,
            "total": gold_total,
            "rate": round(gold_seen / gold_total, 3) if gold_total else None,
        },
        "gold_chunks_without_question_overlap": len(passage_only),
    }


def main():
    if not TRAIN.is_file():
        raise SystemExit(f"missing training file: {TRAIN}")
    rows = train_rows()
    print(f"train rows: {len(rows)} ({TRAIN.name})")
    print(f"distinct questions: {len({row['folded'] for row in rows})}")
    print(f"distinct chunks cited in training: {len({c for row in rows for c in row['chunks']})}")

    report = {"train_rows": len(rows), "sets": {}}
    worst = 0
    for name, items in eval_sets():
        result = audit(rows, items)
        report["sets"][name] = result
        leaks = len(result["exact_question_matches"]) + len(result["near_duplicate_questions"])
        worst = max(worst, leaks)
        print(f"\n[{name}] {result['items']} items")
        print(f"  exact question matches : {len(result['exact_question_matches'])}")
        print(f"  near-duplicates (>= {NEAR_RATIO}) : {len(result['near_duplicate_questions'])}")
        rate = result["gold_chunks_seen_in_training"]["rate"]
        print(f"  gold chunks seen in training: "
              f"{result['gold_chunks_seen_in_training']['hits']}/{result['gold_chunks_seen_in_training']['total']}"
              f" ({rate})")
        for item in result["exact_question_matches"]:
            print(f"    EXACT {item['id']} [{item['category']}]: {item['question'][:80]}")
        for item in result["near_duplicate_questions"]:
            print(f"    NEAR  {item['id']} [{item['category']}] ({item['ratio']}): {item['question'][:70]}")
            print(f"          nearest train: {item['nearest'][:70]}")

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stem = "leakage-audit-2026-10-24"
    (EVAL_DIR / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [f"leakage audit 2026-10-24 — train rows {len(rows)}"]
    for name, result in report["sets"].items():
        lines.append(
            f"{name}: exact={len(result['exact_question_matches'])} "
            f"near={len(result['near_duplicate_questions'])} "
            f"gold_seen={result['gold_chunks_seen_in_training']['rate']}"
        )
    (EVAL_DIR / f"{stem}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nverdict: {'LEAKY' if worst else 'no question overlap'}")
    print(f"evidence: {EVAL_DIR.relative_to(ROOT)}/{stem}.json")
    sys.exit(1 if worst else 0)


if __name__ == "__main__":
    main()
