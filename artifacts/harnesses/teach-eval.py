"""Sampled eval for `mode: teach` — dimensions in, lookups out.

    python artifacts/harnesses/teach-eval.py --rows-only    # the sampled grid
    python artifacts/harnesses/teach-eval.py                # run, no judge
    python artifacts/harnesses/teach-eval.py --judge        # + verdict per example

"Explain it with an example" is not one task. It varies by book, by the shape of
the concept (a mechanism, a process, a comparison, a number), by how the reader
asks, and by whether the book covers the thing at all. A hand-written list drifts
towards the questions the author happened to think of; a sampled grid covers the
corners on purpose and reproduces from a seed.

The sampling rule: every cell (book x kind) is filled exactly once, so each book
sees every kind; phrasings rotate through the cells so each phrasing appears
about equally; one `absent` row per book uses a concept from another book's
headings that this book never mentions. Concepts are never typed by hand — they
come from the book's own section headings, deduplicated, in a deterministic
order.

`bare` is the control: a question with no request in it must NOT be routed to
teach. That is the difference between "give me an example" and the hard bench's
"What uptime percentage represents a concrete example of a service-level
objective in contracts?".
"""

import argparse
import json
import random
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import answer as A  # noqa: E402
import server  # noqa: E402
import store  # noqa: E402
from keywords import postings  # noqa: E402

SEED = 20261102
BOOKS = (
    ("index", "data/index.sqlite"),
    ("index.quantization", "data/index.quantization.sqlite"),
    ("index.ddia", "data/index.ddia.sqlite"),
    ("index.ai-engineering", "data/index.ai-engineering.sqlite"),
    ("index.ai-agents",
     "data/" + next((ROOT / "data").glob("index.ai-agents*")).name),
)
KINDS = ("mechanism", "process", "comparison", "why")
PHRASINGS = ("with_example", "can_you_give", "and_an_example", "bare")
_WORDS = 2, 5
# A concept is a short noun phrase a reader would ask about: not a sentence, not
# a figure caption, not a heading that is mostly a list.
_CONCEPT_REJECT = re.compile(
    r"\d|figure|table|chapter|\?|:|;|\(|\)|^\W| vs\.?$| etc$", re.I
)


def concepts_for(index, limit=24):
    seen, out = set(), []
    for chunk in index.get("chunks") or []:
        heading = (chunk.get("heading") or "").strip().strip("\"'“”")
        words = len(heading.split())
        if words < _WORDS[0] or words > _WORDS[1] or _CONCEPT_REJECT.search(heading):
            continue
        key = heading.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(heading)
    out.sort(key=lambda text: (len(text.split()), text.lower()))
    return out[:limit]


def content_tokens(phrase_text):
    return [tok for tok in re.findall(r"[a-z0-9]+", phrase_text.lower())
            if len(tok) > 2 and tok not in {"the", "and", "for", "with", "does", "from"}]


def phrase_in_book(index, phrase_text):
    """True when every content word of the phrase appears somewhere in the book.

    Token-level, not string-level: half these headings are hyphenated
    ("Per-Tensor quantization"), and `split()[0]` never matches a token.
    """
    head = postings(index)
    tokens = content_tokens(phrase_text)
    return bool(tokens) and all(head.get(tok) for tok in tokens)


def phrase(kind, concept, other, phrasing):
    core = {
        "mechanism": f"what is {concept}",
        "process": f"how does {concept} work",
        "why": f"why does {concept} matter",
        "comparison": f"what is the difference between {concept} and {other}",
    }[kind]
    return {
        "with_example": f"{core}, explain simply with an example",
        "can_you_give": f"{core} in simple words. can you give me an example of it",
        "and_an_example": f"{core} in simple words, and an example?",
        "bare": f"{core} in simple words",
    }[phrasing]


def build_rows():
    """The grid: 4 kinds x 5 books, phrasings rotated, plus one absent row per book."""
    indexes = {book: store.read_index(ROOT / rel) for book, rel in BOOKS}
    pools = {book: concepts_for(index) for book, index in indexes.items()}
    rng = random.Random(SEED)
    rows = []
    for book_index, (book, index) in enumerate(indexes.items()):
        pool = pools[book]
        if len(pool) < 6:
            continue
        for kind_index, kind in enumerate(KINDS):
            concept = pool[(kind_index * 3 + book_index) % len(pool)]
            other = pool[(kind_index * 3 + book_index + 5) % len(pool)] if kind == "comparison" else ""
            phrasing = PHRASINGS[(kind_index + book_index) % len(PHRASINGS)]
            rows.append(make_row(book, kind, concept, other, phrasing, "in_book", index))
        # One concept this book never mentions, taken from another book.
        source = rng.choice([b for b in indexes if b != book and pools[b]])
        foreign = next(
            (term for term in pools[source] if not phrase_in_book(index, term)),
            None,
        )
        if foreign:
            rows.append(make_row(book, "mechanism", foreign, "", "can_you_give",
                                 "absent", index))
    return rows


def make_row(book, kind, concept, other, phrasing, coverage, index):
    question = phrase(kind, concept, other, phrasing)
    present = phrase_in_book(index, concept)
    return {
        "id": f"teach-{book.split('.')[-1][:10]}-{kind}-{phrasing}-{coverage}",
        "book": book,
        "kind": kind,
        "phrasing": phrasing,
        "coverage": coverage,
        "concept": concept,
        "other": other,
        "question": question,
        "expected_mode": "answer" if phrasing == "bare" else "teach",
        "expected_refusal": coverage == "absent" or not present,
        "verified": present if coverage == "in_book" else not present,
    }


