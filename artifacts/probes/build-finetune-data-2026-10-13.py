"""Finetune data prep: quote-or-refuse training rows from the shipped pipeline.

The teacher is qwen2.5:7b at temperature 0, captured through the real
inference seam (canonical_query -> retrieval_context -> user_message with
the shipped SYSTEM prompt), so every row matches what the small model will
see at inference: system = SYSTEM, user = the exact user message, assistant
= the raw teacher completion.

Acceptance gates (all mechanical):
- answers: not refused; the first cited chunk equals the pin when a hard pin
  exists (battery/eval pins); the citation quote is verbatim in a shown
  passage (the repo's own quote check); a gloss line exists after the quote.
- refusals: the completion is exactly the refusal sentence, kept only for
  curated expect=refuse questions.
Rows failing a gate are counted and logged, never written. Soft pins
(sweep hints) demote to silver instead of rejecting.

Run: python artifacts/probes/build-finetune-data-2026-10-13.py [--limit N]
Writes data/finetune/quote-refuse-2026-10-13.jsonl + .stats.json (both
gitignored) and artifacts/evidence/finetune-data-prep/finetune-data-prep-2026-10-13.log.
"""

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from prompt import PARAPHRASE_SYSTEM, SYSTEM
from retrieve import INDEX, load_index

# The teacher stays qwen2.5:7b even when the app's default model changes:
# distillation needs the strong model, and the built files are its record.
TEACHER_MODEL = "qwen2.5:7b"

OUT = ROOT / "data" / "finetune"
DATASET_TRAIN = OUT / "quote-refuse-2026-10-13.train.jsonl"
DATASET_BENCH = OUT / "quote-refuse-2026-10-13.bench.jsonl"
STATS = OUT / "quote-refuse-2026-10-13.stats.json"
LOG = ROOT / "artifacts" / "evidence" / "finetune-data-prep" / "finetune-data-prep-2026-10-13.log"

# Bench = the post-finetune exam: eval/battery questions and their near
# twins, never trained on. The topic patterns catch sweep questions that
# restate a bench question (measured: watermark x3, data mesh, MAD).
BENCH_PATTERNS = (re.compile(r"\bmad\b"), re.compile(r"mesh"),
                  re.compile(r"waterma"))

# Train refusals are repeated REFUSAL_REPEAT times: 13 refusal cards vs 113
# answer cards taught "always quote something" (both v2/v3 models answered
# the France canary). x3 fixed refusals but left repetition loops on some
# answer questions (measured 2026-10-13 evening: the same question drew
# 6/10 looping samples). x2 (ratio 2) fixed both — refusals exact, zero
# loops — so x2c holds that ratio and changes only question forms.
REFUSAL_REPEAT = 2

# Out-of-book refusal candidates: obvious exotica plus book-adjacent
# near-misses. Kept only when the teacher refuses with the exact sentence.
# The five that answered from passing mentions in the first pass (install a
# Python package, Kubernetes, PyTorch, HTTP 404, JVM GC) are excluded.
REFUSAL_CANDIDATES = [
    "Who wrote Romeo and Juliet?",
    "What is the boiling point of water?",
    "How do you make sourdough bread?",
    "Who won the 2022 World Cup?",
    "What is the tallest mountain in the world?",
    "What is the capital of Australia?",
    "How many planets are in the solar system?",
    "What is a binary search tree?",
    "What is the default shuffle partition count in Apache Spark?",
    "What is the chemical symbol for gold?",
    "When did the Berlin Wall fall?",
    "What is compound interest?",
    "How do you train a goldendoodle puppy?",
    "What is the tallest building in the world?",
    "Who painted the Mona Lisa?",
    "What is the speed of light?",
    "How do you bake a chocolate cake?",
    "What is the population of Tokyo?",
    "Who invented the telephone?",
    "What is the best programming language?",
    "How do you change a car tire?",
    "What is photosynthesis?",
    "When was the Eiffel Tower built?",
    "What is the plot of Hamlet?",
    "How does a combustion engine work?",
    "What is a black hole?",
    "Who is the CEO of Apple?",
    "What is the price of Bitcoin?",
]

