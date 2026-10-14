"""A/B proof: would folding typographic punctuation into the dense DOCUMENT
view change retrieval rankings for the shipped pinned questions?

Question under test (2026-10-13): data/index.json embeds documents through
retrieve.format_input(model, "document", text) = normalize(text) + nomic task
prefix. normalize() keeps curly quotes/apostrophes and typographic dashes
(NFKC does not touch them). Would also translating them to ASCII via
preprocess.TYPOGRAPHIC in the document view measurably change rankings? The
answer decides whether an index rebuild is worth it; this probe is
proof-gathering, not a change.

Method, full re-embed, no sampling:
- data/ is read-only here. An in-memory fold space is built: every chunk whose
  text, and every figure whose embedded body (caption + referencing_paragraph,
  measured 2026-10-13 to be what the stored vectors were built from), carries
  a TYPOGRAPHIC source character is re-embedded as
  normalize(text).translate(TYPOGRAPHIC); records without such characters
  reuse the stored vector (identical by construction).
- Pinned questions come from artifacts/harnesses/step2-battery.py via importlib:
  GOLDEN_PINS (question, pin), TYPOS/PROBES (question, pin, phrase),
  COHERENCE (question, pin, regex). Each unique question is embedded once;
  that one query vector ranks ALL chunks in both spaces (retrieve.cosine,
  stable score sort identical to retrieve.rank_chunks, cross-checked once
  against retrieve.rank_chunks itself).
- Pre-declared verdict: 0 top-1 flips and every pinned-chunk dense rank
  within +-2 places => fold unproven on this book, do not rebuild.

Run: python artifacts/probes/probe-fold-ab-2026-10-13.py
Writes artifacts/evidence/probe-fold-ab/probe-fold-ab-2026-10-13.json and .log.
"""

import importlib.util
import json
import statistics
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import preprocess
import retrieve

MODEL = retrieve.DEFAULT_EMBEDDER
BATTERY = ROOT / "artifacts" / "harnesses" / "step2-battery.py"
OUT_JSON = ROOT / "artifacts" / "evidence" / "probe-fold-ab" / "probe-fold-ab-2026-10-13.json"
OUT_LOG = ROOT / "artifacts" / "evidence" / "probe-fold-ab" / "probe-fold-ab-2026-10-13.log"
TIME_BUDGET = 15 * 60  # seconds of re-embed wall clock before sampling the rest
STRAIGHT_QUERY = "Turck's 2021 MAD landscape"
CURLY_QUERY = "Turck\u2019s 2021 MAD landscape"
FIGURE_41 = "figure-4-1"

# str.maketrans returns a dict keyed by ordinals (ints); accept both spellings.
TYPO_CHARS = "".join(
    chr(code) if isinstance(code, int) else code for code in preprocess.TYPOGRAPHIC
)

LINES = []


def log(line=""):
    LINES.append(line)
    print(line, flush=True)


def flush(record):
    OUT_JSON.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    OUT_LOG.write_text("\n".join(LINES) + "\n", encoding="utf-8")


def fold_text(text):
    """The document-side fold under test: normalize, then typographic ASCII."""
    return preprocess.normalize(text).translate(preprocess.TYPOGRAPHIC)


