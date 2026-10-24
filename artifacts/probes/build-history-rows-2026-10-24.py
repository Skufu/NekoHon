"""SUPERSEDED 2026-10-24 — do not train on the output.

The 400 rows this produced were rejected by the independent audits
(`reports/seed-audit-assembled-2026-10-24-deepseek.md`): 3/40 sampled rows
actually use the history, 10/13 coreference rows resolve the referent to the
wrong subject, and 220/400 duplicate the general corpus once the history is
stripped. Quote integrity is fine (0 bad in-book quotes); the pairing is not.
Kept as a record of what was tried.

Build multi-turn training rows from existing teacher answers.

No new teacher run: every target answer here was already written by
Qwen3.8-27B for the same question and passages. What is new is the history
prefix, exactly as `answer.user_message` renders it at serving time.

Two classes:
- A (history conditioning): final question = the anchor row's own question,
  with 1-2 earlier turns in the prompt. Teaches "history is context, not a
  source" and stops the model re-quoting an old passage.
- B (coreference): final question replaces the subject with it/that, and the
  anchor's question must already be about the same aspect (trade-offs / why /
  how), so the existing answer still fits the question.

Anchors whose question is in the round-2/3 validation list are skipped, so the
held-out set stays held out. Every final question is checked against all eval
sets for exact/near overlap.

Writes data/finetune/quote-refuse-2026-10-24.history.jsonl.
"""

import difflib
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"
CORPUS = FIN / "quote-refuse-2026-10-24.train-r3.jsonl"
VAL = FIN / "val-questions-2026-10-24.txt"
OUT = FIN / "quote-refuse-2026-10-24.history.jsonl"
DATASETS = ROOT / "artifacts" / "datasets"
SEED = 3407
TARGET = 400
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can", "i",
}
ASPECTS = [
    (re.compile(r"trade-?off|overhead|advantage|disadvantage|drawback|downside", re.I),
     ["What are the main trade-offs of that?", "What are its main drawbacks?"]),
    (re.compile(r"\bwhy\b", re.I),
     ["Why does that matter?", "Why is that a problem in practice?"]),
    (re.compile(r"\bhow\b", re.I),
     ["How does that work in practice?", "How would a team apply that?"]),
    (re.compile(r"\bwhat (is|are)\b", re.I),
     ["What does that mean in practice?", "Can you say more about that?"]),
]
FALLBACK = ["What else should a reader know about it?", "Can you say more about that?"]


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


def parts(messages):
    system = next(m["content"] for m in messages if m["role"] == "system")
    user = next(m["content"] for m in messages if m["role"] == "user")
    answer = next(m["content"] for m in messages if m["role"] == "assistant")
    match = QUESTION_RE.search(user)
    question = match.group(1).strip() if match else ""
    body = user.split("Passages:\n", 1)[1] if "Passages:\n" in user else ""
    passages = body.rsplit("\n\n", 1)[0] if body else ""
    return system, user, answer, question, passages


def book_of(passages):
    match = re.search(r"chunk_id=([a-z0-9-]+)", passages or "")
    if not match:
        return "none"
    chunk = match.group(1)
    if chunk.startswith("text"):
        return "ddia"
    if chunk.startswith("chapter-"):
        return "quantization"
    if re.match(r"(ch|app)", chunk):
        return "fde"
    return "other"


def render(system, question, passages, answer, history):
    """Same bytes as answer.user_message, minus the need for an index."""
    prefix = ""
    if history:
        lines = ["Earlier in this conversation (not a source — do not quote it):"]
        for turn in history:
            lines.append(f"User: {turn['question']}")
            lines.append(f"Book: {turn['answer']}")
        prefix = "\n".join(lines) + "\n\n"
    user = (f"{prefix}Question: {question}\n\nPassages:\n{passages}\n\n" + FORMAT_REMINDER)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": answer},
    ]


def load_format_reminder():
    # Import the served constant, not a copy: the format must match inference.
    sys.path.insert(0, str(ROOT))
    import answer  # noqa: E402

    return answer.FORMAT_REMINDER


FORMAT_REMINDER = load_format_reminder()