# The class-variance fixture's surface forms (artifacts/probes/probe-class-variance-2026-10-13.py):
# form robustness is exactly what the small model must learn.
VARIANTS = [
    ("MAD data landscape", "ch04-020"),
    ("What is MAD data landscape?", "ch04-020"),
    ("hey can you tell me about MAD data landscape", "ch04-020"),
    ("explain MAD data landscape", "ch04-020"),
    ("data mesh", "ch03-099"),
    ("hey can you tell me about data mesh", "ch03-099"),
    ("explain data mesh", "ch03-099"),
    ("data ingestion", "ch07-002"),
    ("explain data ingestion", "ch07-002"),
]

# x2c form-perturbation swaps: ~30 train answer cards get their question
# string swapped in place for a measured sloppy form (counts and the refusal
# ratio held). Measured motivation (artifacts/reports/x2-trial-2026-10-14.md): x2
# refuses the lowercase "What does crud stand for?" while answering the
# uppercase form, refuses "ddr4 vs ddr5" while answering "DDR5 vs ddr4",
# and false-refuses bare topics ("Location", "DE Lifecycle") and greetings.
# Applied to entries BEFORE capture, so retrieval and the prompt both see
# the perturbed asked form. Keys are exact sweep question strings; every
# value's canonical_query was checked to differ from the original's form
# (2026-10-14, data/finetune/_scratch-preflight.py) and to keep every soft
# pin's chunk in the shown passages. Classes: (a) uppercase/mixed-case
# acronym or proper-noun tokens inside question-form asks, (b) A-vs-B and
# paired-noun order flips, (c) bare fragment topics.
PERTURB_SWAPS = {
    # (a) acronym / proper-noun casing inside a question form
    "crud stands for what": "CRUD stands for what",
    "raid stands for what": "RAID stands for what",
    "what does finops help a data team do":
        "what does FinOps help a data team do",
    "togaf defines data architecture as what":
        "TOGAF defines data architecture as what",
    "kimball is on the opposite end of the data modeling spectrum from who":
        "Kimball is on the opposite end of the data modeling spectrum from who",
    "what is pii": "what is PII",
    "what is an oltp system": "what is an OLTP system",
    "what is acid in database terms": "what is ACID in database terms",
    "what is reverse etl": "what is reverse ETL",
    "what is the cloud-scale data os": "what is the cloud-scale data OS",
    # (b) order flips on A-vs-B / paired-noun questions
    "data science vs data engineering": "data engineering vs data science",
    "internal facing vs external facing data engineering":
        "external facing vs internal facing data engineering",
    "brownfield vs greenfield data projects":
        "greenfield vs brownfield data projects",
    "immutable vs transitory technologies":
        "transitory vs immutable technologies",
    "schema on read vs schema on write": "schema on write vs schema on read",
    "etl vs elt": "elt vs etl",
    "bounded vs unbounded data": "unbounded vs bounded data",
    "push vs pull ingestion": "pull vs push ingestion",
    "olap vs oltp": "oltp vs olap",
    "hashing vs encryption": "encryption vs hashing",
    # (c) bare fragment topics (the engine canonicalizes them to What is X?)
    "what is a data warehouse": "data warehouse",
    "what is a data lakehouse": "data lakehouse",
    "what is a data catalog": "data catalog",
    "what is a message queue": "message queue",
    "what is a star schema": "star schema",
    "what is a fact table": "fact table",
    "what is data quality": "data quality",
    "what is data maturity": "data maturity",
    "what is data management": "data management",
    "what is a key-value store": "key-value store",
}


