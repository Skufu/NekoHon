"""Build 12 fabricated-attribution trap seeds from the two uncovered books.

Why this file exists: the 844-row corpus and `hard-mt-2026-10-24.jsonl` only
carry three trap items, and none of them come from `quantization` or `ddia`.
The model is therefore trained to refuse a fake attribution mostly on `fde`
prose. This builder writes prompts only — no teacher call, no model, no Colab.

Row shape is copied from `build-pilot-seeds-2026-10-24.py`: same `fold` /
`content` / `leaks` helpers, same env-var output override, same byte-for-byte
`answer.user_message` so the seed is exactly what serving will send.

Each row is a two-turn history: a real question about a real chunk, answered
with one verbatim sentence from that chunk (folded check against the chunk
text), then a follow-up naming a person and a year that appear in no book.
The passage list keeps the history's chunk first and adds up to two neighbours
from the same heading, so the trap does not sit on a lone passage.

Nothing here is trained from until the teacher answers and the assembler
validates it.
"""

import difflib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"
DATASETS = ROOT / "artifacts" / "datasets"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
OUT = Path(os.environ.get(
    "TRAP_OUT", FIN / "trap-crossbook-seeds-2026-10-24.jsonl"))
if not OUT.is_absolute():
    OUT = ROOT / OUT
EVIDENCE = Path(os.environ.get(
    "TRAP_EVIDENCE",
    ROOT / "artifacts" / "evidence" / "hard-mt" / "trap-crossbook-summary.json"))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

CORPUS = FIN / "quote-refuse-2026-10-17.train-x3.jsonl"
REFUSAL = "Not in this book."
PER_BOOK = 6
MIN_CHUNK_CHARS = 400
NEAR_JACCARD = 0.7
NEAR_RATIO = 0.85

QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can", "i",
    "you", "we", "they", "from", "at", "as", "or", "if", "not", "but", "so",
    "use", "used", "using", "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "many", "most", "some", "any", "all",
    "into", "over", "than", "then", "there", "their", "when", "where", "who",
}

