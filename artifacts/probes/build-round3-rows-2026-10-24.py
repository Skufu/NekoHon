"""Assemble unused teacher captures into round-3 training rows.

Sources already on disk (no new teacher run):
- teacher-capture-2026-10-15.jsonl + teacher-capture-results-qwen38-27b.jsonl
- teacher-capture-ask-2026-10-15.jsonl + teacher-capture-results-ask-qwen38-27b.jsonl
- quote-refuse-2026-10-16.train-x2g.jsonl (rows not already in x3)

Drops: no answer, truncated (finish != stop), answer that is neither a quote
nor the exact refusal, and anything already in the x3 corpus. Then checks the
question against every eval set for exact/near overlap.

Writes data/finetune/quote-refuse-2026-10-24.round3-extra.jsonl and prints a
summary. Read-only on every existing file.
"""

import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"
OUT = FIN / "quote-refuse-2026-10-24.round3-extra.jsonl"
X3 = FIN / "quote-refuse-2026-10-17.train-x3.jsonl"
DATASETS = ROOT / "artifacts" / "datasets"
REFUSAL = "Not in this book."
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can",
}


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(text):
    return {w for w in fold(text).split() if w not in STOPWORDS}


def key(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def question_of(user):
    match = QUESTION_RE.search(user or "")
    return match.group(1).strip() if match else ""


def load_x3_keys():
    return {key(r["messages"]) for r in jsonl(X3)}


def eval_questions():
    """Every question a gate scores, for the leakage check."""
    out = []
    for name in ("hard-bench-2026-10-17.jsonl", "wide-net-2026-10-23.jsonl",
                 "sealed-2026-10-24.jsonl"):
        path = DATASETS / name
        for record in jsonl(path):
            q = record.get("question") or ("[selection] " + (record.get("selection") or ""))
            if q:
                out.append((name, q))
    adrian = json.loads((DATASETS / "adrian-realworld-eval-2026-10-17.json").read_text(encoding="utf-8"))
    for scenario in adrian:
        for turn in scenario.get("turns") or []:
            q = turn.get("question") or ""
            if q:
                out.append(("adrian", q))
    return out


def leaks(question, corpus):
    folded = fold(question)
    words = content(question)
    for name, other in corpus:
        other_folded = fold(other)
        if folded == other_folded:
            return name, other, "exact"
        other_words = content(other)
        if not words or not other_words:
            continue
        overlap = len(words & other_words) / len(words | other_words)
        if overlap >= 0.7 and difflib.SequenceMatcher(None, folded, other_folded).ratio() >= 0.85:
            return name, other, "near"
    return None


def main():
    x3 = load_x3_keys()
    corpus = eval_questions()
    seen = set()
    rows = []
    stats = {"no_answer": 0, "truncated": 0, "bad_shape": 0, "duplicate": 0, "leak": 0}

    def add(system, user, answer, origin):
        if not answer:
            stats["no_answer"] += 1
            return
        answer = answer.strip()
        if answer != REFUSAL and not answer.startswith("[Ch."):
            stats["bad_shape"] += 1
            return
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ]
        digest = key(messages)
        if digest in x3 or digest in seen:
            stats["duplicate"] += 1
            return
        question = question_of(user)
        hit = leaks(question, corpus) if question else None
        if hit:
            stats["leak"] += 1
            print(f"  LEAK {hit[0]}: {question[:70]!r} ~ {hit[1][:60]!r}")
            return
        seen.add(digest)
        rows.append({"messages": messages, "origin": origin})

    results = {r["id"]: r for r in jsonl(FIN / "teacher-capture-results-qwen38-27b.jsonl")}
    for prompt in jsonl(FIN / "teacher-capture-2026-10-15.jsonl"):
        result = results.get(prompt["id"]) or {}
        if result.get("finish") not in (None, "stop"):
            stats["truncated"] += 1
            continue
        add(prompt["system"], prompt["user"], result.get("answer"), "capture-recapture")

    results_ask = {r["id"]: r for r in jsonl(FIN / "teacher-capture-results-ask-qwen38-27b.jsonl")}
    for prompt in jsonl(FIN / "teacher-capture-ask-2026-10-15.jsonl"):
        result = results_ask.get(prompt["id"]) or {}
        if result.get("finish") not in (None, "stop"):
            stats["truncated"] += 1
            continue
        add(prompt["system"], prompt["user"], result.get("answer"), "capture-new-ask")

    for record in jsonl(FIN / "quote-refuse-2026-10-16.train-x2g.jsonl"):
        messages = record["messages"]
        system = next(m["content"] for m in messages if m["role"] == "system")
        user = next(m["content"] for m in messages if m["role"] == "user")
        answer = next(m["content"] for m in messages if m["role"] == "assistant")
        add(system, user, answer, "x2g-extra")

    with OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps({"messages": row["messages"]}) + "\n")

    print(f"\nnew rows: {len(rows)} -> {OUT.relative_to(ROOT)}")
    print("origins:", {o: sum(1 for r in rows if r['origin'] == o) for o in sorted({r['origin'] for r in rows})})
    print("dropped:", stats)
    print("size:", OUT.stat().st_size, "bytes")
    sys.exit(0)


if __name__ == "__main__":
    main()