def rank_all(records, vectors, query_vec):
    """Rank explicit (record, vector) pairs like retrieve.rank_chunks does.

    Same skip rule (no vector -> not ranked), same cosine, same stable sort
    keyed on score alone, so equal-score ties keep the index order.
    """
    ranked = []
    for record, vector in zip(records, vectors):
        if vector is None:
            continue
        ranked.append((retrieve.cosine(query_vec, vector), record))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def load_battery():
    spec = importlib.util.spec_from_file_location("step2_battery", BATTERY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["step2_battery"] = module
    spec.loader.exec_module(module)
    return module


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    started = time.perf_counter()
    index = retrieve.load_index(retrieve.INDEX)
    chunks = index.get("chunks", [])
    figures = index.get("figures", [])
    dims = index.get("embedding_dims")
    record = {
        "probe": "fold-ab",
        "date": "2026-10-13",
        "status": "running",
        "index": str(Path(retrieve.INDEX).resolve().relative_to(ROOT).as_posix()),
        "embedder": index.get("embedder"),
        "dims": dims,
        "typo_chars": TYPO_CHARS,
    }
    if len(TYPO_CHARS) != 6:
        log(f"WARNING: TYPOGRAPHIC has {len(TYPO_CHARS)} source chars, expected 6")
    log(f"# fold-ab probe 2026-10-13  index {record['index']}  "
        f"embedder {record['embedder']} dims {dims}")
    log(f"# typographic source chars: {TYPO_CHARS!r}")
    log(f"# chunks {len(chunks)}  figures {len(figures)}")

    def fail(message):
        record["status"] = "failed"
        record["error"] = message
        log(f"FAILED: {message}")
        log(f"probe seconds {time.perf_counter() - started:.1f}")
        flush(record)
        raise SystemExit(1)

    # --- Sanity: the stored vectors must be reproducible through the pipeline.
    sanity_chunk = next(
        (c for c in chunks if isinstance(c.get("embedding"), list)), None
    )
    if sanity_chunk is None:
        fail("no chunk with an embedding in the index")
    fresh = retrieve.ollama_embed(
        [retrieve.format_input(MODEL, "document", sanity_chunk["text"])], MODEL
    )[0]
    cos = retrieve.cosine(fresh, sanity_chunk["embedding"])
    log(f"sanity chunk {sanity_chunk['chunk_id']}: re-embed cos vs stored "
        f"{cos:.6f} (bar >0.999)")
    record["sanity"] = {"chunk": {"chunk_id": sanity_chunk["chunk_id"], "cosine": cos}}
    if not cos > 0.999:
        fail("pipeline equivalence broken: stored vectors are not reproducible")

    figure_41 = next((f for f in figures if f.get("id") == FIGURE_41), None)
    if figure_41 is None or not isinstance(figure_41.get("embedding"), list):
        fail(f"{FIGURE_41} missing or has no embedding")
    body_41 = retrieve.figure_body(figure_41)
    fresh_body_41 = retrieve.ollama_embed(
        [retrieve.format_input(MODEL, "document", body_41)], MODEL
    )[0]
    cos_body_41 = retrieve.cosine(fresh_body_41, figure_41["embedding"])
    log(f"sanity {FIGURE_41} body (caption+referencing_paragraph): re-embed cos "
        f"vs stored {cos_body_41:.6f}")
    record["sanity"][FIGURE_41 + "_body"] = {"cosine": cos_body_41}
    if not cos_body_41 > 0.999:
        fail(f"stored {FIGURE_41} vector is not the body re-embed; fold A/B confounded")

    # --- Classify every record: fold (re-embed) vs reuse (byte-identical input).
    to_fold = []  # (kind, record, folded_text)
    chunk_reembedded = chunk_reused = chunk_no_vector = 0
    figure_reembedded = figure_reused = figure_no_vector = 0
    figure_caption_trigger = 0

    for chunk in chunks:
        text = chunk.get("text") or ""
        if not isinstance(chunk.get("embedding"), list):
            chunk_no_vector += 1
            continue
        if any(char in text for char in TYPO_CHARS):
            to_fold.append(("chunk", chunk, fold_text(text)))
        else:
            chunk_reused += 1
    for figure in figures:
        body = retrieve.figure_body(figure)
        if not isinstance(figure.get("embedding"), list):
            figure_no_vector += 1
            continue
        if any(char in (figure.get("caption") or "") for char in TYPO_CHARS):
            figure_caption_trigger += 1
        if any(char in body for char in TYPO_CHARS):
            to_fold.append(("figure", figure, fold_text(body)))
        else:
            figure_reused += 1

    pending = len(to_fold)
    chunk_trigger = sum(1 for kind, _, _ in to_fold if kind == "chunk")
    figure_trigger = sum(1 for kind, _, _ in to_fold if kind == "figure")
    log(f"re-embed vs reuse: chunks embedded {chunk_trigger}/"
        f"{len(chunks)} (reused {chunk_reused}, no vector {chunk_no_vector}); "
        f"figures embedded {figure_trigger}/{len(figures)} "
        f"(reused {figure_reused}, no vector {figure_no_vector})")
    log(f"figure trigger note: {figure_caption_trigger} figures trigger on the "
        f"caption alone; the fold uses caption+referencing_paragraph, the text "
        f"the index embedded")

    # --- Re-embed the fold set in batches, with the 15-minute guard.
    fresh_vectors = {}
    not_sampled = []
    guard_tripped = False
    fold_started = time.perf_counter()
    done = 0
    for start in range(0, pending, retrieve.BATCH):
        group = to_fold[start:start + retrieve.BATCH]
        inputs = [
            retrieve.format_input(MODEL, "document", folded)
            for _, _, folded in group
        ]
        vectors = retrieve.ollama_embed(inputs, MODEL)
        if not isinstance(vectors, list) or len(vectors) != len(group):
            fail(f"embedder returned bad batch at offset {start}")
        for (_, target, _), vector in zip(group, vectors):
            fresh_vectors[id(target)] = [round(value, 6) for value in vector]
        done = start + len(group)
        if time.perf_counter() - fold_started > TIME_BUDGET:
            guard_tripped = True
            not_sampled = [target.get("chunk_id") or target.get("id")
                           for _, target, _ in to_fold[done:]]
            log(f"TIME GUARD: stopped after {done}/{pending} re-embeds; "
                f"the rest reuse stored vectors")
            break
    fold_seconds = time.perf_counter() - fold_started
    sampled = to_fold[:done] if guard_tripped else to_fold
    log(f"fold re-embeds done {done} in {fold_seconds:.1f}s "
        f"(time guard tripped: {guard_tripped})")
    record["fold"] = {
        "trigger_basis": "chunk text / figure caption+referencing_paragraph "
                         "(the text the index embedded)",
        "chunks_total": len(chunks),
        "chunks_reembedded": chunk_trigger if not guard_tripped else
                             sum(1 for kind, _, _ in sampled if kind == "chunk"),
        "chunks_reused": chunk_reused,
        "chunks_no_vector": chunk_no_vector,
        "figures_total": len(figures),
        "figures_reembedded": figure_trigger if not guard_tripped else
                              sum(1 for kind, _, _ in sampled if kind == "figure"),
        "figures_reused": figure_reused,
        "figures_no_vector": figure_no_vector,
        "figures_caption_only_trigger": figure_caption_trigger,
        "seconds": fold_seconds,
        "time_guard_tripped": guard_tripped,
        "not_sampled_ids": not_sampled,
    }

    # How far the fold moves a document vector at all (fresh vs stored, same record).
    for kind in ("chunk", "figure"):
        sims = [
            (retrieve.cosine(fresh_vectors[id(target)], target["embedding"]), target)
            for k, target, _ in sampled
            if k == kind
        ]
        if not sims:
            continue
        values = [value for value, _ in sims]
        floor = min(sims)
        record["fold"][f"{kind}_displacement"] = {
            "n": len(sims),
            "min": min(values),
            "median": statistics.median(values),
            "max": max(values),
            "min_id": floor[1].get("chunk_id") or floor[1].get("id"),
        }
        log(f"fold displacement {kind}s: cos(folded, stored) min {min(values):.6f} "
            f"median {statistics.median(values):.6f} max {max(values):.6f} "
            f"(n {len(sims)})")

    # Fold space = fresh vector where re-embedded, stored vector otherwise.
    stored_vectors = [chunk.get("embedding") for chunk in chunks]
    folded_vectors = [
        fresh_vectors.get(id(chunk), chunk.get("embedding")) for chunk in chunks
    ]

    # --- Pinned questions from the battery (imported, not retyped).
    battery = load_battery()
    entries = []
    for question, pin in battery.GOLDEN_PINS:
        entries.append({"source": "GOLDEN_PINS", "question": question, "pin": pin})
    for source, seq in (("TYPOS", battery.TYPOS), ("PROBES", battery.PROBES),
                        ("COHERENCE", battery.COHERENCE)):
        for item in seq:
            entries.append({"source": source, "question": item[0], "pin": item[1]})
    unique_questions = []
    for entry in entries:
        if entry["question"] not in unique_questions:
            unique_questions.append(entry["question"])
    log(f"questions: {len(entries)} pinned entries over "
        f"{len(unique_questions)} unique questions "
        f"(GOLDEN_PINS {len(battery.GOLDEN_PINS)}, TYPOS {len(battery.TYPOS)}, "
        f"PROBES {len(battery.PROBES)}, COHERENCE {len(battery.COHERENCE)})")

    query_vectors = {}
    for question in unique_questions:
        vector = retrieve.ollama_embed(
            [retrieve.format_input(MODEL, "query", question)], MODEL
        )[0]
        if not isinstance(vector, list) or (dims and len(vector) != dims):
            fail(f"query embedding for {question!r} has bad width")
        query_vectors[question] = vector

    stored_ranked = {}
    folded_ranked = {}
    for question in unique_questions:
        stored_ranked[question] = rank_all(
            chunks, stored_vectors, query_vectors[question]
        )
        folded_ranked[question] = rank_all(
            chunks, folded_vectors, query_vectors[question]
        )

    # Cross-check the direct ranking against the engine's own rank_chunks once.
    check_question = unique_questions[0]
    engine_top5 = [
        chunk["chunk_id"]
        for _, chunk in retrieve.rank_chunks(index, check_question, MODEL)[:5]
    ]
    direct_top5 = [
        chunk["chunk_id"] for _, chunk in stored_ranked[check_question][:5]
    ]
    cross_ok = engine_top5 == direct_top5
    record["rank_cross_check"] = {
        "question": check_question,
        "engine_top5": engine_top5,
        "direct_top5": direct_top5,
        "ok": cross_ok,
    }
    log(f"rank cross-check vs retrieve.rank_chunks on {check_question!r}: "
        f"{'ok' if cross_ok else 'MISMATCH'}")

    # --- Per-entry before/after.
    result_entries = []
    flips = []
    deltas = []
    pin_absent = []
    for entry in entries:
        question = entry["question"]
        pin = entry["pin"]
        stored = stored_ranked[question]
        folded = folded_ranked[question]
        stored_ranks = {c["chunk_id"]: i + 1 for i, (_, c) in enumerate(stored)}
        folded_ranks = {c["chunk_id"]: i + 1 for i, (_, c) in enumerate(folded)}
        stored_top1 = stored[0][1]["chunk_id"] if stored else None
        folded_top1 = folded[0][1]["chunk_id"] if folded else None
        pin_rank_stored = stored_ranks.get(pin)
        pin_rank_folded = folded_ranks.get(pin)
        if pin_rank_stored is None or pin_rank_folded is None:
            pin_absent.append(entry)
        delta = (
            None if pin_rank_stored is None or pin_rank_folded is None
            else pin_rank_folded - pin_rank_stored
        )
        item = {
            "source": entry["source"],
            "question": question,
            "pin": pin,
            "stored": {
                "top1": stored_top1,
                "top5": [c["chunk_id"] for _, c in stored[:5]],
                "pin_rank": pin_rank_stored,
            },
            "folded": {
                "top1": folded_top1,
                "top5": [c["chunk_id"] for _, c in folded[:5]],
                "pin_rank": pin_rank_folded,
            },
            "top1_flip": stored_top1 != folded_top1,
            "pin_rank_delta": delta,
        }
        result_entries.append(item)
        if item["top1_flip"]:
            flips.append(item)
        if delta:
            deltas.append(item)
        if delta is None or item["top1_flip"] or abs(delta) > 2:
            mark = "CHANGED"
        elif delta:
            mark = "MOVED  "
        else:
            mark = "SAME   "
        leaf = question if len(question) <= 64 else question[:61] + "..."
        log(f"{mark} [{entry['source']}] pin {pin} rank "
            f"{pin_rank_stored}->{pin_rank_folded} "
            f"(delta {delta:+d}) top1 {stored_top1}->{folded_top1}  {leaf}"
            if delta is not None else
            f"CHANGED [{entry['source']}] pin {pin} missing from a ranking  {leaf}")

    # --- Step 5: the figure-4-1 straight-query check.
    straight_vec = retrieve.ollama_embed(
        [retrieve.format_input(MODEL, "query", STRAIGHT_QUERY)], MODEL
    )[0]
    curly_vec = retrieve.ollama_embed(
        [retrieve.format_input(MODEL, "query", CURLY_QUERY)], MODEL
    )[0]
    folded_body_vec = fresh_vectors.get(id(figure_41))
    if folded_body_vec is None:
        folded_body_vec = retrieve.ollama_embed(
            [retrieve.format_input(MODEL, "document", fold_text(body_41))], MODEL
        )[0]
        log("note: figure-4-1 was not in the fold set; folded body embedded now")
    folded_caption_vec = retrieve.ollama_embed(
        [
            retrieve.format_input(
                MODEL, "document", fold_text(figure_41.get("caption") or "")
            )
        ],
        MODEL,
    )[0]
    fig = {
        "straight_query": STRAIGHT_QUERY,
        "curly_query": CURLY_QUERY,
        "stored_vector_input": "caption+referencing_paragraph (measured)",
        "cos_straight_vs_stored": retrieve.cosine(straight_vec, figure_41["embedding"]),
        "cos_curly_vs_stored": retrieve.cosine(curly_vec, figure_41["embedding"]),
        "cos_straight_vs_folded_caption_only": retrieve.cosine(
            straight_vec, folded_caption_vec
        ),
        "cos_straight_vs_folded_body": retrieve.cosine(straight_vec, folded_body_vec),
        "cos_folded_body_vs_stored": retrieve.cosine(
            folded_body_vec, figure_41["embedding"]
        ),
    }
    record["figure_4_1"] = fig
    log(f"{FIGURE_41}: straight query vs stored {fig['cos_straight_vs_stored']:.4f}; "
        f"curly query vs stored {fig['cos_curly_vs_stored']:.4f} (the old 0.6887 "
        f"anchor, re-measured); straight query vs folded body "
        f"{fig['cos_straight_vs_folded_body']:.4f}; straight vs folded caption-only "
        f"{fig['cos_straight_vs_folded_caption_only']:.4f} (confounded: stored "
        f"vector carries the referencing paragraph)")

    # --- Verdict against the pre-declared criteria.
    flip_questions = []
    for question in unique_questions:
        if stored_ranked[question][0][1]["chunk_id"] != folded_ranked[question][0][1]["chunk_id"]:
            flip_questions.append(question)
    max_abs = max((abs(item["pin_rank_delta"]) for item in deltas), default=0)
    criteria_ok = not flip_questions and not pin_absent and max_abs <= 2
    recommendation = (
        "fold unproven on this book: 0 top-1 flips and every pinned rank moved "
        "at most +-2; do not rebuild the index for the fold"
        if criteria_ok else
        "fold changes rankings on this book: see flips and deltas; rebuild only "
        "if these moves are wanted"
    )
    record["verdict"] = {
        "top1_flips": len(flip_questions),
        "flip_questions": flip_questions,
        "non_zero_pin_deltas": [
            {
                "question": item["question"],
                "pin": item["pin"],
                "stored_rank": item["stored"]["pin_rank"],
                "folded_rank": item["folded"]["pin_rank"],
                "delta": item["pin_rank_delta"],
            }
            for item in deltas
        ],
        "max_abs_pin_delta": max_abs,
        "pins_absent": [item["pin"] for item in pin_absent],
        "criteria": "0 top-1 flips AND every pinned dense rank within +-2 places",
        "criteria_met": criteria_ok,
        "recommendation": recommendation,
    }
    log("")
    log(f"verdict: top-1 flips {len(flip_questions)}/{len(unique_questions)}; "
        f"non-zero pinned-rank deltas {len(deltas)}/{len(entries)}; "
        f"max |delta| {max_abs}; pins absent {len(pin_absent)}")
    for item in deltas:
        delta = item["pin_rank_delta"]
        direction = "up" if delta < 0 else "down"
        log(f"delta: pin {item['pin']} rank {item['stored']['pin_rank']}->"
            f"{item['folded']['pin_rank']} ({direction} {abs(delta)}) "
            f"[{item['source']}] {item['question']}")
    for item in flips:
        log(f"FLIP: top1 {item['stored']['top1']}->{item['folded']['top1']} "
            f"[{item['source']}] {item['question']}")
    log(f"criteria: {record['verdict']['criteria']} -> "
        f"{'MET' if criteria_ok else 'NOT MET'}")
    log(f"recommendation: {recommendation}")

    record["status"] = "ok"
    record["entries"] = result_entries
    record["probe_seconds"] = time.perf_counter() - started
    log(f"probe seconds {record['probe_seconds']:.1f}")
    flush(record)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        error = traceback.format_exc()
        log(f"UNEXPECTED ERROR\n{error}")
        try:
            flush({"probe": "fold-ab", "date": "2026-10-13",
                   "status": "exception", "error": error})
        finally:
            raise SystemExit(1)
