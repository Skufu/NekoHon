"""Build the highlight-word golden set and the next-finetune pack.

The reader marks 1-3 words and presses explain. The question is
`answer.highlight_query`. The gold completion quotes one sentence from the
pinned chunk, then repeats that sentence. No gloss is invented.

Held-out (24 chunks) is the golden eval and is never written into the train
file. Train (72 chunks) is a different chunk set. Prefer content words that
occur in at least 8 chunks.

Stdlib plus existing repo modules. Does not call Ollama or any network.

Run: python artifacts/probes/build-highlight-golden-2026-10-16.py
Writes:
  artifacts/datasets/highlight-golden-2026-10-16.jsonl
  artifacts/datasets/highlight-train-2026-10-16.jsonl
  data/finetune/highlight-addon-2026-10-16.jsonl
"""

import difflib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from preprocess import STOPWORDS
from prompt import SYSTEM

INDEX = ROOT / "data" / "index.json"
SEALED = ROOT / "artifacts" / "datasets" / "sealed-forms.json"
OUT_GOLDEN = ROOT / "artifacts" / "datasets" / "highlight-golden-2026-10-16.jsonl"
OUT_TRAIN = ROOT / "artifacts" / "datasets" / "highlight-train-2026-10-16.jsonl"
OUT_ADDON = ROOT / "data" / "finetune" / "highlight-addon-2026-10-16.jsonl"

SEED = 20261016
HELD_OUT = 24
TRAIN = 72
AMBIGUOUS_MIN = 8
SOURCE = "highlight-golden-2026-10-16"
WORD_RE = re.compile(r"[A-Za-z]+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
MIN_QUOTE = 40


def tokens(text):
    return set(TOKEN_RE.findall(text.lower()))


def normalized(text):
    return " ".join(TOKEN_RE.findall(text.lower()))


def similarity(text_a, text_b):
    ratio = difflib.SequenceMatcher(None, normalized(text_a), normalized(text_b)).ratio()
    set_a, set_b = tokens(text_a), tokens(text_b)
    union = set_a | set_b
    jaccard = len(set_a & set_b) / len(union) if union else 0.0
    return ratio, jaccard


def content_words(text):
    """1-token content words: not a stopword, not digit-only, letters only."""
    seen = []
    for word in WORD_RE.findall(text or ""):
        folded = word.lower()
        if folded in STOPWORDS or folded.isdigit() or len(folded) < 3:
            continue
        seen.append(folded)
    return seen


def gold_sentences(text):
    """Verbatim sentences from the chunk, heading line excluded when it is not one."""
    raw = (text or "").strip()
    lines = raw.splitlines()
    if len(lines) > 1 and not lines[0].strip().endswith((".", "?", "!")):
        raw = "\n".join(lines[1:])
    flat = re.sub(r"\s+", " ", raw).strip()
    sentences = []
    for part in re.split(r"(?<=[.!?])\s+", flat):
        sentence = part.strip()
        if len(sentence) < MIN_QUOTE:
            continue
        if not sentence.endswith((".", "?", "!")):
            continue
        if sentence not in (text or ""):
            continue
        sentences.append(sentence)
    return sentences


def whole_word(sentence, word):
    return re.search(rf"\b{re.escape(word)}\b", sentence, re.I) is not None


def sealed_hit(text, sealed_items):
    for item in sealed_items:
        ratio, jaccard = similarity(text, item)
        if ratio >= 0.8 or jaccard >= 0.6:
            return item, ratio, jaccard
    return None


def neighbors(chunks, index, chapter, limit=2):
    """Up to `limit` other chunks from the same chapter, reading order."""
    out = []
    for offset in (1, -1, 2, -2, 3, -3):
        other = index + offset
        if other < 0 or other >= len(chunks):
            continue
        chunk = chunks[other]
        if chunk.get("chapter") != chapter:
            continue
        out.append(chunk)
        if len(out) == limit:
            break
    return out


def passage(chunk):
    return {
        "chunk_id": chunk["chunk_id"],
        "chapter": chunk.get("chapter"),
        "heading": chunk.get("heading") or "",
        "text": chunk.get("text") or "",
    }


def completion(chapter, sentence):
    return f'[Ch. {chapter}] "{sentence}"\n{sentence}'


def row_for(chunk, selection, sentence, asked, split, distractors):
    passages = [passage(chunk)] + [passage(item) for item in distractors]
    question = asked
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": A.user_message(question, passages)},
            {"role": "assistant", "content": completion(chunk.get("chapter"), sentence)},
        ],
        "meta": {
            "row_type": "highlight",
            "selection": selection,
            "chunk_id": chunk["chunk_id"],
            "heading": chunk.get("heading") or "",
            "asked": asked,
            "split": split,
            "source": SOURCE,
        },
    }


def load_sealed():
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))
    items = [item.strip() for item in sealed["items"] if (item or "").strip()]
    exact = {item.casefold() for item in items}
    return items, exact