# Six per book, one per heading, one per chunk. `quote` is a full sentence that
# must appear in the target chunk; `gloss` is the second line of the history
# answer, written to fit inside answer.HISTORY_ANSWER_CHARS with the quote.
# Names and years are checked against all three books at run time; the pool
# below avoids the names/years already used by hard-mt and the pilot batch.
SPECS = [
    {
        "book": "quantization", "chunk_id": "chapter-2-034",
        "history_question": "What does each filter in a CNN get under per-channel quantization?",
        "quote": "Per-channel quantization calculates a unique (S,Z) pair for each channel "
                 "(typically the output channel for weights).",
        "gloss": "Every output channel gets its own scale and zero point.",
        "topic": "per-channel quantization", "name": "Miriam Halvorsen", "year": "2044",
    },
    {
        "book": "ddia", "chunk_id": "text00008-030",
        "history_question": "Do LSM-trees take less disk space than B-trees?",
        "quote": "LSM-trees can be compressed better, and thus often produce smaller files "
                 "on disk than B-trees.",
        "gloss": "Less fragmentation means smaller files for the same data.",
        "topic": "LSM-tree storage overhead", "name": "Ingrid Solberg", "year": "2052",
    },
    {
        "book": "quantization", "chunk_id": "chapter-3-024",
        "history_question": "How is one scale computed for a whole weight tensor?",
        "quote": "We compute a single scale factor from the entire weight tensor and apply "
                 "it uniformly to every element.",
        "gloss": "One scale covers every weight in the tensor.",
        "topic": "the per-tensor baseline", "name": "Owen Mbeki", "year": "2047",
    },
    {
        "book": "ddia", "chunk_id": "text00009-024",
        "history_question": "Why must a reader hold the writer's schema to decode Avro bytes?",
        "quote": "This means that the binary data can only be decoded correctly if the code "
                 "reading the data is using the exact same schema as the code that wrote "
                 "the data.",
        "gloss": "Reader and writer have to share one schema or the bytes decode wrongly.",
        "topic": "Avro decoding", "name": "Lucia Ferrante", "year": "2049",
    },
    {
        "book": "quantization", "chunk_id": "chapter-3-071",
        "history_question": "Why does a 4-bit weight need smaller groups than an 8-bit one?",
        "quote": "Each scale still covers 4,096 values, but maps them onto only 16 levels.",
        "gloss": "Four bits leave too few levels for the same per-channel range.",
        "topic": "group size at four bits", "name": "Kenji Obarra", "year": "2051",
    },
    {
        "book": "ddia", "chunk_id": "text00011-033",
        "history_question": "How does a client avoid reading a stale replica after its own write?",
        "quote": "The client can remember the timestamp of its most recent write — then the "
                 "system can ensure that the replica serving any reads for that user "
                 "reflects updates at least until that timestamp.",
        "gloss": "The write time travels with the user, so reads land on a caught-up copy.",
        "topic": "read-after-write consistency", "name": "Marta Zelenka", "year": "2055",
    },
    {
        "book": "quantization", "chunk_id": "chapter-3-043",
        "history_question": "When are scale factors fixed under static quantization?",
        "quote": "Static quantization determines ranges during a calibration phase before "
                 "deployment—run representative data, observe distributions, compute scale "
                 "factors, freeze them.",
        "gloss": "Ranges are chosen once from calibration data, then frozen.",
        "topic": "static quantization ranges", "name": "Perrin Achebe", "year": "2057",
    },
    {
        "book": "ddia", "chunk_id": "text00013-060",
        "history_question": "How do you stop dirty writes and lost updates from corrupting data?",
        "quote": "In order to avoid data corruption, those race conditions need to be "
                 "prevented — either automatically by the database, or by manual safeguards "
                 "such as using locks or atomic write operations.",
        "gloss": "Either the database or the application has to stop them in advance.",
        "topic": "write skew", "name": "Yusuf Adeyemi", "year": "2059",
    },
    {
        "book": "quantization", "chunk_id": "chapter-5-021",
        "history_question": "Why does the straight-through estimator still train a network?",
        "quote": "But the direction of the gradient (should this value increase or decrease "
                 "to reduce loss?) is preserved, even though its exact magnitude through "
                 "the rounding operation is fabricated.",
        "gloss": "Rounding loses the true gradient, so only its sign is passed back.",
        "topic": "the straight-through estimator", "name": "Celia Marchetti", "year": "2061",
    },
    {
        "book": "ddia", "chunk_id": "text00014-074",
        "history_question": "Who decides whether a node is really dead?",
        "quote": "If a quorum of nodes declares another node dead, then it must be considered "
                 "dead, even if that node still very much feels alive.",
        "gloss": "A majority vote overrules the node's own view of itself.",
        "topic": "quorum decisions", "name": "Greta Lindqvist", "year": "2063",
    },
    {
        "book": "quantization", "chunk_id": "chapter-7-061",
        "history_question": "Does multiplying by a random orthogonal matrix throw information away?",
        "quote": "The rotation preserves lengths and angles: no information is lost, only "
                 "redistributed.",
        "gloss": "It only moves the magnitude around, so nothing is destroyed.",
        "topic": "random rotation", "name": "Nadia Erdos", "year": "2065",
    },
    {
        "book": "ddia", "chunk_id": "text00015-037",
        "history_question": "What does CAP force you to give up during a partition?",
        "quote": "When a network fault occurs, you have to choose between either "
                 "linearizability or total availability.",
        "gloss": "A partition costs you one of the two, never neither.",
        "topic": "CAP", "name": "Hollis Vantreight", "year": "2068",
    },
]
# Used only when a curated row is dropped; keeps the 6/6 shape without hand edits.
RESERVE = [
    {
        "book": "quantization", "chunk_id": "chapter-4-033",
        "history_question": "What does absolute maximum range estimation guarantee for zero?",
        "quote": "Absolute maximum has one virtue: it guarantees zero clipping error on the "
                 "calibration set.",
        "gloss": "No calibrated value falls outside the range, so nothing is cut off.",
        "topic": "zero clipping error", "name": "Delia Okonkwo", "year": "2045",
    },
    {
        "book": "ddia", "chunk_id": "text00015-060",
        "history_question": "What makes a Lamport timestamp unique across two nodes?",
        "quote": "Two nodes may sometimes have the same counter value, but by including the "
                 "node ID in the timestamp, each timestamp is made unique.",
        "gloss": "The node ID breaks ties between equal counters.",
        "topic": "Lamport timestamps", "name": "Anders Kvist", "year": "2054",
    },
    {
        "book": "quantization", "chunk_id": "chapter-3-061",
        "history_question": "How should granularity follow the tensor's structure?",
        "quote": "Per-channel quantization assigns one scale per channel, isolating "
                 "outlier channels into their own quantization bins.",
        "gloss": "One scale per channel matches how the weights were built.",
        "topic": "granularity matching", "name": "Ruth Nakashima", "year": "2060",
    },
    {
        "book": "ddia", "chunk_id": "text00017-027",
        "history_question": "Who sorts the mapper output before the reducer sees it?",
        "quote": "Step 3, the sort step, is implicit in MapReduce — you don’t have to write "
                 "it, because the output from the mapper is always sorted before it is "
                 "given to the reducer.",
        "gloss": "The framework sorts for you, so no custom code does it.",
        "topic": "MapReduce sorting", "name": "Emeka Balogun", "year": "2066",
    },
    {
        "book": "ddia", "chunk_id": "text00012-014",
        "history_question": "Can hashing a hot key spread the load on its own?",
        "quote": "Hashing the key doesn’t help, as the hash of two identical IDs is still "
                 "the same.",
        "gloss": "Identical IDs hash alike, so the hot partition stays hot.",
        "topic": "hot key skew", "name": "Noor Haddad", "year": "2067",
    },
    {
        "book": "ddia", "chunk_id": "text00008-021",
        "history_question": "How does a B-tree break the database into units it can read?",
        "quote": "By contrast, B-trees break the database down into fixed-size blocks or "
                 "pages, traditionally 4 KB in size (sometimes bigger), and read or write "
                 "one page at a time.",
        "gloss": "The unit is a fixed page, and one page moves per read or write.",
        "topic": "B-tree pages", "name": "Cyrus Delacroix", "year": "2069",
    },
]


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def flat(text):
    """Whitespace-collapsed but still cased: the verbatim-quote comparator."""
    return SPACE_RE.sub(" ", text or "").strip()


