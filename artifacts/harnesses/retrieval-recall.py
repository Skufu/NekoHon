"""Retrieval recall and chapter coverage, per book. Artifact, not engine.

The question this answers: does the top-5 window the model is shown contain
the chapters that hold the answer? Recall alone does not: a single gold chunk
in the window makes recall green while the answer still comes from one scene.
So the primary metric is chapter coverage:

    coverage@5 = |chapters retrieved in the 5 passages| / |gold chapters|

and plain recall@5 ("some gold chunk is in the window") is reported next to
it on purpose. Today recall is green on the novel while coverage is red -
that gap is the defect this baseline exists to expose.

Pipeline measured, and why it is not answer.retrieval_context:

  passages, ranks = retrieve.search_with_ranks(index, question, k=...)
  if <engine lexical gate>:                    # --gate rare|terms
      passages = fusion.fuse(..., added=N)     # --additions 0|1|2|engine
  otherwise the dense window stands.

The engine knobs are explicit arguments, never the module defaults, so a
run means the same thing before and after a flip:
  --gate rare      keywords.rare(question, word_map)          (pre-fix gate)
  --gate terms     keywords.lexical_terms(index, question, word_map)
  --additions N    fusion.fuse(..., added=N): dense passages first, then N
                   admissible BM25 chunks the window does not hold. "engine"
                   uses the shipped policy: 2 for fiction, 1 for technical.
  --engine-window  start from the book's own passage limit (fiction 8,
                   technical 5) instead of the contract window of 5.
  --max-candidates fusion.MAX_LEXICAL_CANDIDATES for the rejected RRF-cap
                   design; 1 is the pre-fix path.

The pre-fix reference at the engine's real window is:
  python3 artifacts/harnesses/retrieval-recall.py --gate rare --additions 0 --engine-window
and the after run against the same pinned rows is:
  python3 artifacts/harnesses/retrieval-recall.py --label after \
      --dataset artifacts/runs/retrieval-recall-before-dataset-<stamp>.jsonl \
      --gate terms --additions engine --engine-window \
      --compare artifacts/runs/retrieval-recall-before-<stamp>.json
which also prints the per-book delta table (coverage, recall, matter slots,
window passages, mean window characters) against the saved before JSON.

retrieval_context adds reading repair (which may call the answer model),
acronym expansion, caption seeding, phrase boost, pin/history and a
reranker; those are answer-stage decisions, not the lexical gate under
test, and one of them (llm_second_reading) is a non-deterministic network
call per row. The gate is chosen by name (--gate rare|terms), so this
harness can capture the pre-fix reference after the call site has changed
and the after state before it does. Two engine-path caveats the numbers do
not cover: answer.ask may answer a "who is X" entity ask from entity.py
before retrieval_context runs at all, and a pin can shrink the window to
PASSAGE_LIMIT; this harness measures the retrieval layer those paths share,
and the report says so.

Datasets and merge rule. Row schema:
  {"book": <index file stem>, "id", "question", "gold_chunk_ids",
   "gold_chapters", "key_fact", "evidence", "kind", "verified"}
A run merges fragments in this order:
  1. retrieval-recall-2026-11-02.technical.jsonl  (five technical books)
  2. retrieval-recall-2026-11-02.novel.jsonl      (the light novel)
  3. retrieval-recall-2026-11-02.legacy-audited.jsonl, but only for a book
     that has no row in 1 or 2 (the audited comparability set, replaced by
     authored rows as they land).
The merged rows are written to retrieval-recall-2026-11-02.jsonl and pinned
to artifacts/runs/retrieval-recall-<label>-dataset-<stamp>.jsonl. Pass
--dataset to evaluate a pinned file byte-for-byte later; that is how the
before and after runs see the same rows. If a primary fragment is absent
from the tree, the merged dataset is evaluated as-is with a warning; a
partial row set is never produced silently.

Verification is mechanical, every run: every gold chunk id must exist in its
index; key_fact must occur in a gold chunk; evidence must occur in a gold
chunk; a refusal row must have no gold chunks and its key_fact must occur in
no chunk. A row failing a check is reported as a data defect and the run
exits 2. Declared "verified": false rows are reported the same way, never
counted as clean.

Thresholds, stated here and enforced by the exit code:
  COVERAGE_THRESHOLD = 0.75  mean coverage per book
  RECALL_THRESHOLD   = 0.80  mean recall@5 per book
  SUBSET_THRESHOLD   = 0.75  mean coverage per (book, kind) with >= 3 rows
"coverage@5" keeps the contract's name: without --engine-window the window
is exactly 5; with it the window is the book's own (fiction 8, technical 5)
plus --additions, and the report's `window=` column states the mean actually
counted so a larger window is never mistaken for a better one.
`goldchunks=N/M` per row is the count of distinct gold chunks in the window:
a caption seed or a replacement can keep `win=` constant while dropping the
gold chunk (N drops, M stays), which the binary recall column alone hides.
Refusal rows have no gold chapters and are excluded from coverage and
recall; they are reported separately. Exit 1 when a metric is below its
threshold, exit 2 on a data defect, exit 0 otherwise.

Run: python3 artifacts/harnesses/retrieval-recall.py --gate rare --additions 0 --engine-window
Writes artifacts/runs/retrieval-recall-<label>-<stamp>.txt and .json.
"""

