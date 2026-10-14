"""Mine ~27 NEW out-of-book refusal questions for the x2d finetune dataset.

Context: `artifacts/reports/x2d-plan-2026-10-14.md` pre-registers 54 unique
refusal questions (the 27 x2/x2c refusals stay; ~27 new ones required) because
the old builder repeats 27 x2 while x2d needs 54 unique x2.

Method (same refusal gate as the builder):
- Candidates: new questions only. Not in the builder's REFUSAL_CANDIDATES,
  not the France/iops canaries, no duplicate (normalized) of any asked form in
  the train-x1/x2/x2c files, and (added guard) no duplicate of the x2d answer
  forms in data/finetune/x2d-forms-2026-10-14.json.
- Teacher-check through the shipped seam: builder.capture(index, question,
  builder.TEACHER_MODEL) (local qwen2.5:7b, temperature 0). Kept only when the
  completion is exactly the refusal sentence. Anything else is the rejected
  pile, recorded by name.
- Near-match guard, copied logic from probe-fragment-2026-10-14.py: reject a
  kept candidate whose raw or canonical form matches a sealed-suite item or a
  bench question at difflib ratio >= 0.8 or word-set Jaccard >= 0.6. The same
  thresholds run against the pre-existing candidate list (added guard: "new"
  means not a near-twin either). The ten visible queries are report-only,
  matching the sealed-suite probe's treatment.

Budget: hard cap 80 teacher calls per run (attempts), elapsed budget stops
launching new calls. If more exact refusals pass the guard than the plan's
TARGET_KEPT, the script ships exactly TARGET_KEPT: every surviving near-miss
(the scarce, plan-adjacent class) plus the exotica with the best near-match
headroom; the rest go to the audit as named spares. Progress is cached in
data/finetune/x2d-refusal-mining-2026-10-14.progress.jsonl; a re-run resumes
without re-calling the teacher.

Run: python artifacts/probes/mine-x2d-refusals-2026-10-14.py [--limit N]
Writes data/finetune/x2d-refusal-candidates.json (deliverable) and
data/finetune/x2d-refusal-mining-2026-10-14.audit.json.
"""

import argparse
import difflib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from canonical import canonical_query  # noqa: E402
from prompt import REFUSAL  # noqa: E402
from retrieve import INDEX, load_index  # noqa: E402


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_module(HERE / "build-finetune-data-2026-10-13.py",
                      "builder_2026_10_13")

TEACHER_MODEL = builder.TEACHER_MODEL          # "qwen2.5:7b"
EXPECTED_TEACHER = "qwen2.5:7b"
capture = builder.capture
REFUSAL_CANDIDATES = builder.REFUSAL_CANDIDATES
CANARIES = ["What is the capital of France?", "what does iops mean"]

TARGET_KEPT = 27      # the plan's "~27 more" on top of the existing 27
CALL_CAP = 80         # hard cap on teacher calls per run (task bound)
FT = ROOT / "data" / "finetune"
CANDIDATES_OUT = FT / "x2d-refusal-candidates.json"
PROGRESS = FT / "x2d-refusal-mining-2026-10-14.progress.jsonl"
AUDIT = FT / "x2d-refusal-mining-2026-10-14.audit.json"
TRAIN_FILES = [
    FT / "quote-refuse-2026-10-13.train-x2c.jsonl",
    FT / "quote-refuse-2026-10-13.train-x2.jsonl",
    FT / "quote-refuse-2026-10-13.train-x1.jsonl",
]
BENCH_FILE = FT / "quote-refuse-2026-10-13.bench.jsonl"
X2D_FORMS = FT / "x2d-forms-2026-10-14.json"

