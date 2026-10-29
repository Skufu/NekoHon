"""Answer-quality ranking, fair replay (checkables + voted yes/no bits).

Plan: artifacts/plans/answer-quality-judge-plan-2026-10-15.md, "Rating method
v2". Layer 1 is machine-checkable and deterministic (refusal correct against a
reviewed answerability label, quoted spans verbatim in the passages the answer
itself cited). Layer 2 is four yes/no bits, each asked three times, majority
decides; the defect label is derived from the first failed check, not asked of
the judge in one shot.

Fairness rules (2026-10-29):

- **No retrieval on replay.** The old answers were produced against the
  retrieval of their day. Re-running retrieval would judge them against a top-5
  they never saw. Evidence is read only from the row's frozen `passages`
  (chunk_id, chapter, text) — the same schema `behavioral_eval.freeze_result`
  writes. Legacy rows that carry no frozen passages are **unverifiable**: that
  is not an invented claim and not a clean pass.
- A quotation must resolve to the passage the answer **cited**, not to any
  passage in the top-5. A quote found only in an uncited shown passage is
  `wrong-citation`; a quote found nowhere in the frozen evidence is
  `invented-claim`. Explicit citation records are authoritative: a chapter tag
  never widens a citation to every passage in that chapter. A chapter used as a
  fallback is evidence only when exactly one frozen passage carries it; several
  matches are ambiguous, and ambiguous evidence is **unverifiable**.
- `gold_cited` (chapter pins) and `key_fact_present` (regex) are **advisory**
  facts, never correctness. They are reported and never create a defect.
- An unknown or malformed judge reply is `judge_error`, never
  `invented-claim` and never `none`. That includes a completeness axis that is
  not exactly one of 0..3.
- Owner labels (`rating`) and synthetic stand-ins (`persona_rating`,
  `checker_rating`) are reported separately. A refusal is judged against the
  `expect` only when an answerability review is recorded; otherwise the row is
  `unreviewed-answerability`.
- **Completeness is the judge's 0-3 axis, not a regex.** `J.judge_complete`
  checks whether the answer carries the requested information; 0/1 is a real
  miss (`incomplete-list`, `incomplete-comparison`, or `incomplete` by question
  shape), 2/3 passes. Counting commas, requiring both names in a comparison, or
  calling a short definition complete by default would repeat the regex bias
  this harness exists to remove. The no-reask bit is recorded as
  `no_reask_advisory` and never creates a defect.

Run:
    python artifacts/harnesses/rank-answers.py --set artifacts/datasets/owner-rated-2026-10-15.jsonl --label owner-sample-m3
    JUDGE_BACKEND=ollama python ... (offline granite judge)

Writes artifacts/evidence/answer-quality/answer-quality-<label>-<judge-slug>.{json,log}.
An existing evidence file is never overwritten unless `--overwrite` is passed.

Verdicts are UNVALIDATED against human labels; rater agreement is reported
only over rows with a decisive verdict.

This ranking is a list, not a verdict — NOT A GATE. Measured 2026-10-15: two
identical method-v2 runs wobbled 3 of 27 rows on single 2-1 vote flips, and
only rows 25-27 carry owner labels (the rest are persona/checker stand-ins). A
--gate flag is rejected; adopting one needs a new owner decision. main() with
the normal flags exits 0 regardless of defect counts.
"""

import argparse
import copy
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import answer as A
import judge as J
from canonical import canonical_query

OWNER_FIELD = "rating"
SYNTHETIC_FIELDS = ("persona_rating", "checker_rating")
# The judged numbers are a triage dial, not a pass/fail gate (see the module
# docstring for the measured wobble). Any attempt to turn them into an exit
# code via a flag is rejected before a single row is judged.
GATE_FLAGS = ("--gate", "--gate-on-defects", "--fail-on-defects")
GATE_REJECTION = (
    "NOT A GATE: judged numbers are a triage dial, not a pass/fail gate.\n"
    "Measured 2026-10-15: two identical method-v2 runs wobbled 3 of 27 rows\n"
    "on single 2-1 vote flips; only rows 25-27 carry owner labels.\n"
    "Adopting a gate needs a new owner decision — a flag is not one."
)