def chunk_is_sealed(chunk, exact):
    heading = (chunk.get("heading") or "").strip()
    if heading and heading.casefold() in exact:
        return True
    for sentence in gold_sentences(chunk.get("text") or ""):
        if sentence.casefold() in exact:
            return True
    return False


def word_document_frequency(chunks):
    counts = {}
    for chunk in chunks:
        if chunk.get("_sealed"):
            continue
        seen = set()
        for sentence in gold_sentences(chunk.get("text") or ""):
            for word in content_words(sentence):
                if whole_word(sentence, word):
                    seen.add(word)
        for word in seen:
            counts[word] = counts.get(word, 0) + 1
    return counts


def live_options(chunk, word_df, sealed_items):
    """Kept (word, sentence, asked, band) plus how many asks the seal rejected."""
    text = chunk.get("text") or ""
    heading = chunk.get("heading") or ""
    kept = []
    drops = 0
    seen = set()
    for sentence in gold_sentences(text):
        for word in content_words(sentence):
            if word in seen or not whole_word(sentence, word) or not whole_word(text, word):
                continue
            seen.add(word)
            asked = A.highlight_query(word, heading)
            if sealed_hit(asked, sealed_items):
                drops += 1
                continue
            band = "ambiguous" if word_df.get(word, 0) >= AMBIGUOUS_MIN else "rare"
            kept.append((word, sentence, asked, band))
    return kept, drops


def choose(options, rng, band):
    """One option of `band`, or any option when band is None. Seeded shuffle."""
    pool = [item for item in options if band is None or item[3] == band]
    if not pool:
        return None
    rng.shuffle(pool)
    return pool[0]


def fill(pool, wanted, rng, by_id, chunks, split, prefer_band):
    """Take `wanted` chunks. Prefer `prefer_band`, then any remaining option."""
    rows = []
    taken = set()
    order = list(range(len(pool)))
    rng.shuffle(order)

    def accept(index, band):
        if index in taken or len(rows) >= wanted:
            return
        chunk, options, _drops = pool[index]
        choice = choose(options, rng, band)
        if choice is None:
            return
        word, sentence, asked, picked = choice
        taken.add(index)
        distractors = neighbors(chunks, by_id[chunk["chunk_id"]], chunk.get("chapter"))
        rows.append(row_for(chunk, word, sentence, asked, split, distractors))

    for index in order:
        accept(index, prefer_band)
    if len(rows) < wanted:
        for index in order:
            accept(index, None)
    return rows


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def main():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    chunks = index.get("chunks") or []
    if not chunks or "chunk_id" not in chunks[0] or "text" not in chunks[0]:
        raise SystemExit("index chunks lack chunk_id/text")
    sealed_items, exact = load_sealed()
    for chunk in chunks:
        chunk["_sealed"] = chunk_is_sealed(chunk, exact)

    word_df = word_document_frequency(chunks)
    by_id = {chunk["chunk_id"]: i for i, chunk in enumerate(chunks)}
    pool = []
    seal_drops = 0
    for chunk in chunks:
        if chunk.get("_sealed"):
            continue
        options, drops = live_options(chunk, word_df, sealed_items)
        seal_drops += drops
        if options:
            pool.append((chunk, options, drops))

    rng = random.Random(SEED)
    heldout = fill(pool, HELD_OUT, rng, by_id, chunks, "heldout", "ambiguous")
    held_ids = {row["meta"]["chunk_id"] for row in heldout}
    train_pool = [item for item in pool if item[0]["chunk_id"] not in held_ids]
    train = fill(train_pool, TRAIN, rng, by_id, chunks, "train", "ambiguous")
    ambiguous = sum(1 for row in heldout + train if word_df.get(row["meta"]["selection"], 0) >= AMBIGUOUS_MIN)
    rare = len(heldout) + len(train) - ambiguous
    if len(heldout) != HELD_OUT or len(train) != TRAIN:
        raise SystemExit(
            f"short set: held-out {len(heldout)} train {len(train)} "
            f"(ambiguous {ambiguous} rare {rare} seal_drops {seal_drops})"
        )

    held_ids = {row["meta"]["chunk_id"] for row in heldout}
    train_ids = {row["meta"]["chunk_id"] for row in train}
    if held_ids & train_ids:
        raise SystemExit("held-out and train share a chunk")
    pairs = [(row["meta"]["chunk_id"], row["meta"]["selection"]) for row in heldout + train]
    if len(pairs) != len(set(pairs)):
        raise SystemExit("duplicate (chunk_id, selection)")

    write_jsonl(OUT_GOLDEN, heldout)
    write_jsonl(OUT_TRAIN, train)
    write_jsonl(OUT_ADDON, train)
    print(f"train {len(train)}")
    print(f"held-out {len(heldout)}")
    print(f"ambiguous {ambiguous}")
    print(f"rare {rare}")
    print(f"seal drops {seal_drops}")
    print(f"golden {OUT_GOLDEN.relative_to(ROOT)}")
    print(f"train-file {OUT_TRAIN.relative_to(ROOT)}")
    print(f"addon {OUT_ADDON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