def content(text):
    return {w for w in fold(text).split() if w not in STOPWORDS and len(w) > 2}


def jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def load_indexes():
    chunks, by_id, sections = [], {}, {}
    for book, path in INDEXES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        for chunk in data["chunks"]:
            record = {
                "book": book,
                "chunk_id": chunk["chunk_id"],
                "chapter": chunk.get("chapter", ""),
                "heading": (chunk.get("heading") or "").strip(),
                "text": chunk.get("text", ""),
            }
            chunks.append(record)
            by_id[record["chunk_id"]] = record
            if record["heading"]:
                sections.setdefault((book, record["heading"]), []).append(record["chunk_id"])
    return chunks, by_id, sections


def neighbours(by_id, sections, chunk, limit=2):
    """Up to `limit` chunks from the same heading, nearest first, without the target."""
    if not chunk["heading"]:
        return []
    ids = sections.get((chunk["book"], chunk["heading"]), [])
    if chunk["chunk_id"] not in ids:
        return []
    position = ids.index(chunk["chunk_id"])
    picked, step = [], 1
    while len(picked) < limit and (position - step >= 0 or position + step < len(ids)):
        if position - step >= 0:
            picked.append(ids[position - step])
        if len(picked) < limit and position + step < len(ids):
            picked.append(ids[position + step])
        step += 1
    return [by_id[cid] for cid in picked if cid != chunk["chunk_id"]]