def source_entries():
    """Priority-ordered, deduped question entries."""
    entries = []

    def add(question, pin, expect, source, soft=False):
        for existing in entries:
            if existing["question"] == question:
                return
        entries.append({"question": question, "pin": pin, "expect": expect,
                        "source": source, "soft": soft})

    eval_set = json.loads((ROOT / "artifacts" / "datasets" / "eval-set.json").read_text(encoding="utf-8"))
    for item in eval_set["items"]:
        pin = (item.get("gold_chunks") or [None])[0]
        add(item["question"], pin, item.get("expect", "answer"),
            "eval-" + item.get("source", "item"))
    plain = json.loads((ROOT / "artifacts" / "datasets" / "eval-set-plain.json").read_text(encoding="utf-8"))
    for item in plain["items"]:
        pin = (item.get("gold_chunks") or [None])[0]
        add(item["question"], pin, "answer", "eval-plain")
    for question, pin in VARIANTS:
        add(question, pin, "answer", "class-variant")
    sweep = json.loads(
        (ROOT / "artifacts" / "datasets" / "qa-questions-overnight.json").read_text(encoding="utf-8")
    )
    for item in sweep:
        hint = (item.get("expected_chunk_hint") or "").strip() or None
        add(item["question"], hint, "answer", "sweep-" + item.get("style", "?"),
            soft=True)
    for question in REFUSAL_CANDIDATES:
        add(question, None, "refuse", "refusal-mined")
    return entries


def split_for(entry):
    """bench = the exam; train = everything else."""
    if entry["source"].startswith(("eval-", "class-variant")):
        return "bench"
    folded = entry["question"].lower()
    if any(pattern.search(folded) for pattern in BENCH_PATTERNS):
        return "bench"
    return "train"


def capture(index, question, model):
    asked_form = A.canonical_query(question)
    ctx = A.retrieval_context(index, asked_form)
    passages = ctx["passages"]
    if not passages:
        return None, {"outcome": "no-passages", "asked": asked_form}
    user = A.user_message(ctx["asked"], passages)
    completion = A.ollama_generate(SYSTEM, user, model)
    anchors = A.anchor_words(asked_form, ctx["word_map"])
    body = A.parse_completion(
        completion, passages, index.get("figures") or [], anchors
    )
    record = {
        "asked": asked_form,
        "canonical_fired": asked_form != question,
        "refused": body["refused"],
        "cited": [c["chunk_id"] for c in body["citations"]],
        "quote": (body["citations"][0]["quote"] if body["citations"] else ""),
        "chapter": (body["citations"][0]["chapter"] if body["citations"] else ""),
        "completion": completion,
        "passages": passages,
        "user": user,
    }
    return record, None