# Defects that make a row unscorable rather than proven good or bad.
UNSCORED_DEFECTS = ("unverifiable", "judge_error", "unreviewed-answerability")
# Defects that are a real reader-facing failure (worst-first tier 0).
FAILURE_DEFECTS = ("false-refusal", "invented-claim", "wrong-citation", "uncited")

BITS = ("answers_question", "grounded", "clean_form", "no_reask")
GOOD_WHEN_YES = ("answers_question", "grounded", "clean_form")
VOTES = 3
HARNESS_VERSION = "rank-answers-fair-2026-10-29"
TAG_PATTERN = re.compile(r"\[Ch\.\s*([^\]]+)\]")
QUOTE_PATTERN = re.compile(r'"([^"]{20,})"')
DISCLOSURE_PATTERN = re.compile(r"^(Asked as:|Read as:)", re.I)

# Generic English cues only; no book terms, no chunk ids. These name the
# defect label for a failed completeness axis; they never decide correctness.
COMPARISON_CUE = re.compile(
    r"\b(vs\.?|versus|trade-?offs?|difference(?:s)?\s+(?:between|from)"
    r"|differ(?:s|ence)?\s+from|compare[sd]?\s+(?:to|with|and))\b",
    re.I,
)
LIST_CUE = re.compile(
    r"\b(types?|kinds?|categories|advantages?|disadvantages?|benefits?|drawbacks?"
    r"|factors?|steps?|stages?|components?|characteristics|examples?"
    r"|reasons?|ways|requirements?|challenges?|methods?|options?|criteria"
    r"|list|name)\b",
    re.I,
)
COMPLETE_PASS = ("2", "3")
COMPLETE_FAIL = ("0", "1")
COMPLETE_LABELS = {"list": "incomplete-list", "comparison": "incomplete-comparison"}


def content_text(answer):
    """The answer minus disclosure lines — the text the reader judges.

    Precedent: groundedness.answer_sentences drops the Read-as line the same
    way; a disclosure is product furniture, not a claim about the book.
    """
    lines = [
        line for line in (answer or "").splitlines()
        if not DISCLOSURE_PATTERN.match(line.strip())
    ]
    return "\n".join(lines).strip()