import argparse
import collections
import datetime
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import fusion
import keywords
import retrieve
import bookkind

# A subdirectory on purpose: `tests/test_fair_set.py` treats every file directly
# under artifacts/datasets as an existing eval set and requires the fair
# questions to be novel against them. This set reuses some of those question
# strings on purpose (it is a retrieval scoreboard, not a model eval), so it
# lives one level down where that guard does not conflate the two.
DATASETS = ROOT / "artifacts" / "datasets" / "retrieval"
RUNS = ROOT / "artifacts" / "runs"
TECHNICAL = DATASETS / "retrieval-recall-2026-11-02.technical.jsonl"
NOVEL = DATASETS / "retrieval-recall-2026-11-02.novel.jsonl"
LEGACY = DATASETS / "retrieval-recall-2026-11-02.legacy-audited.jsonl"
MERGED = DATASETS / "retrieval-recall-2026-11-02.jsonl"
BOOKS = ROOT / "data" / "books.json"

K = 5
COVERAGE_THRESHOLD = 0.75
RECALL_THRESHOLD = 0.80
SUBSET_THRESHOLD = 0.75
SUBSET_MIN_ROWS = 3


def book_indexes():
    """Every served book: index stem, book id and index path -> path."""
    by_stem = {}
    by_id = {}
    for book in json.loads(BOOKS.read_text(encoding="utf-8")):
        path = ROOT / book["index_path"]
        by_stem[path.stem] = path
        by_id[book["book_id"]] = path
    return by_stem, by_id


def resolve_book(row, by_stem, by_id):
    name = str(row.get("book") or row.get("book_id") or "")
    if name in by_stem:
        return name
    if name in by_id:
        return by_id[name].stem
    stem = Path(name).stem
    if stem in by_stem:
        return stem
    raise SystemExit(f"dataset names a book with no index: {name!r}")


def read_jsonl(path):
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def merge_rows():
    """Primary fragments, with the audited set only for uncovered books.

    If a primary fragment is missing from the tree, the merged dataset is
    evaluated as-is instead of silently running on a partial row set; the
    warning names the missing files. The merged file is written by this
    harness, so it is the last complete set, not a third opinion.
    """
    missing = [path.name for path in (TECHNICAL, NOVEL) if not path.is_file()]
    if missing:
        if MERGED.is_file():
            print(
                f"warning: fragment(s) missing: {', '.join(missing)}; "
                f"evaluating {MERGED.name} as-is",
                file=sys.stderr,
            )
            rows = read_jsonl(MERGED)
            for row in rows:
                row["_source"] = "merged-fallback"
            return rows
        raise SystemExit(
            f"missing dataset fragment(s): {', '.join(missing)} and no {MERGED.name}"
        )
    primary = read_jsonl(TECHNICAL) + read_jsonl(NOVEL)
    legacy = read_jsonl(LEGACY)
    by_stem, by_id = book_indexes()
    covered = {resolve_book(row, by_stem, by_id) for row in primary}
    rows = []
    for row in primary:
        row = dict(row)
        row["_source"] = "primary"
        rows.append(row)
    for row in legacy:
        stem = resolve_book(row, by_stem, by_id)
        if stem not in covered:
            row = dict(row)
            row["_source"] = "legacy"
            rows.append(row)
    return rows


