"""x2d form generator: new question forms + retrieval preflight (step 1 of the
x2d build, `artifacts/reports/x2d-plan-2026-10-14.md`).

v2 widening (2026-10-14 follow-up; v1 counts are kept in the report):
- kept: all v1 checks — suite near-match r>=0.8 / j>=0.6 strict, duplicate
  rules (train-x1/x2/x2c + bench + candidates), retrieval preflight, class-
  covered skips for the 10 article bares + 10 flips (widening option 1
  deliberately NOT taken), no typos/gibberish/refusal/bench-split forms.
- bench tie-break: the "What is data X" vs bench-template cluster (shared
  tokens are exactly the interrogative template + the word "data") is exempt
  from bench rejection and logged as an assisted-template twin. This admits
  the 5 logged bares (data engineering, data architecture, data retention,
  a data migration, data masking) and, mechanically, a data lake (r=0.800
  exactly vs the MAD item) — both reported.
- manual pins (evidence-checkable rejects): undercurrents of data
  engineering -> ch02-042; materialized-view forms (bare/explain/greet) ->
  ch08-131 (the definition chunk); oltp greet + explain -> ch05-007. Capture
  gold-checks against these pins; a miss demotes (soft) or rejects naturally.
- new classes:
  - explain: "explain {remainder}" for the same derivable remainder pool as
    bare.
  - restate: one wh-restatement for no-wh-prefix sources whose question does
    not already carry a wh-word ("source systems" -> "what are source
    systems"; last-word plurality rule). Quiz/subject-first sources already
    carry the interrogative, so a restatement would be gibberish and is
    skipped (reason logged).
  - heading: 1-4 word section headings from the index as bare-topic forms,
    pin = a chunk under the heading (text-verified), topics not already
    covered by an accepted bare/restate/explain form, strict suite check,
    ~30 attempts. Visible-ten-shaped specials admitted only with evidence
    from `x2-trial-2026-10-14.md`: Location -> ch07-046 (7B's citation),
    DE Lifecycle -> ch02-002 (7B's first citation); Our Advice has no
    evidence-backed pin and is skipped.
  - greets: 15 more topics; cap raised to 30 accepted.
- cap: 4 accepted forms per source card.

Everything else (generation rules for bare/lower/flip, duplicates, preflight
semantics, visible-ten report-only) is the v1 pipeline; see the report for
the v1/v2 counts.

Run: python artifacts/probes/gen-x2d-forms-2026-10-14.py
Writes data/finetune/x2d-forms-2026-10-14.json, a list of
{"question", "pin", "soft", "class", "source_card", "asked_probe"} with
class in bare|lower|flip|swap|greet|named|explain|restate|heading.
"""

import difflib
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from keywords import postings, words
from retrieve import INDEX, load_index