# ---------------------------------------------------------------------------
# Candidates. Batch 1 = 45 (32 obvious exotica + 13 book-adjacent near-misses
# that retrieval cannot actually support). Batch 2 = 15 held in reserve, only
# probed when batch 1 yields fewer than TARGET_KEPT exact refusals.
# ---------------------------------------------------------------------------
BATCH1 = [
    # obvious exotica
    "How far is the moon from Earth?",
    "Who discovered penicillin?",
    "How do you tie a bowline knot?",
    "What is the largest desert in the world?",
    "How many bones are in the human body?",
    "What is the currency of Switzerland?",
    "When did the Titanic sink?",
    "How do you grow tomatoes in a greenhouse?",
    "Who founded Microsoft?",
    "What is the deepest point in the ocean?",
    "How do you convert Celsius to Fahrenheit?",
    "What is the longest river in Africa?",
    "How do you fix a leaking faucet?",
    "What causes a rainbow?",
    "Who was the first person to walk on the moon?",
    "How do you make a paper airplane?",
    "What is the fastest land animal?",
    "What is the pH of pure water?",
    "Who won the Nobel Prize in Literature in 2023?",
    "What is an ionic bond?",
    "How does a microwave oven heat food?",
    "What is the largest species of shark?",
    "Who invented the printing press?",
    "What is the atomic number of carbon?",
    "How do you play the guitar?",
    "When was the United Nations founded?",
    "What is the average rainfall in the Amazon basin?",
    "How do you knit a scarf?",
    "How many countries are in the European Union?",
    "Who won the Tour de France in 2023?",
    "How does a solar panel generate electricity?",
    "What is the diameter of Jupiter?",
    # book-adjacent near-misses (data-engineering vocabulary the book's
    # passing mentions may or may not support; the teacher decides)
    "What is a snowflake schema?",
    "What is a vector database?",
    "What is data fabric?",
    "How do you use dbt to build a data warehouse?",
    "What is RabbitMQ used for?",
    "What is a bloom filter?",
    "What is the CAP theorem?",
    "What is a data contract?",
    "What is a semantic layer?",
    "What is zero-copy cloning?",
    "What is a graph database?",
    "What is an OLAP cube?",
    "What is a feature store?",
]

BATCH2 = [
    "Who wrote the Divine Comedy?",
    "When was the telescope invented?",
    "What is the hardest natural substance on Earth?",
    "How do you parallel park a car?",
    "Who composed The Four Seasons?",
    "What is the most spoken language in the world?",
    "How do you make espresso coffee?",
    "What is the lifespan of a monarch butterfly?",
    "How do you repair a bicycle puncture?",
    "What is the national bird of New Zealand?",
    "Who was the first person to climb Mount Everest?",
    "When was the first heart transplant performed?",
    "How do you bake a pumpkin pie?",
    "How cold is liquid nitrogen?",
    "What is the loudest animal on Earth?",
]

# The book-adjacent near-miss subset of BATCH1 (kept in full when they pass:
# the plan's mix wants them, and they are hard to replace).
BATCH1_NEAR_MISS = set(BATCH1[32:])

# ---------------------------------------------------------------------------
# Sealed-suite items + similarity logic, copied from
# probe-fragment-2026-10-14.py (do not re-derive).
# ---------------------------------------------------------------------------
ITEMS = [
    ("fragment", "how do", "answered",
     "bare wh fragment inside the class's degenerate surface"),
    ("fragment", "what about", "answered", "bare wh fragment"),
    ("fragment", "explain", "answered",
     "bare imperative fragment; 'explain' is a book word (explain plan)"),
    ("fragment", "why does", "answered", "bare wh fragment"),
    ("greeting", "hi there", "either",
     "opener passthrough in canonical.py; same judge both models"),
    ("greeting", "good morning", "either",
     "records what canonical_query does to a non-opener greeting"),
    ("greeting", "howdy", "either",
     "distinct greeting word, not 'hey'/'warrup'"),
    ("bare-topic", "Time Series", "answered", "ch05 heading 'Time series'"),
    ("bare-topic", "File Formats", "answered", "ch07 'Practical Issues with Common File Formats'"),
    ("bare-topic", "Micro-Batch", "answered", "ch08 'Micro-batch versus true streaming'"),
    ("bare-topic", "Streaming", "answered", "ch02 'Streaming' section"),
    ("bare-topic", "Event Streams", "answered", "ch05 'Event-streaming platforms'"),
    ("order-flip", "batch vs streaming", "answered", "pair A, ch02 'Batch versus streaming'"),
    ("order-flip", "streaming vs batch", "answered", "pair A, flipped order"),
    ("order-flip", "column-oriented vs row-oriented", "answered",
     "pair B, ch06 'evolution from rows to columns', app01 glossary"),
    ("order-flip", "row-oriented vs column-oriented", "answered", "pair B, flipped order"),
    ("trailing-letter", "what does etls stand for", "answered",
     "etl+s; ch01 footnote expands ETL"),
    ("trailing-letter", "benefits of data meshs", "answered",
     "mesh+s; ch03-099 'Data Mesh'"),
    ("trailing-letter", "how do data pipeliness work", "answered",
     "pipeliness; ch07 'Data Pipelines'"),
    ("control", "what is the offside rule", "refused",
     "explicit out-of-book control; nothing near it in the train forms"),
    ("control", "how many strings does a violin have", "refused",
     "explicit out-of-book control"),
]

