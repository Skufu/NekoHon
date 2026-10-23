"""x2d dataset builder: form-augmented quote-or-refuse rows for the finetune.

Extends the 2026-10-13 reference pipeline
("artifacts/probes/build-finetune-data-2026-10-13.py", imported via importlib,
never copied) with the two inputs produced for the x2d run:
- data/finetune/x2d-forms-2026-10-14.json: extra ANSWER cards (measured
  sloppy forms of train cards — swaps, lowercase, bare headings, greetings),
  each carrying its source card's pin and softness.
- data/finetune/x2d-refusal-candidates.json: new out-of-book refusal
  candidates with the teacher's exact completion on record.

x2d deltas from the reference:
- PERTURB_SWAPS are NOT applied in place. Source entries are captured as-is
  (both the original and the perturbed form stay in training) and the swap
  forms arrive as extras (class "swap").
- Refusals are not oversampled (REFUSAL_REPEAT dropped): the kept reference
  refusals plus the new candidates file, each unique question exactly once.
- Answer rows = kept train-source answers + kept extras. An extra failing any
  acceptance gate (teacher refusal, no citation, non-verbatim quote, hard-pin
  miss, gloss failure, malformed item) is rejected and counted, never written.

Write-time safety (real build only; every failure prints REFUSING and leaves
the disk untouched): missing or malformed input files, planned-row ceiling
below MIN_TOTAL_ROWS, captured total below MIN_TOTAL_ROWS, train/bench
question overlap > 0, built bench question set != the current bench.jsonl
question set, or duplicate questions within a split.

Modes:
- --dry-run: no teacher calls and no index load; prints entries by
  source/class, projected rows, the bench-set diff and overlap counts.
- --limit N: captures the first N planned entries through the shipped seam
  and prints the preview; writes nothing.
- --stub-inputs DIR: reads the two x2d inputs from DIR instead (dry-run and
  limit only) so the plumbing can be checked before the real files land.

Run: python artifacts/probes/build-finetune-x2d-2026-10-14.py [--dry-run]
Writes data/finetune/quote-refuse-2026-10-13.{train,bench}-x2d.jsonl and
.stats-x2d.json (gitignored) plus
artifacts/evidence/finetune-data-prep/finetune-data-prep-2026-10-14-x2d.log.
The canonical train/bench/stats files are never touched; the verifier pass
needs a temporary canonical-name copy swap (see
artifacts/reports/x2d-builder-notes-2026-10-14.md).
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import NoReturn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))


def _load_reference():
    """The 2026-10-13 builder imported as the pipeline of record."""
    path = HERE / "build-finetune-data-2026-10-13.py"
    spec = importlib.util.spec_from_file_location(
        "build_finetune_data_reference", path
    )
    if spec is None or spec.loader is None:
        _refuse(f"cannot load the reference builder at {_display(path)}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REF = _load_reference()
TEACHER_MODEL = REF.TEACHER_MODEL
SYSTEM = REF.SYSTEM
PARAPHRASE_SYSTEM = REF.PARAPHRASE_SYSTEM
# Imported for parity/reporting; split_for() already consults the same
# pattern tuple internally for source entries and extras alike.
BENCH_PATTERNS = REF.BENCH_PATTERNS
REFUSAL_CANDIDATES = REF.REFUSAL_CANDIDATES
# Imported but deliberately never applied: x2d takes swaps as extras.
PERTURB_SWAPS = REF.PERTURB_SWAPS

OUT = ROOT / "data" / "finetune"
DATASET_TRAIN = OUT / "quote-refuse-2026-10-13.train-x2d.jsonl"
DATASET_BENCH = OUT / "quote-refuse-2026-10-13.bench-x2d.jsonl"
STATS = OUT / "quote-refuse-2026-10-13.stats-x2d.json"
BENCH_CURRENT = OUT / "quote-refuse-2026-10-13.bench.jsonl"
FORMS_INPUT = OUT / "x2d-forms-2026-10-14.json"
REFUSALS_INPUT = OUT / "x2d-refusal-candidates.json"
LOG = (ROOT / "artifacts" / "evidence" / "finetune-data-prep"
       / "finetune-data-prep-2026-10-14-x2d.log")
# Previous build stats, newest first: consulted by --dry-run to explain a
# bench overshoot (entries the teacher rejected at capture never reach the
# frozen bench file, so they appear as a projected-but-absent question).
PREV_STATS = (
    OUT / "quote-refuse-2026-10-13.stats-x2c.json",
    OUT / "quote-refuse-2026-10-13.stats.json",
)
MIN_TOTAL_ROWS = 300
STUB_HINT = ("for a plumbing dry-run before the file exists, use "
             "--dry-run --stub-inputs DIR")


def _refuse(message) -> NoReturn:
    print(f"REFUSING: {message}", file=sys.stderr)
    raise SystemExit(1)


def _display(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_json_list(path, what):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _refuse(f"missing input file: {_display(path)} ({what}) — {STUB_HINT}")
    except json.JSONDecodeError as error:
        _refuse(f"input file {_display(path)} ({what}) is not valid JSON: "
                f"{error}")
    if not isinstance(data, list):
        _refuse(f"input file {_display(path)} ({what}) must be a JSON array, "
                f"got {type(data).__name__}")
    return data


def parse_forms(items):
    """Validated x2d extra answer cards; malformed items are counted drops."""
    forms, malformed = [], []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            malformed.append({"index": index, "reason": "not-an-object"})
            continue
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            malformed.append({"index": index, "reason": "missing-question"})
            continue
        pin = item.get("pin")
        if pin is not None and not isinstance(pin, str):
            malformed.append({"index": index, "question": question.strip(),
                              "reason": "pin-not-string-or-null"})
            continue
        forms.append({
            "question": question.strip(),
            "pin": (pin.strip() or None) if isinstance(pin, str) else None,
            "soft": bool(item.get("soft")),
            "class": str(item.get("class") or "unknown").strip() or "unknown",
            "source_card": (item.get("source_card") or None),
            "asked_probe": (item.get("asked_probe") or None),
        })
    return forms, malformed


def parse_refusal_candidates(items):
    """Validated new refusal candidates; a missing completion is malformed."""
    candidates, malformed = [], []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            malformed.append({"index": index, "reason": "not-an-object"})
            continue
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            malformed.append({"index": index, "reason": "missing-question"})
            continue
        completion = item.get("completion")
        if not isinstance(completion, str) or not completion.strip():
            malformed.append({"index": index, "question": question.strip(),
                              "reason": "missing-completion"})
            continue
        asked = item.get("asked")
        candidates.append({
            "question": question.strip(),
            "asked": asked.strip() if isinstance(asked, str) else None,
            "completion": completion.strip(),
        })
    return candidates, malformed


def plan_entries(forms, candidates):
    """Deterministic entry order: reference source entries (as-is), then the
    forms file's extras, then the new refusal candidates. First occurrence of
    a question string wins; later duplicates and inputs that would land in
    the frozen bench (split_for == "bench") are dropped and counted."""
    source, extras, new_refusals = [], [], []
    source_drops, extras_drops, refusal_drops = Counter(), Counter(), Counter()
    seen = set()

    for entry in REF.source_entries():
        question = entry["question"]
        if question in seen:
            source_drops["duplicate-within-source"] += 1
            continue
        seen.add(question)
        source.append(entry)

    for form in forms:
        question = form["question"]
        if question in seen:
            extras_drops["extras-duplicate"] += 1
            continue
        entry = {
            "question": question, "pin": form["pin"], "expect": "answer",
            "source": "x2d-" + form["class"], "soft": form["soft"],
            "source_card": form["source_card"], "asked_probe": form["asked_probe"],
        }
        if REF.split_for(entry) == "bench":
            extras_drops["extras-bench-protected"] += 1
            continue
        seen.add(question)
        extras.append(entry)

    for item in candidates:
        question = item["question"]
        if question in seen:
            refusal_drops["new-refusal-duplicate"] += 1
            continue
        entry = {
            "question": question, "pin": None, "expect": "refuse",
            "source": "x2d-refusal-mined", "soft": False,
            "file_completion": item["completion"],
            "asked_probe": item["asked"],
        }
        if REF.split_for(entry) == "bench":
            refusal_drops["new-refusal-bench-protected"] += 1
            continue
        seen.add(question)
        new_refusals.append(entry)

    return source, extras, new_refusals, source_drops, extras_drops, refusal_drops


def plan_diagnostics(extras, planned):
    """Pure pre-capture checks on the forms file's own claims (reported,
    never gating): source_card agreement and asked_probe consistency."""
    by_question = {entry["question"]: entry for entry in planned}
    # Source cards are looked up among all planned entries, including other
    # extras (a form of a form would still report its card's pin/softness).
    missing_card, pin_soft_mismatch, asked_probe_mismatch = [], [], []
    for extra in extras:
        card_question = extra.get("source_card")
        card = by_question.get(card_question) if isinstance(card_question, str) else None
        if card is None:
            missing_card.append(extra["question"])
        elif (card.get("pin") != extra["pin"]
              or bool(card.get("soft")) != bool(extra["soft"])):
            pin_soft_mismatch.append({
                "question": extra["question"],
                "source_card": card_question,
                "card": {"pin": card.get("pin"), "soft": bool(card.get("soft"))},
                "extra": {"pin": extra["pin"], "soft": bool(extra["soft"])},
            })
        probe = extra.get("asked_probe")
        if (isinstance(probe, str) and probe.strip()
                and REF.A.canonical_query(extra["question"]) != probe.strip()):
            asked_probe_mismatch.append({
                "question": extra["question"],
                "asked_probe": probe.strip(),
                "canonical_query": REF.A.canonical_query(extra["question"]),
            })
    return {
        "source_card_missing": missing_card,
        "pin_soft_mismatch_vs_source_card": pin_soft_mismatch,
        "asked_probe_mismatch": asked_probe_mismatch,
    }


def previous_build_rejects():
    """Capture rejects from the newest previous stats file, tagged by split;
    None when no parseable stats file exists."""
    for path in PREV_STATS:
        if not path.exists():
            continue
        try:
            stats = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        bench, other = [], []
        for reject in stats.get("rejects") or []:
            question = reject.get("question")
            if not isinstance(question, str):
                continue
            split = REF.split_for({"question": question,
                                   "source": reject.get("source") or ""})
            (bench if split == "bench" else other).append(question)
        return {
            "file": path.name,
            "questions": stats.get("questions"),
            "rejects_bench": bench,
            "rejects_other_count": len(other),
        }
    return None


def read_current_bench():
    """The frozen hold-out: question set and rows from the current bench."""
    try:
        raw = BENCH_CURRENT.read_text(encoding="utf-8")
    except FileNotFoundError:
        _refuse(f"missing the frozen bench file {_display(BENCH_CURRENT)} — "
                "cannot run the bench-set check")
    questions, rows = set(), []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            _refuse(f"{_display(BENCH_CURRENT)} line {number}: not JSON "
                    f"({error})")
        rows.append(row)
        questions.add((row.get("meta") or {}).get("question"))
    return questions, rows


def dry_run(planned, extras, new_refusals, drops, forms_meta, refusals_meta,
            forms_malformed, refusals_malformed, forms_path, refusals_path,
            stubbed):
    """Planning report; no index load, no teacher calls, nothing written."""
    _source_drops, extras_drops, refusal_drops = drops
    train = [entry for entry in planned if REF.split_for(entry) == "train"]
    bench = [entry for entry in planned if REF.split_for(entry) == "bench"]
    train_answers = [e for e in train if e["expect"] == "answer"]
    train_refusals = [e for e in train if e["expect"] == "refuse"]

    print("x2d builder — DRY RUN (no index load, no teacher calls, "
          "nothing written)")
    if stubbed:
        print(f"STUB INPUT MODE — the two x2d inputs are stubs from "
              f"{_display(forms_path.parent)} (plumbing test only)")
    print(f"inputs: forms={_display(forms_path)} "
          f"({len(forms_meta) + len(forms_malformed)} items), "
          f"refusals={_display(refusals_path)} "
          f"({len(refusals_meta) + len(refusals_malformed)} items)")
    print(f"source entries as-is (no PERTURB_SWAPS applied): {len(planned) - len(extras) - len(new_refusals)}"
          f"  [reference refusal candidates: {len(REFUSAL_CANDIDATES)}]")

    by_source = Counter(entry["source"] for entry in planned)
    print(f"entries by source/class: "
          f"{dict(sorted(by_source.items()))}")
    extras_by_class = Counter(entry["source"] for entry in extras)
    print(f"extras kept: {len(extras)} of "
          f"{len(forms_meta) + len(forms_malformed)} forms "
          f"(drops: {dict(extras_drops)}; malformed: {len(forms_malformed)})"
          f"  by class: {dict(sorted(extras_by_class.items()))}")
    print(f"new refusal candidates kept: {len(new_refusals)} of "
          f"{len(refusals_meta) + len(refusals_malformed)} "
          f"(drops: {dict(refusal_drops)}; malformed: {len(refusals_malformed)})")

    print(f"planned entries: {len(planned)} — train {len(train)} "
          f"({len(train_answers)} answer + {len(train_refusals)} refusal), "
          f"bench {len(bench)}")
    previous = previous_build_rejects()
    if previous is not None:
        prior = (f"previous build ({previous['file']}): "
                 f"{previous['questions']} planned -> "
                 f"{previous['rejects_other_count'] + len(previous['rejects_bench'])} rejects")
    else:
        prior = "previous build stats unavailable"
    print(f"projected rows ceiling: {len(planned)} ({prior}; capture rejects "
          f"reduce the total)")
    floor_note = ("above" if len(planned) >= MIN_TOTAL_ROWS else
                  "BELOW — a real build on these inputs would refuse")
    print(f"row floor: MIN_TOTAL_ROWS={MIN_TOTAL_ROWS} — ceiling {floor_note}")

    available = {value for value in PERTURB_SWAPS.values()}
    covered = sum(1 for entry in extras if entry["question"] in available)
    print(f"PERTURB_SWAPS swap forms among kept extras: {covered} of "
          f"{len(available)} (report only; extras are the forms agent's set)")

    diagnostics = plan_diagnostics(extras, planned)
    print(f"extras diagnostics: source_card missing "
          f"{len(diagnostics['source_card_missing'])}, pin/soft mismatch vs "
          f"source card {len(diagnostics['pin_soft_mismatch_vs_source_card'])}, "
          f"asked_probe mismatch {len(diagnostics['asked_probe_mismatch'])}")

    current_questions, _current_rows = read_current_bench()
    planned_bench = {entry["question"] for entry in bench}
    excluded = set(previous["rejects_bench"]) if previous else set()
    projected = planned_bench - excluded
    missing = sorted(current_questions - projected)
    extra = sorted(projected - current_questions)
    print(f"bench-set diff vs {BENCH_CURRENT.name} "
          f"({len(current_questions)} questions):")
    if excluded:
        print(f"  previous bench capture rejects excluded: {len(excluded)} "
              f"{sorted(excluded)}")
    print(f"  projected bench questions: {len(projected)}; missing from "
          f"projection: {len(missing)} {missing}; extra: {len(extra)} {extra}"
          f" -> {'MATCH' if not missing and not extra else 'MISMATCH'}")

    train_questions = {entry["question"] for entry in train}
    bench_questions = {entry["question"] for entry in bench}
    overlap = sorted(train_questions & bench_questions)
    print(f"train/bench question overlap: {len(overlap)} {overlap}")
    duplicate_train = sorted(
        q for q, count in Counter(e["question"] for e in train).items()
        if count > 1)
    duplicate_bench = sorted(
        q for q, count in Counter(e["question"] for e in bench).items()
        if count > 1)
    print(f"duplicate questions within train entries: {len(duplicate_train)}; "
          f"within bench entries: {len(duplicate_bench)}")
    asked = Counter(REF.A.canonical_query(e["question"]).strip().lower()
                    for e in planned)
    same_asked = sorted(a for a, count in asked.items() if count > 1)
    print(f"same-asked forms (case-folded, informational): {len(same_asked)} "
          f"groups")

    clean = (not missing and not extra and not overlap
             and not duplicate_train and not duplicate_bench)
    print(f"dry-run verdict: {'CLEAN' if clean else 'PROBLEMS (see above)'}")
    if stubbed:
        print("note: stub mode exercises plumbing only; the floor check "
              "engages on the real inputs")
    return 0 if clean else 1


def limit_preview(entries):
    """Capture the first N planned entries and print them; writes nothing."""
    print(f"--limit preview: capturing {len(entries)} planned entries through "
          f"the shipped seam (teacher {TEACHER_MODEL}); writing NOTHING")
    index = REF.load_index(REF.INDEX)
    outcomes, by_tier = Counter(), Counter()
    consecutive_errors = 0
    for number, entry in enumerate(entries, 1):
        try:
            record, failure = REF.capture(index, entry["question"], TEACHER_MODEL)
        except Exception as error:
            outcomes["capture-error"] += 1
            consecutive_errors += 1
            print(f"[{number:>3}/{len(entries)}] CAPTURE-ERROR "
                  f"{type(error).__name__}: {error}")
            if consecutive_errors >= 3:
                _refuse("3 consecutive capture errors — is Ollama serving "
                        "127.0.0.1:11434? aborting the preview, nothing written")
            continue
        consecutive_errors = 0
        if failure is not None:
            outcomes[failure["outcome"]] += 1
            print(f"[{number:>3}/{len(entries)}] NO-CAPTURE "
                  f"{failure['outcome']}  {entry['question'][:60]!r}")
            continue
        tier, note = REF.evaluate(entry, record)
        if tier is None:
            outcomes[note.split(":")[0]] += 1
            print(f"[{number:>3}/{len(entries)}] REJECT {note}  "
                  f"{entry['question'][:60]!r}")
            continue
        by_tier[tier] += 1
        print(f"[{number:>3}/{len(entries)}] {tier:8s} "
              f"asked={record['asked'][:50]!r} cited={record['cited'][:1]}  "
              f"<- {entry['question'][:50]!r}")
    print(f"preview summary: tiers {dict(by_tier)}; outcomes {dict(outcomes)}")
    print("wrote nothing.")
    return 0


def capture_all(index, planned):
    """The reference capture loop minus in-place swaps and oversampling.

    Returns rows, rejects, outcomes, by_tier, by_source_root and the
    refusal file-completion crosscheck counter.
    """
    rows, rejects, outcomes = [], [], Counter()
    by_tier, by_source_root = Counter(), Counter()
    refusal_crosscheck = Counter()
    consecutive_errors = 0
    for number, entry in enumerate(planned, 1):
        try:
            record, failure = REF.capture(index, entry["question"], TEACHER_MODEL)
        except Exception as error:
            outcomes["capture-error"] += 1
            consecutive_errors += 1
            rejects.append({"question": entry["question"],
                            "source": entry["source"],
                            "outcome": f"capture-error:{type(error).__name__}"})
            if consecutive_errors >= 3:
                _refuse("3 consecutive capture errors — is Ollama serving "
                        "127.0.0.1:11434? nothing written")
            continue
        consecutive_errors = 0
        if failure is not None:
            outcomes[failure["outcome"]] += 1
            rejects.append({"question": entry["question"],
                            "source": entry["source"], **failure})
            continue
        tier, note = REF.evaluate(entry, record)
        if tier is None:
            outcomes[note.split(":")[0]] += 1
            rejects.append({
                "question": entry["question"], "asked": record["asked"],
                "source": entry["source"], "outcome": note,
                "cited": record["cited"][:2],
            })
            continue
        if tier == "refusal":
            target, synthesized = REF.A.REFUSAL, False
            outcomes["refusal-kept"] += 1
            # Crosscheck only: the candidate file's recorded completion vs
            # the fresh capture. The mechanical gate above is what counts.
            stored = entry.get("file_completion")
            if stored is not None:
                outcome = ("file-completion-matches-capture"
                           if stored.strip() == record["completion"].strip()
                           else "file-completion-differs-from-capture")
                refusal_crosscheck[outcome] += 1
        else:
            # Target building copied from the reference builder's main(),
            # with one added gate: the verifier requires exactly two lines
            # and a gloss that is neither [Ch.-tagged nor the quote itself.
            lines = [line for line in record["completion"].splitlines()
                     if line.strip()]
            quote_line = f'[Ch. {record["chapter"]}] "{record["quote"]}"'
            tail = lines[1:]
            if tail and not tail[-1].strip().startswith("[Ch."):
                gloss, synthesized = tail[-1].strip(), False
                outcomes["teacher-gloss"] += 1
            else:
                gloss = REF.A._clean_rewrite(REF.A.ollama_generate(
                    PARAPHRASE_SYSTEM, f"Sentence: {record['quote']}",
                    TEACHER_MODEL
                ))
                if not gloss:
                    outcomes["gloss-synth-failed"] += 1
                    rejects.append({
                        "question": entry["question"],
                        "asked": record["asked"],
                        "source": entry["source"],
                        "outcome": "gloss-synth-failed",
                        "cited": record["cited"][:2],
                    })
                    continue
                synthesized = True
                outcomes["gloss-synthesized"] += 1
            target = f"{quote_line}\n{gloss}"
            if (target.splitlines() != [quote_line, gloss]
                    or not gloss.strip()
                    or gloss.strip().startswith("[Ch.")
                    or gloss.strip() == record["quote"].strip()):
                outcomes["target-shape"] += 1
                rejects.append({
                    "question": entry["question"], "asked": record["asked"],
                    "source": entry["source"], "outcome": "target-shape",
                    "cited": record["cited"][:2],
                })
                continue
        by_source_root[entry["source"].split("-")[0]] += 1
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
                "split": REF.split_for(entry),
                "tier": tier,
                "pin": entry["pin"],
                "cited": record["cited"][:2],
                "canonical_fired": record["canonical_fired"],
                "synthesized_gloss": synthesized,
                "note": note,
            },
        })
        if number % 20 == 0:
            print(f"... {number}/{len(planned)} captured")
    return rows, rejects, outcomes, by_tier, by_source_root, refusal_crosscheck


def _serialize_rows(rows, split):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n"
                   for row in rows if row["meta"]["split"] == split)


def real_build(planned, forms_meta, refusals_meta, forms_path, refusals_path,
               stubbed, drops, source, extras, new_refusals, malformed):
    source_drops, extras_drops, refusal_drops = drops
    forms_malformed, refusals_malformed = malformed
    if stubbed:
        _refuse("stub inputs are for previews only; refusing to build a "
                "dataset from stubs")
    if len(planned) < MIN_TOTAL_ROWS:
        _refuse(f"planned-row ceiling {len(planned)} < {MIN_TOTAL_ROWS} — "
                "the build cannot reach the floor even with zero rejects; "
                "nothing written")
    print(f"x2d builder — real build: {len(planned)} planned entries "
          f"(teacher {TEACHER_MODEL}, shipped seam); writing when the "
          f"safety checks pass")
    index = REF.load_index(REF.INDEX)
    (rows, rejects, outcomes, by_tier, by_source_root,
     refusal_crosscheck) = capture_all(index, planned)
    train_rows = [row for row in rows if row["meta"]["split"] == "train"]
    bench_rows = [row for row in rows if row["meta"]["split"] == "bench"]
    total = len(rows)
    if total < MIN_TOTAL_ROWS:
        _refuse(f"total rows {total} < {MIN_TOTAL_ROWS} "
                f"(train {len(train_rows)} + bench {len(bench_rows)}) — "
                "nothing written")
    train_questions = {row["meta"]["question"] for row in train_rows}
    bench_questions = {row["meta"]["question"] for row in bench_rows}
    overlap = sorted(train_questions & bench_questions)
    if overlap:
        _refuse(f"train/bench question overlap {len(overlap)}: "
                f"{overlap[:5]} — nothing written")
    duplicate_train = sorted(
        q for q, count in Counter(r["meta"]["question"]
                                  for r in train_rows).items() if count > 1)
    duplicate_bench = sorted(
        q for q, count in Counter(r["meta"]["question"]
                                  for r in bench_rows).items() if count > 1)
    if duplicate_train or duplicate_bench:
        _refuse(f"duplicate questions within a split "
                f"(train {duplicate_train[:3]}, bench {duplicate_bench[:3]}) "
                "— nothing written")
    current_questions, current_rows = read_current_bench()
    missing = sorted(current_questions - bench_questions)
    extra = sorted(bench_questions - current_questions)
    if bench_questions != current_questions:
        _refuse(
            f"built bench question set differs from {BENCH_CURRENT.name}: "
            f"missing {len(missing)} {missing[:5]}, extra {len(extra)} "
            f"{extra[:5]} — nothing written. (A previously rejected bench "
            "entry passing again counts as a change; investigate before "
            "re-running.)")
    print(f"bench check passed: {len(bench_questions)} questions identical to "
          f"{BENCH_CURRENT.name}")

    train_text = _serialize_rows(rows, "train")
    bench_text = _serialize_rows(rows, "bench")
    sha_train = hashlib.sha256(train_text.encode("utf-8")).hexdigest()
    sha_bench = hashlib.sha256(bench_text.encode("utf-8")).hexdigest()
    current_text = BENCH_CURRENT.read_text(encoding="utf-8")
    current_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
    built_by_question = {row["meta"]["question"]: row["messages"][2]["content"]
                         for row in bench_rows}
    current_by_question = {}
    for line in current_text.splitlines():
        if line.strip():
            row = json.loads(line)
            current_by_question[row["meta"]["question"]] = (
                row["messages"][2]["content"])
    differing = sorted(q for q in bench_questions if q in current_by_question
                       and built_by_question[q] != current_by_question[q])
    bench_check = {
        "current_file": BENCH_CURRENT.name,
        "current_rows": len(current_rows),
        "built_rows": len(bench_rows),
        "question_set_identical": True,
        "byte_identical": sha_bench == current_sha,
        "current_sha256": current_sha,
        "built_sha256": sha_bench,
        "content_differing_questions": differing,
    }

    by_split = Counter(row["meta"]["split"] for row in rows)
    written = {"train": len(train_rows), "bench": len(bench_rows)}

    def extras_class_stats(entries):
        return dict(sorted(Counter(e["source"] for e in entries).items()))

    stats = {
        "builder": "artifacts/probes/build-finetune-x2d-2026-10-14.py",
        "teacher": TEACHER_MODEL,
        "inputs": {
            "forms": _display(forms_path), "refusals": _display(refusals_path),
            "stub": stubbed,
            "forms_received": len(forms_meta),
            "forms_malformed": forms_malformed,
            "refusals_received": len(refusals_meta),
            "refusals_malformed": refusals_malformed,
        },
        "source_entries": len(source),
        "extras": {
            "kept": len(extras), "drops": dict(extras_drops),
            "by_class": extras_class_stats(extras),
        },
        "new_refusal_candidates": {
            "kept": len(new_refusals), "drops": dict(refusal_drops),
        },
        "source_drops": dict(source_drops),
        "questions": len(planned),
        # x2d never applies the swaps in place; kept at 0 for shape parity.
        "perturb_swaps": 0,
        "rows": total,
        "by_split": dict(by_split),
        "by_tier": dict(by_tier),
        "by_source_root": dict(by_source_root),
        "outcomes": dict(outcomes),
        "oversampled_copies": 0,
        "written": written,
        "files": {"train": DATASET_TRAIN.name, "bench": DATASET_BENCH.name},
        "hashes": {"train_sha256": sha_train, "bench_sha256": sha_bench},
        "bench_check": bench_check,
        "refusal_file_crosscheck": dict(refusal_crosscheck),
        "plan_diagnostics": plan_diagnostics(extras, planned),
        "rejects": rejects,
    }

    log_lines = [
        f"finetune data prep x2d 2026-10-14 — teacher {TEACHER_MODEL}",
        (f"inputs: forms={_display(forms_path)} ({len(forms_meta)} items), "
         f"refusals={_display(refusals_path)} ({len(refusals_meta)} items)"),
        (f"source entries as-is (no PERTURB_SWAPS): {len(source)}  "
         f"extras kept: {len(extras)}  new refusals kept: "
         f"{len(new_refusals)}"),
        (f"questions: {len(planned)}  rows kept: {total}  "
         f"tiers: {dict(by_tier)}"),
        (f"splits: {dict(by_split)}  files: {DATASET_TRAIN.name} / "
         f"{DATASET_BENCH.name}"),
        f"sources: {dict(by_source_root)}",
        f"outcomes: {dict(outcomes)}",
        f"sha256: train {sha_train}  bench {sha_bench}",
        (f"bench check: built {len(bench_rows)} questions vs "
         f"{BENCH_CURRENT.name} {len(current_rows)} — set identical True, "
         f"bytes identical {bench_check['byte_identical']}"
         + (f", content differing {differing}" if differing else "")),
        f"refusal file crosscheck: {dict(refusal_crosscheck)}",
        "",
        "reject samples:",
    ]
    for reject in rejects[:15]:
        log_lines.append(f"  {reject}")
    log_lines += ["", "row samples:"]
    for row in rows[:3]:
        head = row["messages"][2]["content"].replace("\n", " / ")[:220]
        log_lines.append(
            f"  [{row['meta']['tier']}] {row['meta']['asked'][:60]!r} -> {head}")
    log_lines += [
        "",
        ("next: verify + contamination via the canonical-name copy swap "
         "(artifacts/reports/x2d-builder-notes-2026-10-14.md)"),
    ]
    log_text = "\n".join(log_lines)

    OUT.mkdir(parents=True, exist_ok=True)
    DATASET_TRAIN.write_text(train_text, encoding="utf-8")
    DATASET_BENCH.write_text(bench_text, encoding="utf-8")
    STATS.write_text(json.dumps(stats, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(log_text, encoding="utf-8")
    print(log_text)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the x2d finetune dataset (quote-or-refuse, form "
                    "augmented) through the shipped seam.")
    parser.add_argument("--dry-run", action="store_true",
                        help="plan and check inputs; no teacher calls, "
                             "nothing written")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="capture only the first N planned entries, "
                             "print a preview, write nothing")
    parser.add_argument("--stub-inputs", type=Path, default=None, metavar="DIR",
                        help="read the two x2d inputs from DIR instead "
                             "(dry-run/limit only)")
    args = parser.parse_args(argv)

    if args.dry_run and args.limit is not None:
        _refuse("--dry-run and --limit are exclusive")
    if args.limit is not None and args.limit <= 0:
        _refuse("--limit must be a positive integer")
    stubbed = args.stub_inputs is not None
    if stubbed and not (args.dry_run or args.limit is not None):
        _refuse("--stub-inputs is for previews only (--dry-run or --limit); "
                "refusing to build a dataset from stubs")

    forms_path = args.stub_inputs / FORMS_INPUT.name if stubbed else FORMS_INPUT
    refusals_path = (args.stub_inputs / REFUSALS_INPUT.name
                     if stubbed else REFUSALS_INPUT)

    forms_meta, forms_malformed = parse_forms(
        _load_json_list(forms_path, "x2d extra answer cards"))
    refusals_meta, refusals_malformed = parse_refusal_candidates(
        _load_json_list(refusals_path, "x2d refusal candidates"))
    source, extras, new_refusals, source_drops, extras_drops, refusal_drops = \
        plan_entries(forms_meta, refusals_meta)
    planned = source + extras + new_refusals

    if args.dry_run:
        return dry_run(planned, extras, new_refusals,
                       (source_drops, extras_drops, refusal_drops),
                       forms_meta, refusals_meta, forms_malformed,
                       refusals_malformed, forms_path, refusals_path, stubbed)
    if args.limit is not None:
        return limit_preview(planned[:args.limit])
    return real_build(planned, forms_meta, refusals_meta, forms_path,
                      refusals_path, stubbed,
                      (source_drops, extras_drops, refusal_drops),
                      source, extras, new_refusals,
                      (forms_malformed, refusals_malformed))


if __name__ == "__main__":
    main()