spec = importlib.util.spec_from_file_location(
    "builder", ROOT / "artifacts" / "probes" / "build-finetune-data-2026-10-13.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

OUT = ROOT / "data" / "finetune" / "x2d-forms-2026-10-14.json"
DATA = ROOT / "data" / "finetune"
DEDUP_TRAIN = (
    "quote-refuse-2026-10-13.train-x1.jsonl",
    "quote-refuse-2026-10-13.train-x2.jsonl",
    "quote-refuse-2026-10-13.train-x2c.jsonl",
)
DEDUP_BENCH = (
    "quote-refuse-2026-10-13.bench.jsonl",
    "quote-refuse-2026-10-13.bench-x1.jsonl",
    "quote-refuse-2026-10-13.bench-x2.jsonl",
    "quote-refuse-2026-10-13.bench-x2c.jsonl",
)

# ---------------------------------------------------------------------------
# Derivation rules (closed English classes + the book's own word map).
# ---------------------------------------------------------------------------
BARE_PREFIXES = (
    "what is ", "what are ", "what does ", "what do ", "how do ", "how does ",
    "why does ", "why do ", "when is ", "where does ",
)
PRONOUNS = frozenset((
    "i", "me", "my", "mine", "you", "your", "yours", "we", "our", "us",
    "it", "its", "they", "them", "he", "she", "his", "her",
))
BARE_VERBS = frozenset((
    "do", "does", "did", "mean", "matter", "matters", "differ", "differs",
    "help", "helps", "relate", "relates", "use", "uses", "evolve", "evolved",
    "fusing", "detect", "detects",
))
WH_RE = re.compile(r"\b(what|which|when|where|who|whose|why|how)\b")

# v2 manual pins (question string -> chunk id). The two explain forms extend
# the named materialized-view / oltp pins to the sibling class (same
# hand-evidenced chunk, no special handling).
MANUAL_PINS = {
    "undercurrents of data engineering": "ch02-042",
    "a materialized view": "ch08-131",
    "explain a materialized view": "ch08-131",
    "hey can you tell me about a materialized view": "ch08-131",
    "hey can you tell me about an oltp system": "ch05-007",
    "explain an oltp system": "ch05-007",
}

# Heading specials, evidence-backed from `x2-trial-2026-10-14.md` + its
# probe-trial-queries evidence. "Our Advice" skipped: x2 answered uncited,
# the 7B's cites (ch01-064/057, ch10-008) are a meta-answer, not an
# evidence-backed pin.
HEADING_SPECIALS = (
    ("Location", "ch07-046"),
    ("DE Lifecycle", "ch02-002"),
)
HEADING_CAP = 30
HEADING_SKIP = {
    "conclusion", "conclusions", "additional resources", "our definition",
    "summary", "dataops summary", "further reading", "references", "index",
    "preface", "notes", "introduction", "overview", "key takeaways",
    "our advice", "location", "de lifecycle", "the end", "about the author",
    "exercises", "bibliography", "glossary",
}

# Curated greet topics: the v1 list first (pin retries included), then the v2
# extension. First GREET_CAP that pass every check are kept.
GREET_TOPICS = (
    # v1 list (kept for the record; retries with manual pins included)
    "what is change data capture",
    "source systems",
    "what is an event-streaming platform",
    "what is an oltp system",
    "what is a data warehouse",
    "what is a star schema",
    "what is a fact table",
    "what is a dimension table",
    "what is a message queue",
    "what is a materialized view",
    "what is a broadcast join",
    "what is a query optimizer",
    "what is a feature store",
    "what is data vault modeling",
    "what is denormalization",
    "what is normalization",
    "what is a data migration",
    "what is a direct database connection",
    "what is the principle of least privilege",
    "what is shared responsibility in the cloud",
    "what is a key-value store",
    "what are the undercurrents of the data engineering lifecycle",
    "what is orchestration in the data engineering lifecycle",
    "what is query federation",
    "what is data masking",
    # v2 extension (~15 more topics)
    "what is total cost of ownership",
    "what is acid in database terms",
    "advantages of insert-only tables",
    "slowly changing dimensions",
    "streaming pipelines and real-time analytics",
    "big ball of mud",
    "wide-column databases",
    "stream-to-batch architecture",
    "principles of good data architecture",
    "ways to serve data to consumers",
    "immutable vs transitory technologies",
    "hashing vs encryption",
    "push vs pull ingestion",
    "schema on read vs schema on write",
    "etl vs elt",
)
GREET_CAP = 30
MAX_FORMS_PER_SOURCE = 4

# Named adds from the cross-review (x2d plan: shorthand forms).
NAMED_ADDS = (
    ("undercurrents of data engineering",
     "what are the undercurrents of the data engineering lifecycle"),
    ("change data capture", "what is change data capture"),
)

# ---------------------------------------------------------------------------
# Sealed fragment suite (copied from probe-fragment-2026-10-14.py so a later
# edit of the probe cannot move the seal under this generator).
# ---------------------------------------------------------------------------
ITEMS = [
    ("fragment", "how do", "answered", ""),
    ("fragment", "what about", "answered", ""),
    ("fragment", "explain", "answered", ""),
    ("fragment", "why does", "answered", ""),
    ("greeting", "hi there", "either", ""),
    ("greeting", "good morning", "either", ""),
    ("greeting", "howdy", "either", ""),
    ("bare-topic", "Time Series", "answered", ""),
    ("bare-topic", "File Formats", "answered", ""),
    ("bare-topic", "Micro-Batch", "answered", ""),
    ("bare-topic", "Streaming", "answered", ""),
    ("bare-topic", "Event Streams", "answered", ""),
    ("order-flip", "batch vs streaming", "answered", ""),
    ("order-flip", "streaming vs batch", "answered", ""),
    ("order-flip", "column-oriented vs row-oriented", "answered", ""),
    ("order-flip", "row-oriented vs column-oriented", "answered", ""),
    ("trailing-letter", "what does etls stand for", "answered", ""),
    ("trailing-letter", "benefits of data meshs", "answered", ""),
    ("trailing-letter", "how do data pipeliness work", "answered", ""),
    ("control", "what is the offside rule", "refused", ""),
    ("control", "how many strings does a violin have", "refused", ""),
]
SEAL_TEMPLATE_TWINS = (
    ("what does etls stand for", "what does crud stand for"),
    ("what does etls stand for", "what does raid stand for"),
)
VISIBLE_TEN = [
    "what is", "hey", "warrup", "Location", "Our Advice", "DE Lifecycle",
    "DDR5 vs ddr4", "ddr4 vs ddr5", "speed of ddr5", "speed of ddr5s",
]
# The bench-template cluster: pairs whose shared tokens are exactly the
# interrogative template + "data" (the "What is data X" vs "What is data
# ingestion?" artifact). Bench rejection is lifted for these pairs and they
# are logged as assisted-template twins (v2, user decision 2026-10-14).
TEMPLATE_TOKENS = frozenset(("what", "is", "are", "a", "an", "the", "data"))

TOKEN_RE = re.compile(r"[a-z0-9]+")


def norm_tokens(text):
    return set(TOKEN_RE.findall(text.lower()))


def normalized(text):
    return " ".join(TOKEN_RE.findall(text.lower()))


def similarity(text_a, text_b):
    ratio = difflib.SequenceMatcher(
        None, normalized(text_a), normalized(text_b)
    ).ratio()
    set_a, set_b = norm_tokens(text_a), norm_tokens(text_b)
    union = set_a | set_b
    jaccard = len(set_a & set_b) / len(union) if union else 0.0
    return ratio, jaccard


def is_template_cluster(form, other):
    """Both sides are "what is ..." questions and the only shared tokens are
    the interrogative template + "data"."""
    a, b = normalized(form), normalized(other)
    if not a.startswith("what is") or not b.startswith("what is"):
        return False
    shared = norm_tokens(a) & norm_tokens(b)
    return len(shared) >= 3 and shared <= TEMPLATE_TOKENS


def no_llm(*_args, **_kwargs):
    """Make the reading-repair LLM fallback a no-op (the preflight is local)."""
    raise RuntimeError("x2d preflight: model calls are stubbed out")


def load_questions(path):
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines()]