VISIBLE_TEN = [
    "what is", "hey", "warrup", "Location", "Our Advice", "DE Lifecycle",
    "DDR5 vs ddr4", "ddr4 vs ddr5", "speed of ddr5", "speed of ddr5s",
]

TOKEN_RE = re.compile(r"[a-z0-9]+")


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


def asked_forms(path):
    """Distinct 'Question: ...' forms in a quote-refuse jsonl file."""
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for message in row["messages"]:
            if message["role"] == "user" and message["content"].startswith("Question: "):
                out.add(message["content"].split("\n", 1)[0][len("Question: "):])
    return out


def worst_match(forms_a, forms_b):
    """Max ratio/jaccard over every form pair. forms_* are iterables of str."""
    best = {"ratio": 0.0, "ratio_pair": "", "jaccard": 0.0, "jaccard_pair": ""}
    for a in forms_a:
        for b in forms_b:
            ratio, jaccard = similarity(a, b)
            if ratio > best["ratio"]:
                best["ratio"] = ratio
                best["ratio_pair"] = f"{a!r} vs {b!r}"
            if jaccard > best["jaccard"]:
                best["jaccard"] = jaccard
                best["jaccard_pair"] = f"{a!r} vs {b!r}"
    return best


def load_progress():
    done = {}
    if PROGRESS.exists():
        for line in PROGRESS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["question"]] = record
    return done