def write_dataset(rows, label, stamp):
    clean = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in clean)
    MERGED.write_text(text, encoding="utf-8")
    pinned = RUNS / f"retrieval-recall-{label}-dataset-{stamp}.jsonl"
    pinned.write_text(text, encoding="utf-8")
    return pinned


def gate_terms(index, question, word_map, mode="rare"):
    """The lexical gate the run asks for, resolved by name.

    --gate rare is the pre-fix gate the served path uses today; --gate terms
    is keywords.lexical_terms after the answer.py call-site change. Neither
    is taken from whatever the tree currently calls, so a captured run cannot
    silently measure the other one.
    """
    if mode == "terms":
        fn = getattr(keywords, "lexical_terms", None)
        if not callable(fn):
            raise SystemExit("--gate terms: keywords.lexical_terms is not on disk")
        try:
            terms = fn(index, question, word_map)
        except TypeError:
            terms = fn(question, word_map)
        if isinstance(terms, bool):
            return ["<gate>"] if terms else []
        return [str(term) for term in (terms or [])]
    return ["<rare>"] if keywords.rare(question, word_map) else []


def matter_chapters(index):
    """Chapter ids that are front/back matter, not narrative.

    ingest marks matter as section-NNNN. A section that carries an
    "Interlude:" heading is a story chapter in this corpus and is not matter;
    back matter without one is.
    """
    headings = collections.defaultdict(list)
    for chunk in index.get("chunks") or []:
        chapter = str(chunk.get("chapter"))
        if not chapter.isdigit():
            headings[chapter].append((chunk.get("heading") or "").strip().lower())
    return {
        chapter
        for chapter, heads in headings.items()
        if not any(head.startswith("interlude") for head in heads)
    }


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


def check_row(row, index, all_text):
    """Mechanical data check. Returns a list of defect strings."""
    defects = []
    chunks = {chunk.get("chunk_id"): chunk for chunk in index.get("chunks") or []}
    gold = [str(chunk_id) for chunk_id in row.get("gold_chunk_ids") or []]
    if row.get("kind") == "refusal":
        if gold:
            defects.append("refusal row carries gold chunk ids")
        term = str(row.get("key_fact") or "").strip()
        if not term:
            defects.append("refusal row has no key_fact term to check")
        elif term.lower() in all_text.lower():
            defects.append(f"refusal term {term!r} occurs in the book")
        return defects
    if not gold:
        defects.append("no gold chunk ids")
    for chunk_id in gold:
        if chunk_id not in chunks:
            defects.append(f"gold chunk {chunk_id} not in index")
    texts = [chunks[chunk_id].get("text") or "" for chunk_id in gold if chunk_id in chunks]
    key_fact = str(row.get("key_fact") or "").strip()
    if not key_fact:
        defects.append("no key_fact")
    elif not any(key_fact.lower() in text.lower() for text in texts):
        defects.append(f"key_fact {key_fact!r} not in a gold chunk")
    evidence = normalize(row.get("evidence"))
    if not evidence:
        defects.append("no evidence sentence")
    elif not any(evidence in normalize(text) for text in texts):
        defects.append("evidence sentence not in a gold chunk")
    return defects


def base_window(index, engine_window):
    """Dense passages before additions: the contract's 5, or the book's own."""
    if engine_window:
        return int(bookkind.for_index(index)["passage_limit"])
    return K


def additions_for(index, mode):
    """Lexical chunks appended to the window: 0, a fixed n, or the shipped policy."""
    if str(mode) == "engine":
        if bookkind.kind(index) == bookkind.FICTION:
            return int(fusion.MAX_LEXICAL_ADDITIONS_FICTION)
        return int(fusion.MAX_LEXICAL_ADDITIONS)
    return int(mode)