def eval_questions():
    out = []
    for name in ("hard-bench-2026-10-17.jsonl", "wide-net-2026-10-23.jsonl",
                 "sealed-2026-10-24.jsonl"):
        for record in jsonl(DATASETS / name):
            q = record.get("question") or ("[selection] " + (record.get("selection") or ""))
            if q:
                out.append((name, q))
    for scenario in json.loads((DATASETS / "adrian-realworld-eval-2026-10-17.json").read_text(encoding="utf-8")):
        for turn in scenario.get("turns") or []:
            if turn.get("question"):
                out.append(("adrian", turn["question"]))
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
        if len(words & other_words) / len(words | other_words) < 0.7:
            continue
        if difflib.SequenceMatcher(None, folded, other_folded).ratio() >= 0.85:
            return name, other, "near"
    return None


def main():
    rows = []
    for record in jsonl(CORPUS):
        system, user, answer, question, passages = parts(record["messages"])
        if not question or not answer or not passages:
            continue
        rows.append({"system": system, "answer": answer, "question": question,
                     "passages": passages, "book": book_of(passages)})

    with VAL.open(encoding="utf-8") as fh:
        val_keys = {" ".join(line.lower().split()) for line in fh if line.strip()}

    by_book = {}
    by_word = {}
    for row in rows:
        by_book.setdefault(row["book"], []).append(row)
        for word in content(row["question"]):
            if len(word) > 3:
                by_word.setdefault((row["book"], word), []).append(row)
    for group in by_book.values():
        group.sort(key=lambda r: r["question"])

    corpus = eval_questions()
    existing = {key(r["messages"]) for r in jsonl(CORPUS)}
    rng = random.Random(SEED)
    anchors = [r for r in rows if " ".join(r["question"].lower().split()) not in val_keys]
    rng.shuffle(anchors)

    out, seen = [], set()
    dropped = {"leak": 0, "dup": 0, "no_subject": 0}
    for anchor in anchors:
        if len(out) >= TARGET:
            break
        pool = [r for r in by_book.get(anchor["book"], []) if r["question"] != anchor["question"]]
        if not pool:
            continue
        use_coref = rng.random() < 0.4
        if use_coref:
            # Pick a history turn that shares a subject word with the anchor, so
            # "it" has a referent the final answer is actually about.
            subjects = [w for w in content(anchor["question"])
                        if len(w) > 3 and (anchor["book"], w) in by_word]
            candidates = []
            for word in subjects:
                candidates.extend(r for r in by_word[(anchor["book"], word)]
                                  if r["question"] != anchor["question"])
            if not candidates:
                dropped["no_subject"] += 1
                use_coref = False
                history_rows = [rng.choice(pool)]
            else:
                history_rows = [rng.choice(candidates)]
        else:
            history_rows = [rng.choice(pool)]
        if not use_coref and rng.random() < 0.4:
            second_pool = [r for r in pool if r["question"] != history_rows[0]["question"]]
            if second_pool:
                history_rows.append(rng.choice(second_pool))
        history = [{"question": h["question"], "answer": h["answer"][:400].strip()}
                   for h in history_rows]
        if any(" ".join(turn["question"].lower().split()) in val_keys for turn in history):
            dropped["val_in_history"] = dropped.get("val_in_history", 0) + 1
            continue

        question = anchor["question"]
        if use_coref:
            templates = FALLBACK
            for pattern, options in ASPECTS:
                if pattern.search(anchor["question"]):
                    templates = options
                    break
            question = rng.choice(templates)

        messages = render(anchor["system"], question, anchor["passages"],
                          anchor["answer"], history)
        digest = key(messages)
        if digest in existing or digest in seen:
            dropped["dup"] += 1
            continue
        hit = leaks(question, corpus)
        if hit:
            dropped["leak"] += 1
            continue
        seen.add(digest)
        out.append({"messages": messages, "origin": "coref" if use_coref else "history"})

    with OUT.open("w", encoding="utf-8") as fh:
        for row in out:
            fh.write(json.dumps({"messages": row["messages"]}) + "\n")

    print(f"history rows: {len(out)} -> {OUT.relative_to(ROOT)}")
    print("origin:", {o: sum(1 for r in out if r['origin'] == o) for o in sorted({r['origin'] for r in out})})
    print("dropped:", dropped)
    print("size:", OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