def bare_remainder(question, word_map):
    """(remainder, None) or (None, reason) for the bare class."""
    remainder = None
    for prefix in BARE_PREFIXES:
        if question.startswith(prefix):
            remainder = question[len(prefix):].strip()
            break
    if remainder is None:
        return None, "no-prefix"
    tokens = words(remainder)
    if not tokens:
        return None, "empty"
    if tokens[0] in PRONOUNS:
        return None, "pronoun:" + tokens[0]
    pronoun = next((tok for tok in tokens if tok in PRONOUNS), None)
    if pronoun:
        return None, "pronoun:" + pronoun
    verb = next((tok for tok in tokens if tok in BARE_VERBS), None)
    if verb:
        return None, "verb:" + verb
    missing = [tok for tok in tokens if tok not in word_map]
    if missing:
        return None, "word-not-in-book:" + missing[0]
    return remainder, None


def restate_form(question, word_map):
    """One wh-restatement for a no-wh-prefix source, or (None, reason)."""
    if WH_RE.search(question.lower()) or "?" in question:
        return None, "question-already-carries-wh"
    tokens = words(question)
    if not tokens:
        return None, "empty"
    missing = [tok for tok in tokens if tok not in word_map]
    if missing:
        return None, "word-not-in-book:" + missing[0]
    last = tokens[-1]
    plural = last.endswith("s") and not last.endswith("ss")
    return f"what {'are' if plural else 'is'} {question}", None


def topic_phrase(question, word_map):
    """The topic a greet form wraps: the bare derivation when one exists,
    else the question itself when it is a bare topic/heading."""
    remainder, _reason = bare_remainder(question, word_map)
    if remainder:
        return remainder
    if A.canonical_query(question) != question:
        return question
    return None


def bare_shaped(text):
    return A.canonical_query(text) != text