def run_row(index, row, word_map, matter, gate_mode="rare", engine_window=False, additions="0", dense_only=False):
    question = row["question"]
    dense_k = base_window(index, engine_window)
    added = additions_for(index, additions)
    dense, ranks = retrieve.search_with_ranks(index, question, k=dense_k)
    terms = [] if dense_only else gate_terms(index, question, word_map, mode=gate_mode)
    if terms:
        if added > 0:
            passages = fusion.fuse(
                index, question, dense, word_map, ranks=ranks, added=added
            )
        else:
            passages = fusion.fuse(index, question, dense, word_map, ranks=ranks)
    else:
        passages = dense

    retrieved = [str(hit.get("chapter")) for hit in passages]
    retrieved_ids = [hit.get("chunk_id") for hit in passages]
    window_chars = sum(len(hit.get("text") or "") for hit in passages)
    window_passages = len(passages)
    gold_chapters = [str(chapter) for chapter in row.get("gold_chapters") or []]
    refusal = row.get("kind") == "refusal"

    if refusal:
        coverage = None
        recall = None
        missed = []
        clean = not any(
            str(row.get("key_fact") or "").lower() in (hit.get("text") or "").lower()
            for hit in passages
        )
    else:
        hit_chapters = set(retrieved) & set(gold_chapters)
        coverage = len(hit_chapters) / len(gold_chapters) if gold_chapters else 0.0
        gold_chunks = {str(chunk_id) for chunk_id in row.get("gold_chunk_ids") or []}
        recall = any(chunk_id in gold_chunks for chunk_id in retrieved_ids)
        missed = [chapter for chapter in gold_chapters if chapter not in set(retrieved)]
        clean = None

    gold_chunks = {str(chunk_id) for chunk_id in row.get("gold_chunk_ids") or []}
    gold_in_window = (
        None if refusal else len(gold_chunks & set(retrieved_ids))
    )
    dense_ranks = [ranks.get(chunk_id) for chunk_id in gold_chunks if ranks.get(chunk_id)]
    return {
        "id": row.get("id") or f"{row['_stem']}#{row.get('question', '')[:40]}",
        "book": row["_stem"],
        "kind": row.get("kind", ""),
        "source": row.get("_source", "primary"),
        "question": question,
        "gold_chapters": gold_chapters,
        "retrieved_chapters": retrieved,
        "retrieved_chunk_ids": retrieved_ids,
        "missed_chapters": missed,
        "coverage": coverage,
        "recall": recall,
        "gold_chunks_in_window": gold_in_window,
        "gold_chunk_count": len(gold_chunks) if not refusal else 0,
        "refusal_clean": clean,
        "gate_terms": terms,
        "first_gold_dense_rank": min(dense_ranks) if dense_ranks else None,
        "matter_slots": [chapter for chapter in retrieved if chapter in matter],
        "window_chars": window_chars,
        "window_passages": window_passages,
        "verified": row.get("verified", True),
        "defects": row.get("_defects", []),
    }


def summarize(results):
    answerable = [r for r in results if r["coverage"] is not None]
    coverages = [r["coverage"] for r in answerable]
    ranks = [r["first_gold_dense_rank"] for r in answerable if r["first_gold_dense_rank"]]
    refusals = [r for r in results if r["coverage"] is None]
    kinds = {}
    for kind in sorted({r["kind"] for r in answerable}):
        group = [r for r in answerable if r["kind"] == kind]
        if len(group) < SUBSET_MIN_ROWS:
            continue
        kinds[kind] = {
            "rows": len(group),
            "coverage_mean": statistics.fmean(r["coverage"] for r in group),
            "recall_mean": sum(1 for r in group if r["recall"]) / len(group),
        }
    return {
        "rows": len(results),
        "answerable_rows": len(answerable),
        "refusal_rows": len(refusals),
        "refusal_clean": sum(1 for r in refusals if r["refusal_clean"]),
        "coverage_mean": statistics.fmean(coverages) if coverages else 0.0,
        "coverage_zero": sum(1 for c in coverages if c == 0.0),
        "coverage_full": sum(1 for c in coverages if c == 1.0),
        "recall_mean": (
            sum(1 for r in answerable if r["recall"]) / len(answerable)
            if answerable
            else 0.0
        ),
        "mean_first_gold_dense_rank": statistics.fmean(ranks) if ranks else None,
        "gold_chunks_in_window_mean": (
            statistics.fmean(
                r["gold_chunks_in_window"]
                for r in answerable
                if r["gold_chunks_in_window"] is not None
            )
            if answerable
            else 0.0
        ),
        "gold_rows_without_dense_rank": sum(
            1 for r in answerable if r["first_gold_dense_rank"] is None
        ),
        "matter_slot_rows": sum(1 for r in results if r["matter_slots"]),
        "window_chars_mean": statistics.fmean(r["window_chars"] for r in results),
        "window_passages_mean": statistics.fmean(r["window_passages"] for r in results),
        "kinds": kinds,
    }


