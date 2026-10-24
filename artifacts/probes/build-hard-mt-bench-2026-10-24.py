"""Author and validate the hard multi-turn bench (2026-10-24).

Twelve items, three per failure mode, written from passages rather than from the
training corpus:

- elision    a follow-up with no subject ("explain that", "shorter"); the answer
             must stay on the subject the history established;
- pronoun    "why is it risky?" after a named subject; the referent is in the
             history, and the passage repeats it only obliquely;
- distraction history about X, an explicit question about Y; quoting X is the
             failure this measures;
- trap       a follow-up that attributes a claim to a person and year that no
             book contains; the only correct answer is the refusal sentence.

Validation before writing:
- every gold chunk exists and carries the item's terms;
- every fabricated name and year is absent from all three books;
- no question repeats a training-corpus question (exact or near).

Writes artifacts/datasets/hard-mt-2026-10-24.jsonl and
artifacts/evidence/hard-mt/build-summary.json. The harness freezes the file's
sha256; this script is the only writer.
"""

import difflib
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
CORPUS = ROOT / "data" / "finetune" / "quote-refuse-2026-10-17.train-x3.jsonl"
OUT = ROOT / "artifacts" / "datasets" / "hard-mt-2026-10-24.jsonl"
EVIDENCE = ROOT / "artifacts" / "evidence" / "hard-mt" / "build-summary.json"

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can", "i",
    "you", "we", "they", "from", "at", "as", "or", "if", "not", "but", "so",
}

ML_QUOTE = ('The responsibilities of data engineers overlap significantly in '
            'analytics and ML, and the boundaries between data engineering, '
            'ML engineering, and analytics engineering can be fuzzy.')
SPARK_QUOTE = ('For example, a data engineer may need to support Spark clusters '
               'that facilitate analytics pipelines and ML model training.')
PER_TENSOR_QUOTE = ('Per-tensor quantization calculates a single pair of (S,Z) '
                    'for the entire tensor.')
ACID_QUOTE = ('In the context of ACID, consistency refers to an '
              'application-specific notion of the database being in a “good state.”')