def eval_questions():
    """Every question already in play, tagged with the file it came from."""
    out = []
    if CORPUS.is_file():
        for record in jsonl(CORPUS):
            user = next((m.get("content") or "" for m in record.get("messages", [])
                         if m.get("role") == "user"), "")
            match = QUESTION_RE.search(user)
            if match:
                out.append((CORPUS.name, match.group(1).strip()))
    for name in ("hard-mt-2026-10-24.jsonl", "sealed-2026-10-24.jsonl",
                 "hard-bench-2026-10-17.jsonl", "wide-net-2026-10-23.jsonl"):
        for record in jsonl(DATASETS / name):
            question = record.get("question") or ("[selection] " + (record.get("selection") or ""))
            if question.strip():
                out.append((name, question))
            for turn in record.get("history") or []:
                if turn.get("question"):
                    out.append((name, turn["question"]))
    for scenario in json.loads(
            (DATASETS / "adrian-realworld-eval-2026-10-17.json").read_text(encoding="utf-8")):
        for turn in scenario.get("turns") or []:
            if turn.get("question"):
                out.append(("adrian", turn["question"]))
    return out


def leaks(question, corpus):
    folded = fold(question)
    words = content(question)
    if not words:
        return None
    for name, other in corpus:
        other_folded = fold(other)
        if folded == other_folded:
            return name, other, "exact"
        other_words = content(other)
        if not other_words:
            continue
        if len(words & other_words) / len(words | other_words) < NEAR_JACCARD:
            continue
        if difflib.SequenceMatcher(None, folded, other_folded).ratio() >= NEAR_RATIO:
            return name, other, "near"
    return None


def absent(token, books_text):
    """Word-boundary absence of `token` (and each of its words) across all books."""
    for piece in [token] + token.split():
        if re.search(r"\b" + re.escape(fold(piece)) + r"\b", books_text):
            return False
    return True