def display_path(path):
    """A path relative to the repo when it is inside it, else as given."""
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def output(summaries, results, label, stamp, dataset_path):
    lines = []
    lines.append(f"retrieval-recall label={label} stamp={stamp}")
    lines.append(f"dataset={display_path(dataset_path)} rows={len(results)}")
    total_coverages = [r["coverage"] for r in results if r["coverage"] is not None]
    total_answerable = len(total_coverages)
    total_recall = sum(1 for r in results if r["recall"]) 
    lines.append("")
    for summary in summaries:
        rank = summary["mean_first_gold_dense_rank"]
        lines.append(
            f"{summary['book']}: rows={summary['rows']} "
            f"coverage@5={summary['coverage_mean']:.3f} "
            f"recall@5={summary['recall_mean']:.3f} "
            f"coverage_zero={summary['coverage_zero']} "
            f"coverage_full={summary['coverage_full']} "
            f"mean_first_gold_dense_rank={'-' if rank is None else round(rank, 1)} "
            f"matter_slot_rows={summary['matter_slot_rows']} "
            f"goldchunks={summary['gold_chunks_in_window_mean']:.2f} "
            f"window={summary['window_passages_mean']:.1f} "
            f"window_chars={summary['window_chars_mean']:.0f} "
            f"refusals={summary['refusal_rows']} "
            f"refusals_clean={summary['refusal_clean']}"
        )
        for kind, subset in summary["kinds"].items():
            lines.append(
                f"  kind {kind}: rows={subset['rows']} "
                f"coverage@5={subset['coverage_mean']:.3f} "
                f"recall@5={subset['recall_mean']:.3f}"
            )
    lines.append(
        f"TOTAL: rows={len(results)} answerable={total_answerable} "
        f"coverage@5={statistics.fmean(total_coverages) if total_coverages else 0.0:.3f} "
        f"recall@5={(total_recall / total_answerable) if total_answerable else 0.0:.3f} "
        f"coverage_zero={sum(1 for c in total_coverages if c == 0.0)} "
        f"coverage_full={sum(1 for c in total_coverages if c == 1.0)}"
    )
    mismatched = [
        result for result in results
        if result["coverage"] == 1.0 and result["recall"] is False
    ]
    if mismatched:
        lines.append(
            f"coverage!=recall: {len(mismatched)} row(s) at coverage 1.0 with a chunk "
            f"recall miss (e.g. {mismatched[0]['id']}) — coverage is how the fiction "
            f"defect shows; chunk recall is what decides a ship."
        )
    profiled = [
        result for result in results
        if result["kind"] == "entity" and len(result["gold_chapters"]) >= 2
    ]
    if profiled:
        lines.append(
            f"entity-profile caveat: {len(profiled)} entity row(s) span >=2 gold "
            f"chapters; answer.ask runs _entity_profile_body before "
            f"retrieval_context, so this window is the retrieval defect, not the "
            f"window the model sees for those asks (e.g. {profiled[0]['id']})."
        )
    lines.append("")
    lines.append("rows:")
    for result in results:
        state = "ok  " if result["coverage"] == 1.0 else "MISS"
        if result["coverage"] is None:
            state = "ref "
        terms = ",".join(result["gate_terms"]) or "-"
        matter = ",".join(result["matter_slots"]) or "-"
        rank = result["first_gold_dense_rank"]
        if result["coverage"] is None:
            metric = f"refusal_clean={'yes' if result['refusal_clean'] else 'no'}"
        else:
            metric = (
                f"cov={result['coverage']:.2f} "
                f"recall={'yes' if result['recall'] else 'no'} "
                f"goldchunks={result['gold_chunks_in_window']}/{result['gold_chunk_count']} "
                f"dense_rank={rank if rank is not None else '-'}"
            )
        lines.append(
            f"  {state} win={result['window_passages']} {metric} gate={terms} matter={matter}\n"
            f"       {result['id']}: {result['question']}\n"
            f"       gold={result['gold_chapters']} "
            f"retrieved={result['retrieved_chapters']}"
        )
    defects = [r for r in results if r["defects"]]
    lines.append("")
    if defects:
        lines.append(f"DATA DEFECTS: {len(defects)}")
        for result in defects:
            lines.append(f"  {result['id']}: {'; '.join(result['defects'])}")
    else:
        lines.append("DATA DEFECTS: 0")
    return "\n".join(lines) + "\n"