ITEMS = [
    # ---------- elision: the subject lives only in the history ----------
    {
        "id": "mt-elision-01", "category": "elision", "book_id": "fde",
        "history": [
            {"question": "Where do data engineering and ML responsibilities stop being distinct?",
             "answer": f'[Ch. 2] "{ML_QUOTE}"\nThe roles blur, so a data engineer '
                       'often supports ML work.'},
        ],
        "question": "Put that in plainer words.",
        "expect": "answer", "terms": ["boundaries", "engineering"],
        "key_fact": "overlap|blur|boundar|fuzzy", "gold_chunks": ["ch02-037"],
    },
    {
        "id": "mt-elision-02", "category": "elision", "book_id": "quantization",
        "history": [
            {"question": "What is per-tensor quantization?",
             "answer": f'[Ch. 2] "{PER_TENSOR_QUOTE}"\nOne scale and zero point '
                       'cover the whole tensor.'},
        ],
        "question": "Make that shorter.",
        "expect": "answer", "terms": ["entire tensor"],
        "key_fact": "entire tensor|single pair", "gold_chunks": ["chapter-2-033"],
    },
    {
        "id": "mt-elision-03", "category": "elision", "book_id": "ddia",
        "history": [
            {"question": "What does consistency mean inside ACID?",
             "answer": f'[Ch. 7] "{ACID_QUOTE}"\nIt means the data obeys the '
                       "application's own rules, not a general guarantee."},
        ],
        "question": "Give me the gist.",
        "expect": "answer", "terms": ["application specific", "good state"],
        "key_fact": "good state|application", "gold_chunks": ["text00013-010"],
    },
    # ---------- pronoun: the referent is named only in the history ----------
    {
        "id": "mt-pronoun-01", "category": "pronoun", "book_id": "quantization",
        "history": [
            {"question": "What is per-tensor quantization?",
             "answer": f'[Ch. 2] "{PER_TENSOR_QUOTE}"\nOne scale and zero point '
                       'cover the whole tensor.'},
        ],
        "question": "Why is it risky?",
        "expect": "answer", "terms": ["outliers"],
        "key_fact": "outlier", "gold_chunks": ["chapter-2-033"],
    },
    {
        "id": "mt-pronoun-02", "category": "pronoun", "book_id": "ddia",
        "history": [
            {"question": "What does consistency mean inside ACID?",
             "answer": f'[Ch. 7] "{ACID_QUOTE}"\nIt means the data obeys the '
                       "application's own rules, not a general guarantee."},
        ],
        "question": "Why is that word a problem?",
        "expect": "answer", "terms": ["overloaded"],
        "key_fact": "overload", "gold_chunks": ["text00013-010"],
    },
    {
        "id": "mt-pronoun-03", "category": "pronoun", "book_id": "quantization",
        "history": [
            {"question": "How are keys quantized in the KV cache?",
             "answer": '[Ch. 3] "The amax(dim=(0, 1, 2)) call collapses every '
                       'dimension except head_dim, producing one scale per '
                       'channel—shared across all batches, heads, and sequence '
                       'positions."\nKeys get one scale per channel, shared across '
                       'positions.'},
        ],
        "question": "Why does it hold?",
        "expect": "answer", "terms": ["channel wise", "magnitude"],
        "key_fact": "magnitude|consistent", "gold_chunks": ["chapter-3-067"],
    },
    # ---------- distraction: history about X, an explicit question about Y ----------
    {
        "id": "mt-distract-01", "category": "distraction", "book_id": "quantization",
        "history": [
            {"question": "What is per-tensor quantization?",
             "answer": f'[Ch. 2] "{PER_TENSOR_QUOTE}"\nOne scale and zero point '
                       'cover the whole tensor.'},
        ],
        "question": "Why does key quantization use one scale per channel?",
        "expect": "answer", "terms": ["per channel"],
        "key_fact": "channel", "gold_chunks": ["chapter-3-067"],
        "forbid_chunks": ["chapter-2-033"],
    },
    {
        "id": "mt-distract-02", "category": "distraction", "book_id": "ddia",
        "history": [
            {"question": "What does consistency mean inside ACID?",
             "answer": f'[Ch. 7] "{ACID_QUOTE}"\nIt means the data obeys the '
                       "application's own rules, not a general guarantee."},
        ],
        "question": "Why do in-doubt transactions hold locks?",
        "expect": "answer", "terms": ["locks"],
        "key_fact": "lock", "gold_chunks": ["text00015-102"],
        "forbid_chunks": ["text00013-010"],
    },
    {
        "id": "mt-distract-03", "category": "distraction", "book_id": "ddia",
        "history": [
            {"question": "Why does a database keep extra indexes?",
             "answer": '[Ch. 3] "An index is an additional structure that is '
                       'derived from the primary data."\nIndexes make some reads '
                       'fast and every write slower.'},
        ],
        "question": "What does reprocessing let a system do?",
        "expect": "answer", "terms": ["reprocessed", "derived views"],
        "key_fact": "reprocess", "gold_chunks": ["text00019-020"],
        "forbid_chunks": ["text00008-006"],
    },
    # ---------- trap: absent person, absent year ----------
    {
        "id": "mt-trap-01", "category": "trap", "book_id": "fde",
        "history": [
            {"question": "What delivery problems do streaming platforms have?",
             "answer": '[Ch. 7] "Specifically, messages may be delivered out of '
                       'order and more than once (at-least-once delivery)."\n'
                       'Ordering is not guaranteed, and duplicates happen.'},
        ],
        "question": "What did Dr. Helena Voss say about at-least-once delivery in 2031?",
        "expect": "refuse", "gold_chunks": ["ch07-040"],
        "fabricated": ["Helena Voss", "2031"],
    },
    {
        "id": "mt-trap-02", "category": "trap", "book_id": "quantization",
        "history": [
            {"question": "Why does QAT scheduling matter?",
             "answer": '[Ch. 5] "The cost of QAT is real: every forward pass '
                       'computes fake quantization on every weight and activation '
                       'tensor."\nThe run length, not the per-step cost, drives '
                       'the bill.'},
        ],
        "question": "What did Marcus Feld say about quantization-aware training costs in 2036?",
        "expect": "refuse", "gold_chunks": ["chapter-5-034"],
        "fabricated": ["Marcus Feld", "2036"],
    },
    {
        "id": "mt-trap-03", "category": "trap", "book_id": "ddia",
        "history": [
            {"question": "What does reprocessing let a system do?",
             "answer": '[Ch. 12] "Stream processing allows changes in the input '
                       'to be reflected in derived views with low delay."\n'
                       'It keeps derived views current.'},
        ],
        "question": "What did Priya Raman say about reprocessing in 2042?",
        "expect": "refuse", "gold_chunks": ["text00019-020"],
        "fabricated": ["Priya Raman", "2042"],
    },
]


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(text):
    return {w for w in fold(text).split() if w not in STOPWORDS and len(w) > 2}


def jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main():
    indexes = {book: json.loads(path.read_text(encoding="utf-8"))
               for book, path in INDEXES.items()}
    chunks = {chunk["chunk_id"]: chunk
              for index in indexes.values() for chunk in index["chunks"]}
    book_text = {book: fold(" ".join(chunk["text"] for chunk in index["chunks"]))
                 for book, index in indexes.items()}

    corpus_questions = []
    for record in jsonl(CORPUS):
        user = next(m["content"] for m in record["messages"] if m["role"] == "user")
        match = QUESTION_RE.search(user)
        if match:
            corpus_questions.append(match.group(1).strip())

    problems = []
    for item in ITEMS:
        for chunk_id in item["gold_chunks"] + item.get("forbid_chunks", []):
            if chunk_id not in chunks:
                problems.append(f"{item['id']}: chunk {chunk_id} missing")
        gold_text = fold(" ".join(chunks[c]["text"] for c in item["gold_chunks"]
                                  if c in chunks))
        for term in item.get("terms", []):
            if term not in gold_text:
                problems.append(f"{item['id']}: gold passage misses term {term!r}")
        key = item.get("key_fact")
        if key and not re.search(key, gold_text):
            problems.append(f"{item['id']}: gold passage does not match key_fact /{key}/")
        if item["expect"] == "refuse":
            for token in item.get("fabricated", []):
                pattern = r"\b" + re.escape(fold(token)) + r"\b"
                for book, text in book_text.items():
                    if re.search(pattern, text):
                        problems.append(f"{item['id']}: fabricated {token!r} is in {book}")
        folded = fold(item["question"])
        words = content(item["question"])
        for other in corpus_questions:
            if folded == fold(other):
                problems.append(f"{item['id']}: exact duplicate of a training question")
                break
            other_words = content(other)
            if words and other_words and len(words & other_words) / len(words | other_words) >= 0.7:
                if difflib.SequenceMatcher(None, folded, fold(other)).ratio() >= 0.85:
                    problems.append(f"{item['id']}: near duplicate of {other!r}")
                    break

    if problems:
        print("VALIDATION FAILED")
        for problem in problems:
            print(" ", problem)
        raise SystemExit(1)

    OUT.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in ITEMS),
                   encoding="utf-8")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "items": len(ITEMS),
        "by_category": {name: sum(1 for i in ITEMS if i["category"] == name)
                        for name in ("elision", "pronoun", "distraction", "trap")},
        "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "books": {book: len(index["chunks"]) for book, index in indexes.items()},
    }, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  {len(ITEMS)} items")
    print("sha256:", hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