def main():
    sys.path.insert(0, str(ROOT))
    import answer  # noqa: E402  (needs ROOT on the path)
    import prompt  # noqa: E402

    missing_indexes = [str(path) for path in INDEXES.values() if not path.is_file()]
    if missing_indexes:
        print("missing indexes:", missing_indexes)
        sys.exit(1)

    _, by_id, sections = load_indexes()
    books_text = " ".join(
        flat(chunk["text"]) for path in INDEXES.values()
        for chunk in json.loads(path.read_text(encoding="utf-8"))["chunks"])
    books_text = fold(books_text)
    corpus = eval_questions()
    print(f"leak corpus: {len(corpus)} questions")

    rows, drops, used_chunks = [], [], set()
    stats = Counter()

    def build(spec):
        """Return (row, None) or (None, reason). Never mutates state."""
        chunk = by_id.get(spec["chunk_id"])
        if not chunk:
            return None, "chunk not in any index"
        if chunk["book"] != spec["book"]:
            return None, f"chunk belongs to {chunk['book']}"
        if chunk["chunk_id"] in used_chunks:
            return None, "chunk already used"
        if len(chunk["text"]) < MIN_CHUNK_CHARS:
            return None, f"chunk is {len(chunk['text'])} chars"
        if not chunk["heading"]:
            return None, "chunk has no heading"

        quote = flat(spec["quote"])
        if flat(quote) not in flat(chunk["text"]):
            return None, "quote is not verbatim in the chunk"
        if fold(quote) not in fold(chunk["text"]):
            return None, "quote fails folded check"
        if not quote.rstrip().endswith((".", "?", "!")):
            return None, "quote is not a whole sentence"
        if '"' in spec["gloss"] or "\n" in spec["gloss"]:
            return None, "gloss is not a single quote-free line"

        for token in (spec["name"], spec["year"]):
            if not absent(token, books_text):
                return None, f"fabricated {token!r} is in a book"

        history_answer = f'[Ch. {chunk["chapter"]}] "{quote}"\n{spec["gloss"]}'
        if len(history_answer) > answer.HISTORY_ANSWER_CHARS:
            return None, f"history answer is {len(history_answer)} chars"
        if len(spec["history_question"]) > answer.HISTORY_QUESTION_CHARS:
            return None, "history question too long"

        question = (f"What did {spec['name']} say about {spec['topic']} "
                    f"in {spec['year']}?")
        for probe, label in ((spec["history_question"], "history"), (question, "final")):
            hit = leaks(probe, corpus)
            if hit:
                return None, f"{label} question leaks into {hit[0]}: {hit[1][:60]!r}"

        passages = [{"chapter": chunk["chapter"], "chunk_id": chunk["chunk_id"],
                     "text": chunk["text"]}]
        for sibling in neighbours(by_id, sections, chunk):
            passages.append({"chapter": sibling["chapter"], "chunk_id": sibling["chunk_id"],
                             "text": sibling["text"]})
        history = [{"question": spec["history_question"], "answer": history_answer}]
        user = answer.user_message(question, passages, history)
        if question not in user or quote not in user:
            return None, "user_message lost the question or the quote"

        row = {
            "id": "",
            "class": "premise_trap",
            "system": prompt.SYSTEM,
            "user": user,
            "messages": [{"role": "system", "content": prompt.SYSTEM},
                         {"role": "user", "content": user}],
            "meta": {
                "book": chunk["book"],
                "heading": chunk["heading"],
                "target_chunk": chunk["chunk_id"],
                "anchor_question": spec["history_question"],
                "fabricated": [spec["name"], spec["year"]],
                "trap": "absent_attribution",
                "expect": REFUSAL,
            },
        }
        return row, None

    # Curated rows first, each book alternating; reserves only backfill a drop.
    for spec in list(SPECS) + list(RESERVE):
        per_book = sum(1 for row in rows if row["meta"]["book"] == spec["book"])
        if per_book >= PER_BOOK or len(rows) >= 2 * PER_BOOK:
            continue
        row, detail = build(spec)
        if row is None:
            drops.append({"spec": f"{spec['book']}/{spec['chunk_id']}", "reason": detail})
            stats["drop"] += 1
            continue
        used_chunks.add(spec["chunk_id"])
        row["id"] = f"trap-xb-{len(rows) + 1:02d}"
        rows.append(row)
        stats[row["meta"]["book"]] += 1

    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                   encoding="utf-8")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "rows": len(rows),
        "per_book": {book: stats[book] for book in ("quantization", "ddia")},
        "ids": [row["id"] for row in rows],
        "rows_detail": [
            {"id": row["id"], "book": row["meta"]["book"],
             "heading": row["meta"]["heading"], "target_chunk": row["meta"]["target_chunk"],
             "anchor_question": row["meta"]["anchor_question"],
             "fabricated": row["meta"]["fabricated"]} for row in rows],
        "drops": drops,
        "leak_corpus_questions": len(corpus),
        "out": str(OUT.relative_to(ROOT)),
    }
    EVIDENCE.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print(f"seeds: {len(rows)} -> {OUT.relative_to(ROOT)}")
    print("books:", summary["per_book"])
    print("headings:", sorted({row["meta"]["heading"] for row in rows}))
    print("drops:", drops or "none")
    if len(rows) < 2 * PER_BOOK or any(stats[b] < PER_BOOK for b in ("quantization", "ddia")):
        print("INCOMPLETE: need 6 per book")
        sys.exit(1)


if __name__ == "__main__":
    main()