def main():
    started = time.monotonic()
    index = load_index(INDEX)
    word_map = postings(index)
    print(f"index: {INDEX.name} chunks={len(index['chunks'])} "
          f"words={len(word_map)}  teacher-for-capture: {builder.TEACHER_MODEL}")

    entries = [entry for entry in builder.source_entries()
               if builder.split_for(entry) == "train"
               and entry["expect"] == "answer"]
    by_question = {entry["question"]: entry for entry in entries}
    print(f"source entries (train, answer): {len(entries)}")

    # Duplicate sets (normalized).
    train_questions = {}
    for name in DEDUP_TRAIN:
        for row in load_questions(DATA / name):
            question = row["meta"]["question"]
            train_questions.setdefault(normalized(question), set()).add(name)
    bench_rows = []
    for name in DEDUP_BENCH:
        for row in load_questions(DATA / name):
            bench_rows.append(row["meta"])
    bench_questions = {normalized(m["question"]) for m in bench_rows}
    bench_questions |= {normalized(m["asked"]) for m in bench_rows}
    bench_raw = sorted({m["question"] for m in bench_rows}
                       | {m["asked"] for m in bench_rows})

    # Retrieval cache (one embed per distinct asked string).
    ctx_cache = {}
    retrieval_errors = 0

    def get_ctx(asked):
        nonlocal retrieval_errors
        if asked not in ctx_cache:
            try:
                ctx_cache[asked] = A.retrieval_context(
                    index, asked, generate_fn=no_llm)
            except Exception as exc:
                retrieval_errors += 1
                print(f"  retrieval error for {asked!r}: "
                      f"{type(exc).__name__}: {exc}")
                ctx_cache[asked] = None
        return ctx_cache[asked]

    def top_chunk(ctx):
        if not ctx or not ctx.get("passages"):
            return None
        return ctx["passages"][0]["chunk_id"]

    # ------------------------------------------------------------------
    # Checks (shared by every phase)
    # ------------------------------------------------------------------
    accepted = []
    accepted_norm = {}
    accepted_by_source = Counter()
    cap_skips = []
    rejects = []
    worst_suite = []
    worst_bench = []
    worst_visible = []
    twin_notes = []
    bench_twin_notes = []
    cluster_notes = []
    repair_notes = []

    def note_reject(candidate, reason, detail=""):
        rejects.append({"question": candidate["question"],
                        "class": candidate["class"], "reason": reason,
                        "detail": detail})

    def run_checks(candidate):
        """Return (reject_reason, detail) or (None, None) when it passes."""
        question = candidate["question"]
        class_name = candidate["class"]
        entry = candidate["entry"]
        norm = normalized(question)

        # similarity telemetry over every generated candidate
        best = (0.0, 0.0, None, None)
        for _cls, item, _expect, _note in ITEMS:
            for form in {question, A.canonical_query(question)}:
                for item_form in {item, A.canonical_query(item)}:
                    r, j = similarity(form, item_form)
                    if r > best[0]:
                        best = (r, j, item_form, form)
        worst_suite.append((best[0], best[1], question, best[2], best[3]))
        best_bench = (0.0, 0.0, None, None)
        for bench_form in bench_raw:
            for form in {question, A.canonical_query(question)}:
                r, j = similarity(form, bench_form)
                if r > best_bench[0]:
                    best_bench = (r, j, bench_form, form)
        worst_bench.append((best_bench[0], best_bench[1], question,
                            best_bench[2], best_bench[3]))
        for visible in VISIBLE_TEN:
            r, j = similarity(question, visible)
            if r >= 0.5 or j >= 0.5:
                worst_visible.append((round(r, 3), round(j, 3), question,
                                      visible))

        # 1. duplicates (swap extras are exempt from the file duplicate rule)
        if class_name != "swap":
            if norm in train_questions:
                return ("duplicate-of-train",
                        ",".join(sorted(train_questions[norm])))
            if norm in bench_questions:
                return "duplicate-of-bench", norm
        if norm in accepted_norm:
            return "duplicate-of-candidate", accepted_norm[norm]

        # 2. sealed suite near-match (declared twins logged; strict >=)
        for _cls, item, _expect, _note in ITEMS:
            for form in {question, A.canonical_query(question)}:
                for item_form in {item, A.canonical_query(item)}:
                    r, j = similarity(form, item_form)
                    if r >= 0.8 or j >= 0.6:
                        if (item, form) in SEAL_TEMPLATE_TWINS:
                            twin_notes.append((item, form, round(r, 3),
                                               round(j, 3)))
                        else:
                            return ("near-suite",
                                    str((item, form, round(r, 3), round(j, 3))))

        # 3. bench near-match; template-cluster pairs are logged, not rejected
        for bench_form in bench_raw:
            for form in {question, A.canonical_query(question)}:
                r, j = similarity(form, bench_form)
                if r >= 0.8 or j >= 0.6:
                    if class_name == "swap":
                        bench_twin_notes.append((question, str(
                            (bench_form, form, round(r, 3), round(j, 3)))))
                        continue
                    if is_template_cluster(form, bench_form):
                        cluster_notes.append((question, str(
                            (bench_form, form, round(r, 3), round(j, 3)))))
                        continue
                    return ("near-bench",
                            str((bench_form, form, round(r, 3), round(j, 3))))

        # 4. retrieval preflight
        asked = A.canonical_query(question)
        ctx = get_ctx(asked)
        passages = ctx["passages"] if ctx else []
        if not passages:
            return "no-passages", ""
        if ctx["asked"] != asked:
            repair_notes.append((question, ctx["asked"]))
        shown = [hit["chunk_id"] for hit in passages]
        pin = candidate["pin"]
        if pin is not None:
            if pin not in shown:
                return "pin-not-shown", f"{pin} not in {shown[:4]}"
        else:
            source_ctx = get_ctx(A.canonical_query(entry["question"]))
            source_top = top_chunk(source_ctx)
            if source_top is None:
                return "no-baseline-passages", entry["question"]
            if top_chunk(ctx) != source_top:
                return "top-chunk-differs", f"{top_chunk(ctx)} vs {source_top}"
        return None, None

    def check_and_accept(candidate):
        question = candidate["question"]
        reason, detail = run_checks(candidate)
        if reason is not None:
            note_reject(candidate, reason, detail)
            return False
        key = candidate["source_key"]
        if accepted_by_source[key] >= MAX_FORMS_PER_SOURCE:
            cap_skips.append({"question": question,
                              "class": candidate["class"],
                              "reason": f"over-{MAX_FORMS_PER_SOURCE}-per-source"})
            return False
        entry = candidate["entry"]
        accepted.append({
            "question": question,
            "pin": candidate["pin"],
            "soft": candidate["soft"],
            "class": candidate["class"],
            "source_card": candidate["source_card"],
            "asked_probe": A.canonical_query(question),
        })
        accepted_norm[normalized(question)] = question
        accepted_by_source[key] += 1
        return True

    # ------------------------------------------------------------------
    # Phase 1: named + swap extras + per-source derived forms
    # ------------------------------------------------------------------
    candidates = []
    skipped = []

    def add_candidate(question, class_name, entry, note="", pin=None,
                      src_key=None, source_card=None, soft=None):
        candidates.append({
            "question": question,
            "class": class_name,
            "entry": entry,
            "pin": MANUAL_PINS.get(question, pin if pin is not None
                                   else (entry["pin"] if entry else None)),
            "note": note,
            "source_key": src_key if src_key is not None else (
                entry["question"] if entry else f"heading:{question}"),
            "source_card": source_card if source_card is not None else (
                entry["question"] if entry else note),
            "soft": soft if soft is not None else (
                entry["soft"] if entry else True),
        })

    for form, source in NAMED_ADDS:
        entry = by_question.get(source)
        if entry is None:
            skipped.append({"question": form, "class": "named",
                            "reason": f"source-missing:{source}"})
            continue
        add_candidate(form, "named", entry, f"from {source!r}")

    for key, value in builder.PERTURB_SWAPS.items():
        entry = by_question.get(key)
        if entry is None:
            skipped.append({"question": value, "class": "swap",
                            "reason": f"key-not-a-train-answer-card:{key}"})
            continue
        add_candidate(value, "swap", entry, f"x2c card for {key!r}")

    for entry in entries:
        question = entry["question"]
        x2c_card = builder.PERTURB_SWAPS.get(question, question)
        covered = set()
        if x2c_card != question:
            if bare_shaped(x2c_card):
                covered.add("bare")
            if " vs " in x2c_card:
                covered.add("flip")
        derived = []
        remainder, reason = bare_remainder(question, word_map)
        if remainder:
            derived.append(("bare", remainder))
        else:
            skipped.append({"question": question, "class": "bare",
                            "reason": reason})
            restated, restate_reason = restate_form(question, word_map)
            if restated:
                derived.append(("restate", restated))
            else:
                skipped.append({"question": question, "class": "restate",
                                "reason": restate_reason})
        lowered = question.lower()
        if lowered != question:
            derived.append(("lower", lowered))
        if " vs " in question:
            if question in builder.PERTURB_SWAPS:
                derived.append(("flip", builder.PERTURB_SWAPS[question]))
            else:
                first, second = question.split(" vs ", 1)
                derived.append(("flip", f"{second} vs {first}"))
        if remainder:
            derived.append(("explain", f"explain {remainder}"))
        picked = 0
        for class_name, form in derived:
            if picked >= 3:
                break
            if class_name in covered:
                skipped.append({"question": form, "class": class_name,
                                "reason": f"class-covered-by-x2c-card:"
                                          f"{x2c_card}"})
                continue
            add_candidate(form, class_name, entry)
            picked += 1

    for candidate in candidates:
        check_and_accept(candidate)
    print(f"phase 1: candidates {len(candidates)} accepted {len(accepted)}")

    # ------------------------------------------------------------------
    # Phase 2: heading forms (specials + mechanical sweep). Topics already
    # covered by an accepted bare/restate/explain form are skipped.
    # ------------------------------------------------------------------
    chunk_by_id = {c["chunk_id"]: c for c in index["chunks"]}
    covered_norms = set()
    covered_tokens = []
    for card in accepted:
        if card["class"] not in ("bare", "restate", "explain"):
            continue
        topic = card["question"]
        if card["class"] == "explain":
            topic = topic[len("explain "):]
        elif card["class"] == "restate":
            topic = re.sub(r"^what (?:is|are) ", "", topic)
        covered_norms.add(normalized(topic))
        covered_norms.add(normalized(card["question"]))
        tokens = norm_tokens(topic)
        if len(tokens) >= 2:
            covered_tokens.append(tokens)

    def heading_covered(heading):
        key = normalized(heading)
        if key in covered_norms:
            return True
        tokens = norm_tokens(heading)
        if len(tokens) >= 2 and any(tokens <= other for other in covered_tokens):
            return True
        return False

    heading_candidates = []
    for form, pin in HEADING_SPECIALS:
        heading_candidates.append({
            "question": form, "class": "heading", "entry": None,
            "pin": pin, "source_key": f"heading:{pin}", "soft": False,
            "source_card": (chunk_by_id[pin].get("heading") or "").strip(),
            "note": "visible-ten special, evidence x2-trial-2026-10-14.md",
        })

    heading_attempts = 0
    heading_pool = {}
    for chunk in index["chunks"]:
        if not str(chunk.get("chapter", "")).isdigit():
            continue
        heading = (chunk.get("heading") or "").strip()
        if not heading:
            continue
        key = normalized(heading)
        if key in heading_pool or key in HEADING_SKIP:
            continue
        if len(heading.split()) > 4 or "?" in heading:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,'\x27-]*", heading):
            continue
        if not normalized((chunk.get("text") or "")[:200]).startswith(key):
            continue
        heading_pool[key] = (heading, chunk["chunk_id"])
    for key in sorted(heading_pool, key=lambda k: heading_pool[k][1]):
        if heading_attempts >= HEADING_CAP:
            break
        if heading_covered(key):
            continue
        heading, chunk_id = heading_pool[key]
        heading_attempts += 1
        heading_candidates.append({
            "question": heading, "class": "heading", "entry": None,
            "pin": chunk_id, "source_key": f"heading:{chunk_id}", "soft": False,
            "source_card": heading, "note": f"section heading of {chunk_id}",
        })

    for candidate in heading_candidates:
        check_and_accept(candidate)
    print(f"phase 2: heading candidates {len(heading_candidates)} "
          f"(mechanical attempts {heading_attempts}) accepted {len(accepted)}")

    # ------------------------------------------------------------------
    # Phase 3: greets (curated topics in order, cap on accepted)
    # ------------------------------------------------------------------
    greet_count = 0
    for topic in GREET_TOPICS:
        if greet_count >= GREET_CAP:
            break
        entry = by_question.get(topic)
        if entry is None:
            skipped.append({"question": topic, "class": "greet",
                            "reason": "source-not-a-train-answer-card"})
            continue
        phrase = topic_phrase(topic, word_map)
        if phrase is None:
            skipped.append({"question": topic, "class": "greet",
                            "reason": "no-topic-phrase"})
            continue
        greet = f"hey can you tell me about {phrase}"
        candidate = {
            "question": greet, "class": "greet", "entry": entry,
            "pin": MANUAL_PINS.get(greet, entry["pin"]), "note": "",
            "source_key": topic, "soft": entry["soft"], "source_card": topic,
        }
        if check_and_accept(candidate):
            greet_count += 1
    print(f"phase 3: greets accepted total {greet_count}")

    # ------------------------------------------------------------------
    # Output + summary
    # ------------------------------------------------------------------
    OUT.write_text(json.dumps(accepted, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    by_class = Counter(card["class"] for card in accepted)
    rej_by_reason = Counter(rej["reason"] for rej in rejects)
    skip_by_reason = Counter(item["reason"].split(":")[0]
                             for item in skipped)

    def worst_of(rows, n=6):
        return sorted(rows, key=lambda row: (-row[0], -row[1]))[:n]

    print()
    print(f"accepted: {len(accepted)}  classes: {dict(sorted(by_class.items()))}")
    print(f"rejected: {len(rejects)}  by reason: {dict(sorted(rej_by_reason.items()))}")
    print(f"generation skips: {len(skipped)}  by reason: {dict(sorted(skip_by_reason.items()))}")
    print(f"cap skips: {len(cap_skips)}")
    rows = 113 + len(accepted) + 54
    steps = -(-6 * rows // 8)  # ceil(6*rows/8)
    print(f"projected x2d rows: 113 + {len(accepted)} + 54 = {rows}"
          f"  steps@6-epochs: ceil(6*{rows}/8) = {steps}")
    print()
    print("worst suite similarities seen (r, j, candidate, item_form, form):")
    for r, j, q, item, form in worst_of(worst_suite):
        print(f"  r={r:.3f} j={j:.3f} {q!r} vs {item!r} (as {form!r})")
    print("worst bench similarities seen (r, j, candidate, bench_form, form):")
    for r, j, q, bench_form, form in worst_of(worst_bench):
        print(f"  r={r:.3f} j={j:.3f} {q!r} vs {bench_form!r} (as {form!r})")
    print(f"visible-ten near hits (report only): {len(worst_visible)}")
    for r, j, q, visible in sorted(worst_visible, key=lambda x: -x[0])[:8]:
        print(f"  r={r} j={j} {q!r} vs {visible!r}")
    print(f"seal twins noted (kept): {len(twin_notes)}")
    for item, form, r, j in twin_notes:
        print(f"  TWIN {item!r} vs {form!r} r={r} j={j}")
    print(f"bench twins noted (swap extras kept): {len(bench_twin_notes)}")
    for question, hit in bench_twin_notes:
        print(f"  BENCH-TWIN {question!r} {hit}")
    print(f"template-cluster admits (logged, assisted-template convention): "
          f"{len(cluster_notes)}")
    for question, hit in cluster_notes:
        print(f"  CLUSTER-ADMIT {question!r} {hit}")
    print(f"reading-repair fired on {len(repair_notes)} candidates:")
    for question, asked in repair_notes[:12]:
        print(f"  {question!r} -> {asked!r}")
    print()
    print("generation skips (detail):")
    for item in skipped:
        print(f"  [{item['class']}] {item['question']!r} {item['reason']}")
    print("cap skips (detail):")
    for item in cap_skips:
        print(f"  [{item['class']}] {item['question']!r} {item['reason']}")
    print("rejects (detail):")
    for item in rejects:
        print(f"  [{item['class']}] {item['question']!r} {item['reason']} {item['detail']}")
    print()
    print("accepted forms:")
    for card in accepted:
        print(f"  [{card['class']:7s}] {card['question']!r} pin={card['pin']} "
              f"soft={card['soft']} asked={card['asked_probe']!r}")
    print(f"\nwrote {OUT}  ({len(accepted)} entries)  "
          f"runtime {time.monotonic() - started:.1f}s  retrieval errors "
          f"{retrieval_errors}")


if __name__ == "__main__":
    main()