def evaluate(entry, record):
    if entry["expect"] == "refuse":
        if record["refused"] and record["completion"].strip() == A.REFUSAL:
            return "refusal", None
        return None, "answered-when-refusal-expected"
    if record["refused"]:
        return None, "teacher-refused"
    if not record["cited"]:
        return None, "no-citation"
    if not any(A._quote_in_passage(record["quote"], h.get("text") or "")
               for h in record["passages"]):
        return None, "quote-not-verbatim"
    pin = entry["pin"]
    if pin and record["cited"][0] == pin:
        return "gold", None
    if pin and entry["soft"]:
        return "silver", f"hint-miss:{record['cited'][0]}"
    if pin:
        return None, f"wrong-chunk:{record['cited'][0]}"
    return "silver", None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    index = load_index(INDEX)
    entries = source_entries()
    swapped = 0
    for entry in entries:
        replacement = PERTURB_SWAPS.get(entry["question"])
        if replacement is not None:
            entry["question"] = replacement
            swapped += 1
    if args.limit:
        entries = entries[: args.limit]

    OUT.mkdir(parents=True, exist_ok=True)
    outcomes = Counter()
    by_source = Counter()
    by_tier = Counter()
    oversampled = 0
    rows = []
    rejects = []

    for number, entry in enumerate(entries, 1):
        record, failure = capture(index, entry["question"], TEACHER_MODEL)
        if failure is not None:
            outcomes[failure["outcome"]] += 1
            rejects.append({"question": entry["question"], **failure})
            continue
        tier, note = evaluate(entry, record)
        if tier is None:
            outcomes[note.split(":")[0]] += 1
            rejects.append({
                "question": entry["question"], "asked": record["asked"],
                "source": entry["source"], "outcome": note,
                "cited": record["cited"][:2],
            })
            continue
        if tier == "refusal":
            target, synthesized = A.REFUSAL, False
            outcomes["refusal-kept"] += 1
        else:
            lines = [line for line in record["completion"].splitlines()
                     if line.strip()]
            quote_line = f'[Ch. {record["chapter"]}] "{record["quote"]}"'
            tail = lines[1:]
            if tail and not tail[-1].strip().startswith("[Ch."):
                gloss, synthesized = tail[-1].strip(), False
                outcomes["teacher-gloss"] += 1
            else:
                gloss = A._clean_rewrite(A.ollama_generate(
                    PARAPHRASE_SYSTEM, f"Sentence: {record['quote']}", TEACHER_MODEL
                ))
                if not gloss:
                    outcomes["gloss-synth-failed"] += 1
                    rejects.append({
                        "question": entry["question"], "asked": record["asked"],
                        "source": entry["source"], "outcome": "gloss-synth-failed",
                        "cited": record["cited"][:2],
                    })
                    continue
                synthesized = True
                outcomes["gloss-synthesized"] += 1
            target = f"{quote_line}\n{gloss}"
        by_source[entry["source"].split("-")[0]] += 1
        by_tier[tier] += 1
        rows.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": record["user"]},
                {"role": "assistant", "content": target},
            ],
            "meta": {
                "question": entry["question"],
                "asked": record["asked"],
                "source": entry["source"],
                "split": split_for(entry),
                "tier": tier,
                "pin": entry["pin"],
                "cited": record["cited"][:2],
                "canonical_fired": record["canonical_fired"],
                "synthesized_gloss": synthesized,
                "note": note,
            },
        })
        if tier == "refusal" and rows[-1]["meta"]["split"] == "train":
            rows[-1]["meta"]["oversampled"] = True
            for _ in range(REFUSAL_REPEAT - 1):
                rows.append(json.loads(json.dumps(rows[-1])))
                oversampled += 1
        if number % 20 == 0:
            print(f"... {number}/{len(entries)} captured")

    by_split = Counter(row["meta"]["split"] for row in rows)
    written = {"train": 0, "bench": 0}
    for split, path in (("train", DATASET_TRAIN), ("bench", DATASET_BENCH)):
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                if row["meta"]["split"] == split:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    written[split] += 1

    stats = {
        "teacher": TEACHER_MODEL,
        "questions": len(entries),
        "perturb_swaps": swapped,
        "rows": len(rows),
        "by_split": dict(by_split),
        "by_tier": dict(by_tier),
        "by_source_root": dict(by_source),
        "outcomes": dict(outcomes),
        "oversampled_copies": oversampled,
        "written": written,
        "files": {"train": DATASET_TRAIN.name, "bench": DATASET_BENCH.name},
        "rejects": rejects,
    }
    STATS.write_text(json.dumps(stats, indent=2, ensure_ascii=False),
                     encoding="utf-8")

    lines = [
        f"finetune data prep 2026-10-13 — teacher {TEACHER_MODEL}",
        f"questions: {len(entries)}  rows kept: {len(rows)}  tiers: {dict(by_tier)}",
        f"perturb swaps applied: {swapped}",
        f"splits: {dict(by_split)}  files: {DATASET_TRAIN.name} / {DATASET_BENCH.name}",
        f"sources: {dict(by_source)}",
        f"outcomes: {dict(outcomes)}",
        "",
        "reject samples:",
    ]
    for reject in rejects[:15]:
        lines.append(f"  {reject}")
    lines.append("")
    lines.append("row samples:")
    for row in rows[:3]:
        head = row["messages"][2]["content"].replace("\n", " / ")[:220]
        lines.append(f"  [{row['meta']['tier']}] {row['meta']['asked'][:60]!r} -> {head}")
    log = "\n".join(lines)
    LOG.write_text(log, encoding="utf-8")
    print(log)


if __name__ == "__main__":
    main()