def slug(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")


def load_rows(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    return data["items"] if isinstance(data, dict) else data


def chapter_of(chunk_id):
    head = str(chunk_id).split("-", 1)[0]
    return str(int(head[2:])) if head.startswith("ch") and head[2:].isdigit() else head


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def cited_chapters(row):
    tags = {m.group(1).strip() for m in TAG_PATTERN.finditer(row.get("answer") or "")}
    stored = {str(c).strip() for c in row.get("chapters") or []}
    return tags or stored


def frozen_passages(row):
    """The row's frozen passages; never re-retrieved, never re-embedded.

    A passage without its own text cannot support a verdict: the current index
    is not the index the answer saw. Returns (passages, reasons_missing).
    """
    raw = (
        row.get("passages")
        or row.get("frozen_passages")
        or row.get("shown_passages")
        or []
    )
    missing = []
    passages = []
    if not isinstance(raw, list):
        return [], ["frozen passages are malformed"]
    for entry in raw:
        if not isinstance(entry, dict):
            missing.append("frozen passage is malformed")
            continue
        chunk_id = entry.get("chunk_id")
        text = entry.get("text")
        if not chunk_id:
            missing.append("frozen passage has no chunk_id")
            continue
        if not isinstance(text, str) or not text.strip():
            missing.append(f"passage {chunk_id} has no frozen text")
            continue
        if "sha256" in entry and entry["sha256"] != digest({
            key: entry.get(key) for key in ("chunk_id", "chapter", "text")
        }):
            missing.append(f"passage {chunk_id} snapshot hash mismatch")
            continue
        passages.append({
            "chunk_id": str(chunk_id),
            "chapter": str(entry.get("chapter", "")),
            "text": text,
            "shown": bool(entry.get("shown", True)),
        })
    if not passages and not missing:
        missing.append("no frozen shown/cited passages on the row (legacy answer)")
    return passages, missing


def evidence_digest(passages):
    if not passages:
        return None
    core = [
        {"chunk_id": p["chunk_id"], "chapter": p["chapter"], "text": p["text"]}
        for p in passages
    ]
    return digest(core)


def cited_passage_ids(row, passages):
    """(cited ids, ambiguous chapters).

    Explicit citation records are authoritative and are returned alone: a
    chapter tag must never widen a citation to every passage in that chapter.
    A chapter is a fallback only, and only when exactly one frozen passage
    carries it; two or more matches are ambiguous, not evidence.
    """
    ids = []
    for cite in row.get("citations") or []:
        chunk_id = cite.get("chunk_id") if isinstance(cite, dict) else cite
        if chunk_id:
            ids.append(str(chunk_id))
    ids.extend(str(c) for c in row.get("cited_chunks") or [])
    if ids:
        return list(dict.fromkeys(ids)), []
    ambiguous = []
    for chapter in cited_chapters(row):
        matches = [p["chunk_id"] for p in passages if p["chapter"] == chapter]
        if len(matches) == 1:
            ids.append(matches[0])
        elif len(matches) > 1:
            ambiguous.append(chapter)
    return list(dict.fromkeys(ids)), sorted(set(ambiguous))


def has_quoted_span(answer_text):
    return bool(QUOTE_PATTERN.search(answer_text or ""))


def resolve_quote(answer_text, passages, cited_ids, ambiguous_chapters=(),
                  unresolved_citations=()):
    """True / 'elsewhere' / False / None for every quotation in the answer.

    True: every span occurs in a cited passage whose frozen text is present.
    'elsewhere': every span occurs in the frozen evidence, but at least one
    only in a passage the answer did not cite (wrong citation, not invention).
    False: at least one span occurs in no frozen passage.
    None: no span, no frozen evidence, no resolved citation, a cited passage
    whose text is not frozen, or a chapter tag that matches several passages.
    Missing and ambiguous evidence are unverifiable, never invention.
    """
    spans = [m.group(1) for m in QUOTE_PATTERN.finditer(answer_text)]
    if not spans:
        return None, "no quoted span"
    if not passages:
        return None, "no frozen passage to check the quote"
    cited = set(cited_ids)
    if not cited and ambiguous_chapters:
        return None, "chapter-only evidence matches several passages (ambiguous)"
    if not cited:
        return None, "no cited passage resolved from the answer"
    cited_texts = [p["text"] for p in passages if p["chunk_id"] in cited]
    statuses = []
    for span in spans:
        in_cited = any(A._quote_in_passage(span, text) for text in cited_texts)
        in_evidence = any(A._quote_in_passage(span, p["text"]) for p in passages)
        statuses.append((in_cited, in_evidence))
    if cited_texts and all(in_cited for in_cited, _ in statuses):
        return True, None
    if ambiguous_chapters:
        # A span that missed every resolved citation might live in the
        # ambiguous chapter's sibling; that is unknown, not wrong.
        return None, "chapter-only evidence matches several passages (ambiguous)"
    if unresolved_citations:
        return None, "cited passage text is missing from the frozen evidence"
    if all(in_cited or in_evidence for in_cited, in_evidence in statuses):
        return "elsewhere", "quote resolves only to a passage the answer did not cite"
    return False, "quote resolves to no frozen passage"


def question_kind(question):
    """Label only: does a completeness failure concern a list or a comparison."""
    asked = canonical_query(question or "")
    if COMPARISON_CUE.search(asked):
        return "comparison", asked
    if LIST_CUE.search(asked):
        return "list", asked
    return "other", asked


def completeness_verdict(kind, axis):
    """Strict 0-3 completeness axis -> (defect, detail).

    The judge checks the requested information; the harness never counts
    commas, both names in a comparison, or a definition's length. An axis that
    is not exactly one of 0..3 is a judge_error, never a pass.
    """
    if axis not in ("0", "1", "2", "3"):
        return "judge_error", {"axis": axis, "verdict": "invalid-axis"}
    if axis in COMPLETE_PASS:
        return None, {"axis": axis, "verdict": "complete"}
    return (
        COMPLETE_LABELS.get(kind, "incomplete"),
        {"axis": axis, "verdict": "missing-requested-information"},
    )


def reviewed_expect(row):
    """The reviewed answerability label, or None when the row carries none."""
    review = row.get("expectation_review")
    if isinstance(review, dict):
        expect = review.get("expect")
        if (
            expect in ("answer", "refuse")
            and review.get("reason")
            and review.get("reviewer")
            and (review.get("question_sha256") in (None, digest(row.get("question"))))
        ):
            return expect
    if row.get("answerability_reviewed") is True and row.get("expect") in ("answer", "refuse"):
        return row["expect"]
    return None


def majority(votes):
    values = [v for v in votes if v in ("yes", "no", "judge_error")]
    if not values:
        return "error"
    label, count = Counter(values).most_common(1)[0]
    if count < 2:
        return "error"
    return label


def default_judge_call(bit, question, passages_text, answer_text, timeout):
    return J.judge_bit(
        bit, question, passages_text, answer_text, timeout=timeout
    )


def default_complete_call(question, passages_text, answer_text, timeout):
    return J.judge_complete(
        question, passages_text, answer_text, timeout=timeout
    )


def judge_row(row, timeout=90.0, judge_call=None, complete_call=None,
              judge_label=None, pace=0.25):
    """Judge one stored answer from its frozen evidence. Never retrieves."""
    call = judge_call or default_judge_call
    complete = complete_call or default_complete_call
    judge = judge_label or J.judge_name()
    out = dict(row)
    answer_text = content_text(row.get("answer"))
    asked = canonical_query(row["question"])
    passages, missing = frozen_passages(row)
    out["evidence_state"] = "frozen" if passages else "missing"
    out["evidence_missing"] = missing
    out["evidence_sha256"] = evidence_digest(passages)

    reviewed = reviewed_expect(row)
    out["expect_reviewed"] = reviewed
    out["expect_advisory"] = row.get("expect") if reviewed is None else None
    out["refusal_ok"] = (
        (bool(row.get("refused")) == (reviewed == "refuse")) if reviewed else None
    )
    out["refusal_ok_advisory"] = (
        (bool(row.get("refused")) == (row.get("expect") == "refuse"))
        if reviewed is None and row.get("expect") in ("answer", "refuse")
        else None
    )

    chapters = cited_chapters(row)
    gold = row.get("gold_chunks") or []
    out["gold_cited"] = (
        any(chapter_of(cid) in chapters for cid in gold)
        if gold and not row.get("refused")
        else None
    )  # advisory: a chapter pin, never correctness

    key_fact = row.get("key_fact")
    out["key_fact_present"] = (
        bool(re.search(key_fact, answer_text, re.I)) if key_fact else None
    )  # advisory: a regex, never correctness

    cited_ids, ambiguous = cited_passage_ids(row, passages)
    frozen_ids = {p["chunk_id"] for p in passages}
    unresolved = [cid for cid in cited_ids if cid not in frozen_ids]
    out["cited_chunks"] = cited_ids
    out["cited_unresolved"] = unresolved
    out["ambiguous_cited_chapters"] = ambiguous
    if row.get("refused"):
        out["quote_ok"], out["quote_note"] = None, None
    else:
        out["quote_ok"], out["quote_note"] = resolve_quote(
            answer_text, passages, cited_ids, ambiguous, unresolved
        )

    passages_text = A.passages_block(passages) if passages else ""
    out["votes"] = {}
    out["judge_calls"] = []
    if not row.get("refused") and passages:
        for bit in BITS:
            votes = []
            for _ in range(VOTES):
                value = call(bit, asked, passages_text, answer_text, timeout)
                votes.append(value)
                out["judge_calls"].append({"axis": bit, "value": value,
                    "transport": copy.deepcopy(J.LAST_CALL) if judge_call is None
                    else {"provenance": "injected judge double; not a live measurement"}})
            if pace:
                time.sleep(pace)  # pace the relay; 503 on bursts measured 2026-10-15
            out["votes"][bit] = votes
            out[bit] = majority(votes)
    else:
        # A bit asked against no frozen evidence would be a vote on nothing;
        # the row is unverifiable (or a refusal) and is never scored on it.
        for bit in BITS:
            out[bit] = None

    kind, _ = question_kind(row.get("question"))
    out["question_kind"] = kind
    out["complete_axis"] = None
    out["no_reask_advisory"] = out.get("no_reask") == "yes"
    if not row.get("refused") and passages:
        try:
            out["complete_axis"] = complete(
                asked, passages_text, answer_text, timeout
            )
            out["judge_calls"].append({"axis": "complete", "value": out["complete_axis"],
                "transport": copy.deepcopy(J.LAST_CALL) if complete_call is None
                else {"provenance": "injected judge double; not a live measurement"}})
        except Exception as exc:  # noqa: BLE001 - an unavailable axis is not a pass
            out["complete_axis"] = None
            out["complete_error"] = repr(exc)
    if row.get("refused") or not passages:
        complete_defect, complete_detail = None, {"axis": None, "verdict": "not-checked"}
    else:
        complete_defect, complete_detail = completeness_verdict(
            kind, out["complete_axis"]
        )
    out["completeness"] = complete_detail

    if row.get("refused"):
        if reviewed is None:
            out["defect"] = "unreviewed-answerability"
        elif reviewed == "answer":
            out["defect"] = "false-refusal"
        else:
            out["defect"] = "none"
    elif not passages or missing:
        out["defect"] = "unverifiable"
    elif any(out.get(bit) not in ("yes", "no") for bit in BITS):
        out["defect"] = "judge_error"
    elif (
        out.get("quote_ok") is None
        and has_quoted_span(answer_text)
        and (ambiguous or unresolved)
    ):
        out["defect"] = "unverifiable"
    elif out.get("quote_ok") is False:
        out["defect"] = "invented-claim"
    elif out.get("quote_ok") == "elsewhere":
        out["defect"] = "wrong-citation"
    elif has_quoted_span(answer_text) and out.get("quote_ok") is None:
        out["defect"] = "uncited"
    elif out.get("answers_question") != "yes":
        out["defect"] = "wrong-subject"
    elif out.get("grounded") != "yes":
        out["defect"] = "invented-claim"
    elif out.get("clean_form") != "yes":
        out["defect"] = "format-drift"
    elif complete_defect:
        out["defect"] = complete_defect
    else:
        out["defect"] = "none"

    out["provenance"] = {
        "harness_version": HARNESS_VERSION,
        "question_sha256": digest(row.get("question") or ""),
        "answer_sha256": digest(row.get("answer") or ""),
        "judge_input_sha256": digest({
            "question": asked,
            "passages": passages_text,
            "answer": answer_text,
        }),
        "prompt_sha256": {bit: digest(J.BIT_SYSTEMS[bit]) for bit in BITS},
        "complete_prompt_sha256": digest(J.COMPLETE_SYSTEM),
        "complete_axis": out["complete_axis"],
        "judge": judge,
        "answer_model": row.get("answer_model") or "unknown",
        "embedding_model": row.get("embedding_model") or "unknown",
        "source": row.get("source"),
        "index_sha256": row.get("index_sha256"),
        "evidence_sha256": out["evidence_sha256"],
        "evidence_state": out["evidence_state"],
        "evidence_chunks": [p["chunk_id"] for p in passages],
        "cited_chunks": cited_ids,
        "cited_unresolved": unresolved,
        "ambiguous_cited_chapters": ambiguous,
        "raw_votes": out["votes"],
    }
    return out


def flagged(row):
    """Any proven or unscorable failure — the machine's 'not clean'.

    Advisory pins (gold chapter, key-fact regex) never flag a row; they are
    recorded facts, not correctness.
    """
    if row.get("refusal_ok") is False:
        return True
    if row.get("quote_ok") is False or row.get("quote_ok") == "elsewhere":
        return True
    for bit in BITS:
        value = row.get(bit)
        if value in (None, "error"):
            continue
        if value != ("yes" if bit in GOOD_WHEN_YES else "no"):
            return True
    return row.get("defect") not in (None, "none")


def scorable(row):
    return row.get("defect") not in UNSCORED_DEFECTS


def rank_tier(row):
    if row.get("refusal_ok") is False:
        return 0
    if row.get("defect") in FAILURE_DEFECTS:
        return 0
    if flagged(row):
        return 1
    return 2


def _agreement(rows, field):
    rated = [r for r in rows if r.get(field)]
    scored = [r for r in rated if scorable(r)]
    agree = sum(1 for r in scored if (r[field] == "good") == (not flagged(r)))
    bads = [r for r in scored if r[field] == "bad"]
    bads_flagged = [r for r in bads if flagged(r)]
    return rated, scored, agree, bads_flagged, bads


def rater_summary(rows):
    lines = []
    for field in (OWNER_FIELD,) + SYNTHETIC_FIELDS:
        rated, scored, agree, bads_flagged, bads = _agreement(rows, field)
        if not rated:
            continue
        kind = "owner labels" if field == OWNER_FIELD else "synthetic stand-in labels"
        unscored = len(rated) - len(scored)
        lines.append(
            f"# {field} ({kind}): agreement {agree}/{len(scored)}"
            f" | bads flagged {len(bads_flagged)}/{len(bads)}"
            f" | unscored {unscored}/{len(rated)}"
        )
    return lines


def ensure_writable(path, overwrite):
    """Never alter an old evidence file by accident (parent decision 2026-10-29)."""
    if path.exists() and not overwrite:
        try:
            shown = path.relative_to(ROOT)
        except ValueError:
            shown = path
        print(
            f"refusing to overwrite {shown} — pass --overwrite "
            "or use a new --label; old evidence is not rewritten",
            file=sys.stderr,
        )
        raise SystemExit(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", required=True)
    parser.add_argument("--label", default="run")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--overwrite", action="store_true",
                        help="rewrite an existing evidence file (off by default)")
    parser.add_argument(*GATE_FLAGS, dest="gate", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.gate:
        print(GATE_REJECTION, file=sys.stderr)
        sys.exit(2)

    path = Path(args.set)
    if not path.is_absolute():
        path = ROOT / path
    rows = load_rows(path)
    if args.limit:
        rows = rows[: args.limit]

    judge_name = J.judge_name()
    judged = []
    skipped = []
    for row in rows:
        if not row.get("answer"):
            skipped.append(row.get("id"))
            continue
        started = time.time()
        try:
            out = judge_row(row, timeout=args.timeout, judge_label=judge_name)
        except Exception as exc:  # noqa: BLE001 - record and keep going
            out = dict(row)
            out["defect"] = "judge_error"
            out["judge_error"] = repr(exc)
            print(f'{row.get("id"):>3} judge_error: {exc!r}')
        out["seconds"] = round(time.time() - started, 1)
        judged.append(out)
        bits = " ".join(
            f"{'A' if b == 'answers_question' else 'G' if b == 'grounded' else 'F' if b == 'clean_form' else 'R'}"
            f"{'Y' if out.get(b) == ('yes' if b in GOOD_WHEN_YES else 'no') else out.get(b, '-')}"
            for b in BITS
        )
        marks = (
            f"{'ok' if out.get('refusal_ok') else 'REF!' if out.get('refusal_ok') is False else 'ref?'} "
            f"g{'Y' if out.get('gold_cited') else 'N' if out.get('gold_cited') is False else '-'} "
            f"k{'Y' if out.get('key_fact_present') else 'N' if out.get('key_fact_present') is False else '-'} "
            f"q{'Y' if out.get('quote_ok') is True else 'C' if out.get('quote_ok') == 'elsewhere' else 'N' if out.get('quote_ok') is False else '-'} "
            f"| {bits}"
        )
        print(f'{out.get("id"):>3} {out["defect"]:<22} {marks:<30} {str(row.get("question"))[:40]}')

    ordered = sorted(judged, key=lambda r: (rank_tier(r), str(r.get("id"))))
    counts = Counter(r["defect"] for r in judged)
    unverifiable = counts["unverifiable"]
    judge_errors = counts["judge_error"]
    unreviewed = counts["unreviewed-answerability"]

    out_dir = ROOT / "artifacts" / "evidence" / "answer-quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"answer-quality-{args.label}-{slug(judge_name)}"
    json_path = out_dir / f"{stem}.json"
    log_path = out_dir / f"{stem}.log"
    ensure_writable(json_path, args.overwrite)
    ensure_writable(log_path, args.overwrite)

    summary_lines = [
        f"# answer-quality ranking (fair replay: checkables + voted bits) — {args.label}"
        f" — {len(judged)} judged | {len(skipped)} skipped — judge {judge_name}",
        "# fair replay: NO retrieval on replay; evidence comes only from the row's frozen passages",
        "# layer 1 checkables: refusal_ok / quote_ok (cited passage only) — deterministic;"
        " layer 2 bits voted 3x, majority (A answers, G grounded, F clean form, R no-reask)",
        "# completeness is the judge's strict 0-3 axis (0/1 miss, 2/3 pass);"
        " no_reask is advisory only and never a defect",
        "# defect derived from the first failed check, not asked of the judge",
    ] + rater_summary(judged) + [
        f"# unverifiable {unverifiable}/{len(judged)}: legacy answers carry no frozen"
        " shown/cited passages — not defects, not clean",
        f"# judge_error {judge_errors}/{len(judged)}: unknown or malformed judge replies"
        " are never invention and never a clean pass",
        f"# unreviewed answerability {unreviewed}/{len(judged)}: refusals are judged"
        " only against a recorded answerability review",
        "# regex/chapter pins (gold_cited, key_fact_present) are advisory, never correctness",
        "# chapter-only evidence is used only when exactly one frozen passage matches;"
        " several matches are ambiguous and unverifiable",
        "# UNVALIDATED against human labels — a triage list, not a score.",
        "# NOT A GATE — judged numbers are a triage dial, not a pass/fail gate; --gate is rejected.",
        "# persona/checker stand-in ratings are not owner labels — only rows 25-27 carry owner labels.",
        "",
    ]

    table = ["rank | id | rated | defect | cmp | refusal_ok | gold* | key* | quote | A G F R | question"]
    for position, row in enumerate(ordered, start=1):
        rated = row.get("rating") or row.get("persona_rating") or row.get("checker_rating") or "-"
        bits = " ".join(str(row.get(b) or "-") for b in BITS)
        table.append(
            f'{position:4} | {row.get("id"):>3} | {rated:<5} | {row["defect"]:<22} | '
            f'{str(row.get("complete_axis") or "-"):<3} | '
            f'{str(row.get("refusal_ok")):<10} | '
            f'{"Y" if row.get("gold_cited") else "N" if row.get("gold_cited") is False else "-"} | '
            f'{"Y" if row.get("key_fact_present") else "N" if row.get("key_fact_present") is False else "-"} | '
            f'{"Y" if row.get("quote_ok") is True else "C" if row.get("quote_ok") == "elsewhere" else "N" if row.get("quote_ok") is False else "-"} | '
            f'{bits:<11} | {str(row.get("question"))[:44]}'
        )
        pin_note = row.get("pin_note")
        if pin_note:
            table.append(f'     |     | pin: {pin_note}')

    log_path.write_text("\n".join(summary_lines + table) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {"label": args.label, "judge": judge_name, "set": str(path.name),
             "harness_version": HARNESS_VERSION,
             "counts": dict(sorted(counts.items())),
             "rows": ordered, "skipped": skipped},
            ensure_ascii=False, indent=1,
        ) + "\n",
        encoding="utf-8",
    )
    print("\n" + "\n".join(summary_lines))
    print(f"wrote {json_path.relative_to(ROOT)}")
    print(f"wrote {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
