"""SUPERSEDED 2026-10-24 — the source set is unusable for quote-first training.

Ten of its 15 quoted sentences exist nowhere in the three books (the ACID one
was attached to an OLTP passage), and all 15 are "explain more simply", a
behaviour the product already handles. Kept as a record; not a data source.
See `reports/seed-audit-specialized-2026-10-24-deepseek.md`.

Convert the 2026-10-17 conversational follow-up set into the served format.

The source rows are real follow-ups with history, but they were written for the
old prose answer mode: a different system prompt, a different user layout, and
no quote-first target. The shipped model is trained and served on
`prompt.SYSTEM` + `answer.user_message` + a quote-first answer, so the rows
cannot be dropped in as they are.

This rebuilds each row:
- system  = prompt.SYSTEM (the served one)
- user    = answer.user_message(follow_up, [cited passage], history)
- target  = [Ch. N] "<verbatim sentence from that passage>" + the old prose gloss

The quote is checked against the index before the row is kept.

Writes data/finetune/quote-refuse-2026-10-24.history-specialized.jsonl.
"""

import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from prompt import SYSTEM  # noqa: E402
from retrieve import load_index  # noqa: E402

SRC = ROOT / "artifacts" / "datasets" / "followup-evil-train-2026-10-17.jsonl"
OUT = ROOT / "data" / "finetune" / "quote-refuse-2026-10-24.history-specialized.jsonl"
VAL = ROOT / "data" / "finetune" / "val-questions-2026-10-24.txt"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
FIELD_RE = {
    "previous_question": re.compile(r"^Previous reader question:\s*(.*)$", re.M),
    "previous_answer": re.compile(r"^Previous answer:\s*(.*?)(?=^Current reader follow-up question:)", re.M | re.S),
    "follow_up": re.compile(r"^Current reader follow-up question:\s*(.*?)(?=^Cited passage quote:)", re.M | re.S),
    "cited_quote": re.compile(r"^Cited passage quote:\s*(.*?)(?=^Section heading:)", re.M | re.S),
    "heading": re.compile(r"^Section heading:\s*(.*?)(?=^Passage context:)", re.M | re.S),
    "context": re.compile(r"^Passage context:\s*(.*?)(?=^Write a direct)", re.M | re.S),
}

NORMALISE = re.compile(r"[^a-z0-9 ]+")
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can", "i",
}


def plain(text):
    return re.sub(r"\s+", " ", NORMALISE.sub(" ", (text or "").lower())).strip()


def content(text):
    return {w for w in plain(text).split() if w not in STOPWORDS and len(w) > 2}


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]


def load_chunks():
    chunks = []
    for book, path in INDEXES.items():
        for chunk in load_index(path).get("chunks", []):
            chunks.append({
                "book": book,
                "chunk_id": chunk.get("chunk_id"),
                "chapter": str(chunk.get("chapter")),
                "text": chunk.get("text") or "",
                "plain": plain(chunk.get("text")),
            })
    return chunks


def find_chunk(chunks, quote, context=""):
    """Locate the source chunk by context first, then by the quoted sentence.

    The old set paraphrased some quotes, so the context is the stronger key:
    it is the book text and matches the index even when the quote was edited.
    """
    for source in (context, quote):
        needle = plain(source)[:120 if source is context else 80]
        if not needle:
            continue
        hits = [c for c in chunks if needle in c["plain"]]
        if hits:
            return hits[0]
    needle = plain(quote)[:40]
    return next((c for c in chunks if needle and needle in c["plain"]), None)


def full_sentence(chunk, quote, gloss=""):
    """The verbatim sentence in the chunk that best covers the quote or gloss.

    Some source quotes were paraphrased, so an exact match does not exist. The
    gloss is grounded in the passage, so its shared words pick the right
    sentence.
    """
    target = content(quote) | content(gloss)
    wanted = plain(quote)
    best, score = "", 0.0
    for sentence in sentences(chunk["text"]):
        if len(sentence) < 40:
            continue
        ratio = difflib.SequenceMatcher(None, wanted, plain(sentence)).ratio()
        overlap = len(target & content(sentence)) / max(1, len(target))
        score_now = max(ratio, overlap)
        if score_now > score:
            best, score = sentence, score_now
    if score >= 0.3:
        return best
    return next((s for s in sentences(chunk["text"]) if len(s) >= 60), "")


def main():
    chunks = load_chunks()
    with VAL.open(encoding="utf-8") as fh:
        val_keys = {" ".join(line.lower().split()) for line in fh if line.strip()}

    rows, stats = [], {"parsed": 0, "no_chunk": 0, "no_sentence": 0,
                       "not_verbatim": 0, "val": 0}
    for record in (json.loads(line) for line in SRC.open(encoding="utf-8") if line.strip()):
        user = next(m["content"] for m in record["messages"] if m["role"] == "user")
        gloss = next(m["content"] for m in record["messages"] if m["role"] == "assistant").strip()
        parsed = {}
        for name, pattern in FIELD_RE.items():
            match = pattern.search(user)
            parsed[name] = match.group(1).strip() if match else ""
        if not all(parsed.get(key) for key in ("previous_question", "previous_answer",
                                               "follow_up", "cited_quote")):
            stats["no_chunk"] += 1
            continue
        stats["parsed"] += 1

        chunk = find_chunk(chunks, parsed["cited_quote"], parsed.get("context", ""))
        if chunk is None:
            stats["no_chunk"] += 1
            continue
        quote = full_sentence(chunk, parsed["cited_quote"], gloss)
        if not quote:
            stats["no_sentence"] += 1
            continue
        if not A._quote_in_passage(quote, chunk["text"]):
            stats["not_verbatim"] += 1
            continue
        if " ".join(parsed["follow_up"].lower().split()) in val_keys:
            stats["val"] += 1
            continue

        history = [{"question": parsed["previous_question"], "answer": parsed["previous_answer"]}]
        passages = [{"chapter": chunk["chapter"], "chunk_id": chunk["chunk_id"], "text": chunk["text"]}]
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": A.user_message(parsed["follow_up"], passages, history)},
            {"role": "assistant", "content": f'[Ch. {chunk["chapter"]}] "{quote}"\n{gloss}'},
        ]
        rows.append({"messages": messages, "category": record.get("category"),
                     "chunk_id": chunk["chunk_id"], "book": chunk["book"]})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps({"messages": row["messages"]}) + "\n")

    print(f"converted: {len(rows)} -> {OUT.relative_to(ROOT)}")
    print("by category:", {c: sum(1 for r in rows if r["category"] == c) for c in sorted({r["category"] for r in rows})})
    print("by book:", {b: sum(1 for r in rows if r["book"] == b) for b in sorted({r["book"] for r in rows})})
    print("dropped:", stats)


if __name__ == "__main__":
    main()