def compare(before_path, summaries):
    """Per-book delta against a saved before run's JSON."""
    path = Path(before_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise SystemExit(f"--compare: no such before file: {path}")
    before = json.loads(path.read_text(encoding="utf-8"))
    old = {summary["book"]: summary for summary in before.get("summaries", [])}
    lines = [
        "",
        f"== delta vs {display_path(path)} (label={before.get('label', '?')})",
    ]
    for summary in summaries:
        book = summary["book"]
        prior = old.get(book)
        if prior is None:
            lines.append(f"{book}: new in this run")
            continue
        cov_delta = summary["coverage_mean"] - prior["coverage_mean"]
        rec_delta = summary["recall_mean"] - prior["recall_mean"]
        prior_chars = prior.get("window_chars_mean")
        chars = (
            f"{prior_chars:.0f} -> {summary['window_chars_mean']:.0f}"
            if prior_chars is not None
            else f"- -> {summary['window_chars_mean']:.0f}"
        )
        prior_window = prior.get("window_passages_mean")
        window = (
            f"{prior_window:.1f} -> {summary['window_passages_mean']:.1f}"
            if prior_window is not None
            else f"- -> {summary['window_passages_mean']:.1f}"
        )
        lines.append(f"{book}:")
        lines.append(
            f"  coverage {prior['coverage_mean']:.3f} -> {summary['coverage_mean']:.3f} "
            f"({cov_delta:+.3f}) | recall {prior['recall_mean']:.3f} -> "
            f"{summary['recall_mean']:.3f} ({rec_delta:+.3f}) | matter "
            f"{prior['matter_slot_rows']} -> {summary['matter_slot_rows']} | "
            f"window {window} | chars {chars}"
        )
    return lines


def failures(summaries):
    problems = []
    for summary in summaries:
        book = summary["book"]
        if summary["coverage_mean"] < COVERAGE_THRESHOLD:
            problems.append(
                f"{book}: coverage@5 {summary['coverage_mean']:.3f} < {COVERAGE_THRESHOLD:.2f}"
            )
        if summary["recall_mean"] < RECALL_THRESHOLD:
            problems.append(
                f"{book}: recall@5 {summary['recall_mean']:.3f} < {RECALL_THRESHOLD:.2f}"
            )
        for kind, subset in summary["kinds"].items():
            if subset["coverage_mean"] < SUBSET_THRESHOLD:
                problems.append(
                    f"{book}/{kind}: coverage@5 {subset['coverage_mean']:.3f} "
                    f"< {SUBSET_THRESHOLD:.2f}"
                )
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="before", help="before or after; names the run files")
    parser.add_argument("--dataset", help="evaluate this pinned dataset instead of merging fragments")
    parser.add_argument("--compare", help="before-run JSON to print a per-book delta table against")
    parser.add_argument(
        "--gate",
        choices=("rare", "terms"),
        default="rare",
        help="lexical gate: rare (pre-fix) or terms (keywords.lexical_terms)",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=1,
        help="fusion.MAX_LEXICAL_CANDIDATES for this run (pre-fix 1)",
    )
    parser.add_argument(
        "--additions",
        default="0",
        help="chunks appended by fusion.fuse(added=N): 0, 1, 2, or engine (bookkind policy)",
    )
    parser.add_argument(
        "--engine-window",
        action="store_true",
        help="start from the book's own passage limit (fiction 8, technical 5) instead of 5",
    )
    parser.add_argument(
        "--dense-only",
        action="store_true",
        help="skip the lexical leg entirely; the dense window is the whole measurement",
    )
    parser.add_argument("--failures-only", action="store_true", help="print only rows below full coverage")
    parser.add_argument("--json", action="store_true", help="emit the full result as JSON")
    args = parser.parse_args()

    if hasattr(fusion, "MAX_LEXICAL_CANDIDATES"):
        fusion.MAX_LEXICAL_CANDIDATES = max(1, args.max_candidates)
    if args.additions != "engine" and not str(args.additions).isdigit():
        parser.error("--additions must be 0, 1, 2, or engine")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    by_stem, by_id = book_indexes()
    if args.dataset:
        dataset_path = Path(args.dataset)
        if not dataset_path.is_absolute():
            dataset_path = ROOT / dataset_path
        rows = read_jsonl(dataset_path)
    else:
        rows = merge_rows()
        dataset_path = write_dataset(rows, args.label, stamp)

    for row in rows:
        stem = resolve_book(row, by_stem, by_id)
        row["_stem"] = stem
        row["_defects"] = []

    results_by_book = collections.defaultdict(list)
    for stem in dict.fromkeys(row["_stem"] for row in rows):
        index = retrieve.load_index(by_stem[stem])
        word_map = keywords.postings(index)
        matter = matter_chapters(index)
        all_text = " ".join(
            chunk.get("text") or "" for chunk in index.get("chunks") or []
        )
        for row in (row for row in rows if row["_stem"] == stem):
            defects = check_row(row, index, all_text)
            if not row.get("verified", True):
                defects.append("row is declared verified: false")
            row["_defects"] = defects
            results_by_book[stem].append(
                run_row(
                    index,
                    row,
                    word_map,
                    matter,
                    gate_mode=args.gate,
                    engine_window=args.engine_window,
                    additions=args.additions,
                    dense_only=args.dense_only,
                )
            )

    summaries = [summarize(results_by_book[stem]) | {"book": stem} for stem in results_by_book]
    results = [result for stem in results_by_book for result in results_by_book[stem]]

    report = output(summaries, results, args.label, stamp, dataset_path)
    if args.compare:
        report += "\n".join(compare(args.compare, summaries)) + "\n"
    RUNS.mkdir(parents=True, exist_ok=True)
    raw_path = RUNS / f"retrieval-recall-{args.label}-{stamp}.txt"
    json_path = RUNS / f"retrieval-recall-{args.label}-{stamp}.json"
    raw_path.write_text(report, encoding="utf-8")
    json_path.write_text(
        json.dumps({"label": args.label, "summaries": summaries, "rows": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    latest = RUNS / f"retrieval-recall-{args.label}-latest.txt"
    latest.write_text(report, encoding="utf-8")
    latest_json = RUNS / f"retrieval-recall-{args.label}-latest.json"
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

    if args.json:
        print(json.dumps({"label": args.label, "summaries": summaries, "rows": results}, indent=2))
    else:
        if args.failures_only:
            report = "\n".join(
                line for line in report.splitlines()
                if not line.startswith("  ok  ") and not line.startswith("       ")
            ) + "\n"
        print(report)
    print(f"raw: {raw_path.relative_to(ROOT)}")
    print(f"json: {json_path.relative_to(ROOT)}")
    print(f"dataset: {display_path(dataset_path)}")

    defects = [result for result in results if result["defects"]]
    problems = failures(summaries)
    print("\n== thresholds")
    print(
        f"coverage@5 >= {COVERAGE_THRESHOLD:.2f} per book, "
        f"recall@5 >= {RECALL_THRESHOLD:.2f} per book, "
        f"coverage@5 >= {SUBSET_THRESHOLD:.2f} per (book, kind) with >= {SUBSET_MIN_ROWS} rows"
    )
    for problem in problems:
        print(f"FAIL {problem}")
    if defects:
        print(f"FAIL data: {len(defects)} row(s) failed mechanical verification")
        for result in defects:
            print(f"  {result['id']}: {'; '.join(result['defects'])}")
        return 2
    if problems:
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