def run_row(row):
    index = store.read_index(ROOT / dict(BOOKS)[row["book"]])
    mode = server.effective_mode("answer", row["question"])
    started = time.perf_counter()
    body = A.teach(index, row["question"]) if mode == "teach" else A.respond(index, row["question"])
    elapsed = int((time.perf_counter() - started) * 1000)
    text = body.get("answer") or ""
    chunks = {chunk.get("chunk_id"): chunk.get("text") or "" for chunk in index.get("chunks") or []}
    passages = " ".join(chunks.get(c.get("chunk_id"), "") for c in body.get("citations") or [])
    # Groundedness is measured on the explanation only: the example is the
    # writer's own illustration by contract, so counting its words against the
    # passages measures the wrong thing (it made the score fall when examples
    # started arriving, which was an artefact of the metric, not of the answers).
    explanation = text.split("Example:", 1)[0]
    claim = set(re.findall(r"[a-z]{4,}", explanation.lower()))
    support = set(re.findall(r"[a-z]{4,}", passages.lower()))
    return {
        **row,
        "mode_used": mode,
        "refused": bool(body.get("refused")),
        "has_example": "Example:" in text,
        "words": len(text.split()),
        "grounded": round(len(claim & support) / len(claim), 2) if claim else 0.0,
        "cites": len(body.get("citations") or []),
        "ms": elapsed,
        "answer": text,
        "passages": passages,
    }


def judge_row(result):
    """correct / contradicts / missing, from the rubric written for this mode."""
    import judge

    try:
        return judge.judge_teach_example(
            result["question"], result["passages"], result["answer"]
        )
    except Exception as exc:  # a judge outage is not a verdict
        return f"error:{type(exc).__name__}"


def rate(items, predicate):
    return round(sum(1 for item in items if predicate(item)) / len(items), 3) if items else None


def summarise(results):
    teach = [r for r in results if r["expected_mode"] == "teach"]
    bare = [r for r in results if r["expected_mode"] == "answer"]
    absent = [r for r in results if r["expected_refusal"]]
    in_book = [r for r in results if not r["expected_refusal"]]
    answered = [r for r in teach if not r["refused"]]
    by_kind = {}
    for kind in KINDS:
        rows = [r for r in answered if r["kind"] == kind]
        by_kind[kind] = {
            "rows": len(rows),
            "example_present": rate(rows, lambda r: r["has_example"]),
        }
    return {
        "rows": len(results),
        "routed_to_teach": rate(teach, lambda r: r["mode_used"] == "teach"),
        "control_stayed_on_answer": rate(bare, lambda r: r["mode_used"] == "answer"),
        "refused_when_absent": rate(absent, lambda r: r["refused"]),
        "answered_when_in_book": rate(in_book, lambda r: not r["refused"]),
        "example_present": rate(answered, lambda r: r["has_example"]),
        "grounded_ge_0_6": rate(answered, lambda r: r["grounded"] >= 0.6),
        "mean_words": round(statistics.mean([r["words"] for r in results])),
        "mean_ms": round(statistics.mean([r["ms"] for r in results])),
        "by_kind": by_kind,
    }


def failures(results):
    out = []
    for result in results:
        bad = []
        if result["expected_mode"] == "teach" and result["mode_used"] != "teach":
            bad.append("not-routed")
        if result["expected_mode"] == "answer" and result["mode_used"] != "answer":
            bad.append("mis-routed")
        if result["expected_refusal"] and not result["refused"]:
            bad.append("should-refuse")
        if not result["expected_refusal"] and result["refused"]:
            bad.append("false-refusal")
        if result["expected_mode"] == "teach" and not result["refused"] and not result["has_example"]:
            bad.append("no-example")
        if bad:
            out.append((result["id"], ",".join(bad), result["question"]))
    return out


def main():
    parser = argparse.ArgumentParser(description="Sampled eval for mode teach.")
    parser.add_argument("--judge", action="store_true",
                        help="ask the LLM judge whether each example teaches correctly")
    parser.add_argument("--rows-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    rows = build_rows()
    if args.rows_only:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0

    results = []
    for row in rows:
        result = run_row(row)
        if args.judge and result["has_example"] and not result["refused"]:
            result["verdict"] = judge_row(result)
        results.append(result)
        if args.verbose:
            print(
                f"[{result['ms']:>5}ms] {result['book'].split('.')[-1][:12]:12} "
                f"mode={result['mode_used']:6} refused={str(result['refused']):5} "
                f"ex={str(result['has_example']):5} grounded={result['grounded']:.2f} "
                f":: {row['question'][:64]}"
            )
            print("     " + result["answer"][:200].replace("\n", " / "))

    summary = summarise(results)
    if args.judge:
        verdicts = [r["verdict"] for r in results if "verdict" in r]
        summary["example_verdicts"] = {v: verdicts.count(v) for v in set(verdicts)}
    print(json.dumps(summary, indent=1))

    bad = failures(results)
    print(f"\nfailures: {len(bad)}")
    for row_id, why, question in bad:
        print(f"  {row_id:38} {why:26} {question[:58]}")

    out = ROOT / "artifacts" / "runs" / "teach-eval-latest.json"
    out.write_text(json.dumps({"seed": SEED, "summary": summary, "results": results},
                              indent=1, ensure_ascii=False))
    print(f"\nwrote {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