def probe(index, question, attempts):
    """One teacher call through the shipped seam; returns (record, calls_used)."""
    t0 = time.time()
    try:
        record, err = capture(index, question, TEACHER_MODEL)
    except Exception as exc:  # noqa: BLE001 - network/HTTP/empty-completion
        return ({"question": question, "asked": canonical_query(question),
                 "batch": None, "outcome": "error", "detail": repr(exc),
                 "completion": "", "seconds": round(time.time() - t0, 1)},
                attempts + 1)
    seconds = round(time.time() - t0, 1)
    if err is not None or record is None:
        return ({"question": question, "asked": canonical_query(question),
                 "batch": None, "outcome": "no-passages", "detail": err,
                 "completion": "", "seconds": seconds}, attempts + 1)
    completion = record["completion"]
    if record["refused"] and completion.strip() == REFUSAL:
        outcome = "kept-raw"
    elif record["refused"]:
        outcome = "other-completion"
    else:
        outcome = "answered"
    return ({"question": question, "asked": record["asked"], "batch": None,
             "outcome": outcome, "detail": "",
             "completion": completion, "seconds": seconds}, attempts + 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="probe at most N not-yet-probed candidates")
    parser.add_argument("--budget-seconds", type=float, default=260.0,
                        help="stop launching new teacher calls after this")
    args = parser.parse_args()

    assert REFUSAL == "Not in this book.", REFUSAL
    if TEACHER_MODEL != EXPECTED_TEACHER:
        print(f"[fatal] builder teacher is {TEACHER_MODEL!r}, expected {EXPECTED_TEACHER!r}")
        return 2

    # ---------- load reference sets ----------
    train_forms = set()
    train_counts = {}
    for path in TRAIN_FILES:
        if path.exists():
            forms = asked_forms(path)
            train_counts[path.name] = len(forms)
            train_forms |= forms
    bench_forms = asked_forms(BENCH_FILE) if BENCH_FILE.exists() else set()
    x2d_forms = set()
    if X2D_FORMS.exists():
        for item in json.loads(X2D_FORMS.read_text(encoding="utf-8")):
            x2d_forms.add(item["question"])
            if item.get("asked_probe"):
                x2d_forms.add(item["asked_probe"])
    existing_norm = {normalized(q) for q in REFUSAL_CANDIDATES}
    canary_norm = {normalized(q) for q in CANARIES}
    train_norm = {normalized(q) for q in train_forms}
    x2d_norm = {normalized(q) for q in x2d_forms}
    print(f"[setup] train files {train_counts}; train forms {len(train_forms)}; "
          f"bench forms {len(bench_forms)}; x2d answer forms {len(x2d_forms)}; "
          f"existing candidates {len(REFUSAL_CANDIDATES)}; teacher {TEACHER_MODEL}")

    # ---------- admission (pre-teacher exclusions) ----------
    excluded = []
    admitted = {"batch1": [], "batch2": []}
    for batch, questions in (("batch1", BATCH1), ("batch2", BATCH2)):
        for question in questions:
            norm = normalized(question)
            canon = normalized(canonical_query(question))
            if norm in existing_norm or canon in existing_norm:
                excluded.append((question, "existing-candidate")); continue
            if norm in canary_norm or canon in canary_norm:
                excluded.append((question, "canary")); continue
            if norm in train_norm or canon in train_norm:
                excluded.append((question, "train-form")); continue
            if norm in x2d_norm or canon in x2d_norm:
                excluded.append((question, "x2d-answer-form")); continue
            if question in admitted["batch1"] + admitted["batch2"]:
                excluded.append((question, "local-duplicate")); continue
            admitted[batch].append(question)
    for question, reason in excluded:
        print(f"[excluded] {reason}: {question!r}")

    # ---------- teacher probing ----------
    index = load_index(INDEX)
    progress = load_progress()
    attempts = len(progress)   # calls already spent in earlier runs count
    t0 = time.time()
    calls_this_run = 0
    budget_hit = False
    limit_hit = False

    def probe_batch(name):
        nonlocal attempts, calls_this_run, budget_hit, limit_hit
        for question in admitted[name]:
            if args.limit and calls_this_run >= args.limit:
                limit_hit = True
                return
            if question in progress:
                continue
            if time.time() - t0 > args.budget_seconds:
                budget_hit = True
                return
            if attempts >= CALL_CAP:
                budget_hit = True
                return
            record, attempts = probe(index, question, attempts)
            calls_this_run += 1
            record["batch"] = name
            progress[question] = record
            with PROGRESS.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"[probe] {calls_this_run:3d} {record['seconds']:6.1f}s "
                  f"{record['outcome']:15s} {question!r}")

    probe_batch("batch1")
    raw_kept = [q for q in admitted["batch1"]
                if progress.get(q, {}).get("outcome") == "kept-raw"]
    if len(raw_kept) < TARGET_KEPT and not limit_hit and not budget_hit:
        print(f"[batch2] batch1 exact refusals {len(raw_kept)} < {TARGET_KEPT}; "
              f"probing reserve batch")
        probe_batch("batch2")
    elif len(raw_kept) < TARGET_KEPT:
        print(f"[batch2] skipped (limit/budget); batch1 exact refusals {len(raw_kept)}")

    # ---------- near-match guard ----------
    sealed_forms = set()
    for _cls, item, _expect, _note in ITEMS:
        sealed_forms.add(item)
        sealed_forms.add(canonical_query(item))
    bench_forms_list = sorted(bench_forms)
    existing_list = list(REFUSAL_CANDIDATES)
    guard_rejections = []
    kept = []
    kept_worst = []
    for question in admitted["batch1"] + admitted["batch2"]:
        record = progress.get(question)
        if not record or record["outcome"] != "kept-raw":
            continue
        asked = record["asked"]
        forms = {question, asked}
        sealed = worst_match(forms, sealed_forms)
        bench = worst_match(forms, bench_forms_list)
        existing = worst_match(forms, existing_list)
        visible = worst_match(forms, VISIBLE_TEN)
        kept_forms = [k["question"] for k in kept] + [k["asked"] for k in kept]
        twins = worst_match(forms, kept_forms)
        reasons = []
        if sealed["ratio"] >= 0.8 or sealed["jaccard"] >= 0.6:
            reasons.append("sealed-near-match")
        if bench["ratio"] >= 0.8 or bench["jaccard"] >= 0.6:
            reasons.append("bench-near-match")
        if existing["ratio"] >= 0.8 or existing["jaccard"] >= 0.6:
            reasons.append("existing-near-match")
        if twins["ratio"] >= 0.8 or twins["jaccard"] >= 0.6:
            reasons.append("new-set-near-match")
        worst = {"question": question, "asked": asked,
                 "sealed": sealed, "bench": bench, "existing": existing,
                 "visible_ten": visible, "new_set": twins}
        if reasons:
            guard_rejections.append(dict(worst, reasons=reasons))
            continue
        kept.append({"question": question, "asked": asked,
                     "completion": REFUSAL})
        kept_worst.append(worst)

    # ---------- selection (plan count: exactly TARGET_KEPT new) ----------
    def margin(worst):
        """Distance to the rejection thresholds; higher = closer to a match."""
        return max(
            worst["sealed"]["ratio"] / 0.8, worst["sealed"]["jaccard"] / 0.6,
            worst["bench"]["ratio"] / 0.8, worst["bench"]["jaccard"] / 0.6,
            worst["existing"]["ratio"] / 0.8, worst["existing"]["jaccard"] / 0.6)

    selected = kept
    spares = []
    if len(kept) > TARGET_KEPT:
        exotica = [w for w in kept_worst if w["question"] not in BATCH1_NEAR_MISS]
        drop_count = len(kept) - TARGET_KEPT
        drop = sorted(exotica, key=lambda w: margin(w), reverse=True)[:drop_count]
        drop_set = {w["question"] for w in drop}
        selected = [k for k in kept if k["question"] not in drop_set]
        spares = [dict(w, margin=round(margin(w), 3)) for w in drop]
        print(f"[select] {len(kept)} passed the guard; shipping {TARGET_KEPT} "
              f"(all near-miss survivors + best-headroom exotica); "
              f"spares: {[w['question'] for w in drop]}")

    # ---------- outputs ----------
    CANDIDATES_OUT.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    outcomes = {}
    answered = []
    for question in admitted["batch1"] + admitted["batch2"]:
        record = progress.get(question)
        if not record:
            continue
        outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
        if record["outcome"] != "kept-raw":
            answered.append({"question": question, "asked": record["asked"],
                             "outcome": record["outcome"],
                             "completion": record["completion"][:200],
                             "detail": record["detail"]})

    audit = {
        "date": "2026-10-14",
        "teacher": TEACHER_MODEL,
        "index": str(INDEX.relative_to(ROOT)),
        "proposed": {"batch1": len(BATCH1), "batch2": len(BATCH2),
                     "batch2_ran": any(q in progress for q in admitted["batch2"])},
        "excluded": [{"question": q, "reason": r} for q, r in excluded],
        "teacher_calls_this_run": calls_this_run,
        "teacher_calls_cumulative": attempts,
        "budget_hit": budget_hit,
        "limit_hit": limit_hit,
        "probed": len([q for q in admitted["batch1"] + admitted["batch2"] if q in progress]),
        "outcomes": outcomes,
        "not_kept": answered,
        "guard_rejections": guard_rejections,
        "kept": kept,
        "selected": selected,
        "spares": spares,
        "selection_rule": (
            f"plan pre-registers 54 unique refusals (27 existing + TARGET_KEPT new); "
            f"all near-miss survivors kept, exotica dropped from the tail by "
            f"highest near-match margin (max(ratio/0.8, jaccard/0.6))"
        ),
        "near_match": {
            "thresholds": {"ratio": 0.8, "jaccard": 0.6},
            "note": ("forms checked: raw question + canonical asked; sealed items "
                     "raw + canonical; bench/existing raw; visible ten report-only "
                     "(probe-fragment metric-artifact note applies)"),
            "kept_worst": kept_worst,
        },
        "seconds_this_run": round(time.time() - t0, 1),
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")

    print()
    print(f"[measured] teacher_calls_this_run={calls_this_run} "
          f"cumulative={attempts} probed={audit['probed']} "
          f"kept={len(kept)} selected={len(selected)}/{TARGET_KEPT} "
          f"guard_rejections={len(guard_rejections)} "
          f"rejected_pile={len(answered)} "
          f"seconds={audit['seconds_this_run']} "
          f"budget_hit={budget_hit} limit_hit={limit_hit}")
    for name, key in (("sealed", "sealed"), ("bench", "bench"),
                      ("existing", "existing"), ("visible-ten", "visible_ten")):
        if kept_worst:
            worst = max(kept_worst, key=lambda w: (w[key]["ratio"], w[key]["jaccard"]))
            print(f"[near-match] worst vs {name}: r={worst[key]['ratio']:.3f} "
                  f"({worst[key]['ratio_pair']}) j={worst[key]['jaccard']:.3f} "
                  f"({worst[key]['jaccard_pair']})")
    print(f"wrote {CANDIDATES_OUT.relative_to(ROOT)} "
          f"({len(selected)} candidates) and {AUDIT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
