"""Reviewed-response evaluation: grade a captured answer without trusting words.

This module answers one question: *given the sources the model actually saw, a
captured output, and an independent review record, may this output be called
PASS?* It is offline and deterministic. It never calls a model, a judge, an
index, or the network, and it never re-retrieves. Actual shown evidence is the
only evidence text it reads.

The three-way rule is versioned (`reviewed-semantics-v2`). A review binds the
exact output, input, evidence set, citation set, reference content, criterion
version, and (when captured) model and engine fingerprints. Change any of them
and the review is stale (`REVIEW`), never a silent pass. v1 reviews predate the
structural quote-attribution rule: they go stale, they are never retroactively
certified. The failed Go judge v3
calibration is retained elsewhere; it is never read here and cannot approve an
answer.

Quote attribution is structural at both stages: a quotation is a book claim
only when a `[Ch. ...]` tag directly owns it or a structured citation carries
its text explicitly. The engine's `Asked as:`/`Read as:` disclosure lines are
metadata about the question, not book quotations, and only the SYSTEM stage is
engine output: a raw MODEL line with the same label is a model claim. At that
stage they are recognized only as a whole labeled line with one quotation, so a
tag or extra text on the same line is never hidden. The graded bytes, including
disclosures, stay unchanged and remain bound by the review's output digest.

Two statuses stay independent:

- ``mechanical`` — behaviour, exact refusal, quote/citation integrity, echo,
  quote-only, truncation, and capture provenance.
- ``semantic`` — a source-backed review's judgement. A correct quote is not an
  answer, so an answer/gloss cannot PASS on mechanics alone.

``readiness`` is separate: an unreviewed, unbound, or stale golden cannot be
used as truth. A pending golden therefore cannot produce a PASS, even with a
perfect response. That is deliberate.

Record shape and review shape:
``artifacts/runs/data-repair-2026-10-29/evaluation/REVIEW-SCHEMA.md``.

CLI::

    python artifacts/harnesses/reviewed_eval.py \\
        --golden PATH --responses PATH [--reviews PATH] \\
        [--stage model|system|both] [--split dev,test,review] \\
        [--json] [--out PATH] [--no-self-check] \\
        [--golden-readiness] [--train-corpus PATH]

JSON on stdout with ``--json``; exit 0 PASS, 1 REVIEW, 2 FAIL. ``--out`` never
overwrites an existing report: before/after runs are separate files, so a
historical score is never rewritten. Stdlib only.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import chapter_labels

ROOT = Path(__file__).resolve().parent.parent.parent

EVALUATOR = {
    "name": "reviewed_eval",
    "version": "1.1.4",
    "schema_version": 1,
    "criterion_version": "reviewed-semantics-v2",
    "reference_version": "golden-schema-v1",
}
REFUSAL = "Not in this book."
STAGES = ("model", "system")
SPLITS = ("train", "dev", "test", "review")
DEFAULT_SPLITS = ("dev", "test", "review")
KINDS = ("answer", "gloss", "refusal")
BEHAVIORS = ("answer", "refuse", "boundary")
REVIEW_VERDICTS = ("pass", "fail", "review")
REVIEW_PROVENANCES = ("agent", "owner")
RANK = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
EXIT = {"PASS": 0, "REVIEW": 1, "FAIL": 2}

TAG_RE = re.compile(r"\[Ch\.\s*([^\]]+)\]")
QUOTE_RE = re.compile(r'"[^"]*"|“[^”]*”')
QUOTE_OPENER_RE = re.compile(r'["“]')
ATTACHED_GAP_RE = re.compile(r"[\s,;:./·\-–—]*")
DISCLOSURE_LINE_RE = re.compile(
    r'\s*(?:Asked as|Read as)\s*:\s*(?:"[^"]*"|“[^”]*”)\s*[.!]?\s*',
    re.IGNORECASE,
)
FIGURE_RE = re.compile(r"\(Figure\s+\d+-\d+\)", re.IGNORECASE)
WS_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[^\W_]", re.UNICODE)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _sha_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _sha_hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(value):
    return _sha_text(_canonical(value))


def _norm_text(value):
    return " ".join((value or "").casefold().split())


def _norm_claim(value):
    return _norm_text(value).rstrip(" .;:!?")


def _verdict(findings):
    worst = "PASS"
    for finding in findings:
        if RANK[finding["verdict"]] > RANK[worst]:
            worst = finding["verdict"]
    return worst


def _finding(code, verdict, detail, subject, scope):
    return {
        "code": code,
        "verdict": verdict,
        "detail": detail,
        "subject": subject,
        "scope": scope,
    }


def _fail(code, detail, subject, scope):
    return _finding(code, "FAIL", detail, subject, scope)


def _review(code, detail, subject, scope):
    return _finding(code, "REVIEW", detail, subject, scope)


def _codes(findings):
    return list(dict.fromkeys(finding["code"] for finding in findings))


class _SourceView:
    """One actual shown passage. Text is whatever the capture says was shown."""

    def __init__(self, raw, position):
        self.position = position
        self.raw = raw if isinstance(raw, dict) else {}
        self.source_id = self.raw.get("source_id")
        self.book_id = self.raw.get("book_id")
        self.chunk_id = self.raw.get("chunk_id")
        self.chapter = self.raw.get("chapter")
        self.figure_id = self.raw.get("figure_id")
        self.text = self.raw.get("text")
        self.chapter_key = _chapter_key(self.chapter)

    @property
    def has_text(self):
        return isinstance(self.text, str)

    def identity(self):
        return {
            "source_id": self.source_id,
            "book_id": self.book_id,
            "chunk_id": self.chunk_id,
            "chapter": self.chapter,
            "figure_id": self.figure_id,
            "text_sha256": _sha_text(self.text if self.has_text else ""),
        }


def _chapter_key(value):
    return chapter_labels.chapter_key(value)


def _sources(response):
    evidence = response.get("evidence") if isinstance(response.get("evidence"), dict) else {}
    raw = evidence.get("sources")
    if not isinstance(raw, list):
        return []
    return [_SourceView(item, index) for index, item in enumerate(raw)]


def _evidence_status(response):
    evidence = response.get("evidence") if isinstance(response.get("evidence"), dict) else {}
    return evidence.get("status")


def _input_identity(response):
    inp = response.get("input") if isinstance(response.get("input"), dict) else {}
    prompt = inp.get("prompt")
    prompt_sha = inp.get("prompt_sha256")
    if _text(prompt):
        prompt_sha = _sha_text(prompt)
    return {
        "question": inp.get("question"),
        "history": inp.get("history"),
        "prompt_sha256": prompt_sha if _sha_hex(prompt_sha) else None,
    }


def _input_sha(response):
    return _digest(_input_identity(response))


def _evidence_sha(response):
    evidence = response.get("evidence") if isinstance(response.get("evidence"), dict) else {}
    rows = [source.identity() for source in _sources(response)]
    rows.sort(
        key=lambda row: (
            str(row.get("source_id") or ""),
            str(row.get("chunk_id") or ""),
            str(row.get("chapter") or ""),
            row.get("text_sha256") or "",
        )
    )
    unique = []
    for row in rows:
        if row not in unique:
            unique.append(row)
    return _digest({"status": evidence.get("status"), "sources": unique})


def _graded_text(response, stage):
    if stage == "model":
        model = response.get("model") if isinstance(response.get("model"), dict) else {}
        value = model.get("raw_body")
        return value if isinstance(value, str) else None
    reader = response.get("reader") if isinstance(response.get("reader"), dict) else {}
    value = reader.get("final_text")
    return value if isinstance(value, str) else None


def _model_fingerprint(response):
    model = response.get("model") if isinstance(response.get("model"), dict) else {}
    explicit = model.get("fingerprint")
    if _text(explicit):
        return explicit.strip()
    tag = model.get("tag")
    digest = model.get("digest")
    if _text(tag) and _text(digest):
        return f"{tag.strip()}@{digest.strip()}"
    if _text(tag):
        return tag.strip()
    if _text(digest):
        return digest.strip()
    return None


def _engine_fingerprint(response):
    reader = response.get("reader") if isinstance(response.get("reader"), dict) else {}
    capture = response.get("capture") if isinstance(response.get("capture"), dict) else {}
    for holder in (reader, capture, response):
        value = holder.get("engine_fingerprint") if isinstance(holder, dict) else None
        if _text(value):
            return value.strip()
    return None


def _validator_review_digest():
    """Seam to the dataset validator's public review_digest, when it lands.

    The response-review binding is intentionally independent: if the public
    function is absent or returns something unusable, this module hashes the
    record itself. The validator is never called to make a response PASS.
    """
    try:
        import dataset_integrity  # noqa: F401
    except Exception:
        return None
    function = getattr(dataset_integrity, "review_digest", None)
    return function if callable(function) else None


def content_digest(record):
    """Hash a golden's content, excluding its review block.

    Uses the dataset validator's public ``review_digest`` when available so a
    data review and this evaluator bind the same reference bytes. A local
    canonical fallback keeps the module usable before that API exists.
    """
    function = _validator_review_digest()
    if function is not None:
        try:
            value = function(record)
        except Exception:
            value = None
        if _sha_hex(value):
            return value
    body = {key: value for key, value in (record or {}).items() if key != "review"}
    return _digest(body)


def _structured_citations(response, stage):
    if stage == "model":
        model = response.get("model") if isinstance(response.get("model"), dict) else {}
        raw = model.get("citations")
    else:
        reader = response.get("reader") if isinstance(response.get("reader"), dict) else {}
        raw = reader.get("citations")
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if isinstance(item, str):
            rows.append({"chapter": None, "chunk_id": item, "quote": None})
        elif isinstance(item, dict):
            rows.append(
                {
                    "chapter": item.get("chapter"),
                    "chunk_id": item.get("chunk_id") or item.get("source_id"),
                    "quote": item.get("quote"),
                }
            )
    return rows


def _parse_tags(text):
    tags = []
    for match in TAG_RE.finditer(text or ""):
        inside = match.group(1)
        cleaned = re.sub(r"chunk_id\s*=\s*", " ", inside, flags=re.IGNORECASE)
        chunk_ids = list(dict.fromkeys(chapter_labels.chunk_tokens(cleaned)))
        for token in chunk_ids:
            cleaned = cleaned.replace(token, " ")
        chapters = []
        for label in chapter_labels.tag_labels(cleaned):
            for key in sorted(chapter_labels.chapter_keys(label)):
                if key not in chapters:
                    chapters.append(key)
        tags.append(
            {
                "start": match.start(),
                "end": match.end(),
                "raw": match.group(0),
                "chapters": chapters,
                "chunk_ids": chunk_ids,
            }
        )
    return tags


def _parse_quotes(text):
    """Every closed quotation, at any length.

    Length is not evidence of attribution: a one-word phrase and a full
    sentence are parsed the same way. Whether a quotation claims book text is
    decided structurally, by the citation that precedes it (see
    ``_attached_tag``), not by how long it is.
    """
    quotes = []
    for match in QUOTE_RE.finditer(text or ""):
        body = match.group(0)[1:-1]
        if not body.strip():
            continue
        quotes.append(
            {
                "start": match.start(),
                "end": match.end(),
                "text": body,
                "raw": match.group(0),
            }
        )
    return quotes


def _unclosed_quote(text):
    """The first opening delimiter left without a partner, if any.

    A tag followed by an unterminated quotation is a claimed quote whose
    boundary is unknown; it is reported, never silently skipped. Closed
    spans are masked first so a stray apostrophe-like mark inside a real
    quote is not mistaken for a new claim.
    """
    source = text or ""
    masked = list(source)
    for match in QUOTE_RE.finditer(source):
        for index in range(match.start(), match.end()):
            masked[index] = " "
    match = QUOTE_OPENER_RE.search("".join(masked))
    if not match:
        return None
    return {
        "start": match.start(),
        "end": len(source),
        "text": source[match.start() + 1 :],
        "raw": source[match.start() :],
    }


def _attribution_gap(text, tag, quotes, start):
    """Text between a tag and a quotation, with intervening quotes masked."""
    source = text or ""
    cursor = tag["end"]
    pieces = []
    for quote in quotes:
        if quote["end"] <= cursor:
            continue
        if quote["start"] >= start:
            break
        pieces.append(source[cursor : quote["start"]])
        cursor = max(cursor, quote["end"])
    pieces.append(source[cursor:start])
    return "".join(pieces)


def _attached_tag(text, tags, quotes, start):
    """The citation tag that directly owns a quotation, if one does.

    Ownership is a run: from the tag's close to the opening delimiter there
    is only separator punctuation and, for a second quote, an earlier quote
    from the same run. Any prose in between means the quotation is not
    directly attributed to the book by that tag.
    """
    preceding = [tag for tag in tags if tag["start"] < start and tag["end"] <= start]
    if not preceding:
        return None
    tag = preceding[-1]
    gap = _attribution_gap(text, tag, quotes, start)
    return tag if ATTACHED_GAP_RE.fullmatch(gap) else None


def _same_line_tag(text, tags, quotes, start):
    """A tag followed by prose and then the quotation, all on one line.

    The quotation is not directly attached, but it sits in an attributed
    sentence, so it cannot be silently treated as ordinary prose either.
    """
    preceding = [tag for tag in tags if tag["start"] < start and tag["end"] <= start]
    if not preceding:
        return None
    tag = preceding[-1]
    gap = _attribution_gap(text, tag, quotes, start)
    if not gap.strip() or "\n" in gap:
        return None
    return tag


def _engine_disclosure(text, quote, stage, provenance):
    """True when a quotation is the engine's own query-disclosure line.

    ``Asked as: "..."`` and ``Read as: "..."`` describe the question the
    engine actually sent; they are not claims about the book. The exemption
    needs both the SYSTEM stage and engine-authored reader text: a raw MODEL
    body can write the same line, and a SYSTEM reader that declares
    ``provenance: "model"`` is model-authored too, so neither is engine
    metadata. Missing provenance gets no exemption; the readiness check
    already reports reader provenance as uncertain. Recognition is
    deliberately narrow: the quotation must be the only one on its line, the
    whole line must be the label plus that quotation, and the line must carry
    no `[Ch. ...]` tag. A label with extra text or a hidden citation is not a
    disclosure, so it cannot mask a book claim.
    """
    if stage != "system" or provenance not in ("engine", "mixed"):
        return False
    source = text or ""
    start = quote.get("start")
    if not isinstance(start, int):
        return False
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", start)
    if line_end == -1:
        line_end = len(source)
    line = source[line_start:line_end]
    if TAG_RE.search(line) or not DISCLOSURE_LINE_RE.fullmatch(line):
        return False
    local = _parse_quotes(line)
    return (
        len(local) == 1
        and line_start + local[0]["start"] == quote["start"]
        and line_start + local[0]["end"] == quote["end"]
    )


def _structured_tag(item):
    """A locator built from one structured citation entry."""
    chapter = item.get("chapter")
    chunk_id = item.get("chunk_id")
    return {
        "raw": f"structured citation {chunk_id or chapter!r}",
        "chapters": [_chapter_key(chapter)] if chapter is not None else [],
        "chunk_ids": [chunk_id] if _text(chunk_id) else [],
    }


def _structured_quote_tag(structured, quote_text):
    """A tag built from an explicit structured citation ``quote`` field."""
    for item in structured:
        value = item.get("quote")
        if _text(value) and _norm_text(value) == _norm_text(quote_text):
            return _structured_tag(item)
    return None


def _citation_identity(response, stage):
    text = _graded_text(response, stage) or ""
    tags = [
        {"chapters": tag["chapters"], "chunk_ids": tag["chunk_ids"]}
        for tag in _parse_tags(text)
    ]
    tags.sort(key=lambda item: (str(item["chapters"]), str(item["chunk_ids"])))
    structured = [
        {
            "chapter": item.get("chapter"),
            "chunk_id": item.get("chunk_id"),
            "quote": item.get("quote"),
        }
        for item in _structured_citations(response, stage)
    ]
    structured.sort(
        key=lambda item: (
            str(item.get("chapter")),
            str(item.get("chunk_id")),
            str(item.get("quote")),
        )
    )
    return {"tags": tags, "structured": structured}


def _citation_sha(response, stage):
    return _digest(_citation_identity(response, stage))


def bindings_for(
    golden,
    response,
    stage,
    *,
    reference_version=EVALUATOR["reference_version"],
    criterion_version=EVALUATOR["criterion_version"],
):
    """The exact content a review must bind to for this response and stage.

    The returned dict can be copied into ``review.bind`` after a reviewer has
    read the captured output. Any later change to the response, its input,
    the shown evidence set, its citations, the golden reference, or either
    version leaves the old review stale.
    """
    return {
        "output_sha256": _sha_text(_graded_text(response, stage) or ""),
        "input_sha256": _input_sha(response),
        "evidence_sha256": _evidence_sha(response),
        "citation_sha256": _citation_sha(response, stage),
        "reference_sha256": content_digest(golden),
        "reference_version": reference_version,
        "criterion_version": criterion_version,
        "model_fingerprint": _model_fingerprint(response),
        "engine_fingerprint": _engine_fingerprint(response),
    }


def _quote_match(quote, text):
    if not isinstance(quote, str) or not isinstance(text, str):
        return "none"
    if quote in text:
        return "exact"
    stripped_quote = FIGURE_RE.sub("", quote)
    stripped_text = FIGURE_RE.sub("", text)
    if stripped_quote != quote and stripped_quote in stripped_text:
        return "figure"
    folded_quote = WS_RE.sub(" ", stripped_quote.casefold()).strip()
    folded_text = WS_RE.sub(" ", stripped_text.casefold()).strip()
    if folded_quote and folded_quote in folded_text:
        return "folded"
    return "none"


def _behavior(text):
    stripped = (text or "").strip()
    if stripped == REFUSAL:
        return "refuse"
    if stripped.startswith(REFUSAL):
        return "refuse_with_commentary"
    if not stripped:
        return "empty"
    return "answer"


def _source_by_witness(sources, witness):
    source_id = witness.get("source_id") if isinstance(witness, dict) else None
    if not _text(source_id):
        return None, "missing"
    matches = [source for source in sources if source.source_id == source_id]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, "ambiguous"
    matches = [source for source in sources if source.chunk_id == source_id]
    if len(matches) == 1:
        return matches[0], "chunk_id"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "absent"


def _source_matches_id(source, value):
    return value is not None and (source.chunk_id == value or source.source_id == value)


def _required_facts(golden):
    expected = golden.get("expected") if isinstance(golden.get("expected"), dict) else {}
    facts = expected.get("required_facts")
    return [fact for fact in facts if isinstance(fact, dict)] if isinstance(facts, list) else []


def _unsupported_claims(golden):
    expected = golden.get("expected") if isinstance(golden.get("expected"), dict) else {}
    claims = expected.get("unsupported_claims")
    if not isinstance(claims, list):
        return []
    rows = []
    for claim in claims:
        if isinstance(claim, str):
            rows.append({"claim": claim})
        elif isinstance(claim, dict) and _text(claim.get("claim")):
            rows.append(claim)
    return rows


def _fact_sources(fact):
    sources = fact.get("source_ids")
    return [source for source in sources if _text(source)] if isinstance(sources, list) else []


def _witness_coverage(golden, sources):
    """How many required facts have at least one witness source actually shown."""
    available = {source.source_id for source in sources if _text(source.source_id)}
    available.update(source.chunk_id for source in sources if _text(source.chunk_id))
    facts = _required_facts(golden)
    if not facts:
        return {"facts": 0, "covered": 0, "all": True}
    covered = 0
    for fact in facts:
        wanted = _fact_sources(fact)
        mode = fact.get("support_mode", "any")
        if not wanted:
            covered += 1
            continue
        hits = [source for source in wanted if source in available]
        if (mode == "all" and len(hits) == len(wanted)) or (mode != "all" and hits):
            covered += 1
    return {"facts": len(facts), "covered": covered, "all": covered == len(facts)}


def _target_kind(golden):
    metadata = golden.get("metadata") if isinstance(golden.get("metadata"), dict) else {}
    for value in (golden.get("target_kind"), metadata.get("target_kind")):
        if value in KINDS:
            return value
    target = golden.get("target") if isinstance(golden.get("target"), dict) else {}
    if target.get("kind") in KINDS:
        return target["kind"]
    expected = golden.get("expected") if isinstance(golden.get("expected"), dict) else {}
    allowed = expected.get("allowed_behaviors") if isinstance(expected.get("allowed_behaviors"), list) else []
    if allowed == ["refuse"]:
        return "refusal"
    if metadata.get("gloss_only") is True:
        return "gloss"
    return "answer"


def _golden_readiness(golden, stage, data_criteria_version):
    findings = []
    notes = []
    if not isinstance(golden, dict):
        return [_review("golden_invalid", "golden record is not an object", "harness", "readiness")], notes
    if golden.get("schema_version") != 1:
        findings.append(_review("golden_invalid", "schema_version must be 1", "harness", "readiness"))
    for name in ("id", "question"):
        if not _text(golden.get(name)):
            findings.append(_review("golden_invalid", f"{name} missing", "harness", "readiness"))
    expected = golden.get("expected")
    if not isinstance(expected, dict):
        findings.append(_review("golden_invalid", "expected must be an object", "harness", "readiness"))
        expected = {}
    allowed = expected.get("allowed_behaviors")
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(value not in BEHAVIORS for value in allowed)
    ):
        findings.append(
            _review("golden_behavior_invalid", f"allowed_behaviors {allowed!r}", "harness", "readiness")
        )
    split = golden.get("split")
    if split not in SPLITS:
        findings.append(_review("golden_split_unknown", f"split {split!r}", "harness", "readiness"))
    task_stage = golden.get("task_stage")
    if task_stage in STAGES and task_stage != stage:
        findings.append(
            _review(
                "golden_stage_mismatch",
                f"golden task_stage {task_stage!r} but grading {stage!r}",
                "harness",
                "readiness",
            )
        )
    refs = golden.get("source_refs")
    if not isinstance(refs, list):
        findings.append(_review("golden_invalid", "source_refs must be a list", "harness", "readiness"))
        refs = []
    ref_ids = {
        ref.get("source_id")
        for ref in refs
        if isinstance(ref, dict) and _text(ref.get("source_id"))
    }
    for fact in _required_facts(golden):
        for source_id in _fact_sources(fact):
            if source_id not in ref_ids:
                findings.append(
                    _review(
                        "golden_fact_source_unknown",
                        f"required fact names {source_id!r}, not in source_refs",
                        "harness",
                        "readiness",
                    )
                )
    review = golden.get("review") if isinstance(golden.get("review"), dict) else {}
    status = review.get("status")
    if not review:
        findings.append(_review("golden_review_missing", "golden has no review block", "harness", "readiness"))
    elif status == "needs_review":
        findings.append(_review("golden_unreviewed", "golden review is pending", "harness", "readiness"))
    elif status == "rejected":
        findings.append(_review("golden_rejected", "golden review was rejected", "harness", "readiness"))
    elif status != "accepted":
        findings.append(_review("golden_review_invalid", f"review status {status!r}", "harness", "readiness"))
    else:
        author = review.get("author")
        reviewer = review.get("reviewer")
        if _text(author) and _text(reviewer) and author.strip().casefold() == reviewer.strip().casefold():
            findings.append(_fail("golden_self_review", "author and reviewer are the same", "harness", "readiness"))
        provenance = review.get("provenance")
        if provenance not in REVIEW_PROVENANCES:
            findings.append(
                _review(
                    "golden_review_provenance",
                    f"review provenance {provenance!r}",
                    "harness",
                    "readiness",
                )
            )
        declared = review.get("content_sha256")
        if not _sha_hex(declared):
            findings.append(
                _review(
                    "golden_review_unbound",
                    "accepted review has no content_sha256",
                    "harness",
                    "readiness",
                )
            )
        elif declared != content_digest(golden):
            findings.append(
                _review(
                    "golden_review_stale_content",
                    "content_sha256 does not match the current golden content",
                    "harness",
                    "readiness",
                )
            )
        criteria = review.get("criteria_version")
        if not _text(criteria):
            findings.append(
                _review(
                    "golden_review_unbound_criteria",
                    "accepted review has no criteria_version",
                    "harness",
                    "readiness",
                )
            )
        elif _text(data_criteria_version) and criteria != data_criteria_version:
            findings.append(
                _review(
                    "golden_review_stale_criteria",
                    f"data criteria {criteria!r} != expected {data_criteria_version!r}",
                    "harness",
                    "readiness",
                )
            )
        else:
            notes.append(f"golden_criteria_declared:{criteria}")
    return findings, notes


def _response_readiness(response, stage):
    findings = []
    notes = []
    if not isinstance(response, dict):
        return [_review("response_invalid", "response record is not an object", "harness", "mechanical")], notes
    if response.get("schema_version") != 1:
        findings.append(_review("response_invalid", "schema_version must be 1", "harness", "mechanical"))
    for name in ("response_id", "golden_id"):
        if not _text(response.get(name)):
            findings.append(_review("response_invalid", f"{name} missing", "harness", "mechanical"))
    capture = response.get("capture")
    if not isinstance(capture, dict):
        findings.append(_review("capture_status_missing", "capture block is missing", "capture", "mechanical"))
        status = None
    else:
        status = capture.get("status")
        if status not in ("ok", "transport_error", "capture_error", "no_call"):
            findings.append(
                _review("capture_status_invalid", f"capture status {status!r}", "capture", "mechanical")
            )
    if status == "transport_error":
        findings.append(_review("unverifiable_transport", "capture reported a transport error", "capture", "mechanical"))
    elif status == "capture_error":
        findings.append(_review("unverifiable_capture", "capture reported a capture error", "capture", "mechanical"))
    input_identity = _input_identity(response)
    if not (
        input_identity.get("question") is not None
        or input_identity.get("history") is not None
        or input_identity.get("prompt_sha256") is not None
    ):
        findings.append(_review("input_unverifiable", "no question, history, or prompt hash captured", "capture", "mechanical"))
    inp = response.get("input") if isinstance(response.get("input"), dict) else {}
    declared_input = inp.get("input_sha256")
    if _sha_hex(declared_input) and declared_input != _input_sha(response):
        findings.append(_review("input_hash_mismatch", "declared input_sha256 does not match", "capture", "mechanical"))
    evidence = response.get("evidence")
    if not isinstance(evidence, dict):
        findings.append(_review("evidence_unverifiable", "no evidence block captured", "capture", "mechanical"))
    else:
        e_status = evidence.get("status")
        if e_status not in ("shown", "prompt_parsed", "guard_no_call", "missing"):
            findings.append(
                _review("evidence_unverifiable", f"evidence status {e_status!r}", "capture", "mechanical")
            )
        elif e_status == "missing":
            findings.append(
                _review(
                    "evidence_unverifiable",
                    "evidence status 'missing'",
                    "capture",
                    "mechanical",
                )
            )
        elif e_status == "guard_no_call":
            notes.append("guard_no_model_call")
        sources = _sources(response)
        for source in sources:
            if not source.has_text:
                findings.append(
                    _review(
                        "evidence_text_missing",
                        f"shown source {source.source_id or source.chunk_id!r} has no text",
                        "capture",
                        "mechanical",
                    )
                )
        declared_evidence = evidence.get("evidence_sha256")
        if _sha_hex(declared_evidence) and declared_evidence != _evidence_sha(response):
            findings.append(
                _review("evidence_hash_mismatch", "declared evidence_sha256 does not match", "capture", "mechanical")
            )
    holder = response.get("model") if stage == "model" else response.get("reader")
    if not isinstance(holder, dict):
        code = "model_output_unavailable" if stage == "model" else "reader_output_unavailable"
        findings.append(_review(code, f"no {stage} output block captured", "capture", "mechanical"))
    else:
        declared_output = holder.get("output_sha256")
        text = _graded_text(response, stage)
        if _sha_hex(declared_output) and declared_output != _sha_text(text or ""):
            findings.append(
                _review("capture_hash_mismatch", f"declared {stage} output_sha256 does not match", "capture", "mechanical")
            )
        if stage == "model":
            if holder.get("provenance") != "model":
                findings.append(
                    _review(
                        "model_output_not_model",
                        f"model provenance is {holder.get('provenance')!r}, not 'model'",
                        "capture",
                        "mechanical",
                    )
                )
        else:
            if holder.get("provenance") not in ("engine", "mixed", "model"):
                findings.append(
                    _review(
                        "reader_provenance_missing",
                        f"reader provenance is {holder.get('provenance')!r}",
                        "capture",
                        "mechanical",
                    )
                )
            if holder.get("code_fallback") is True:
                notes.append("code_fallback_present")
    return findings, notes


def _behavior_findings(golden, response, stage, text, sources, kind, notes):
    findings = []
    expected = golden.get("expected") if isinstance(golden.get("expected"), dict) else {}
    allowed = expected.get("allowed_behaviors") if isinstance(expected.get("allowed_behaviors"), list) else []
    book_answerable = expected.get("book_answerable")
    evidence_sufficient = expected.get("evidence_sufficient")
    behavior = _behavior(text)
    coverage = _witness_coverage(golden, sources)
    outcome = None
    subject = "model" if stage == "model" else "system"

    if behavior == "empty":
        findings.append(_fail("empty_output", f"{stage} output is empty", subject, "mechanical"))
        return findings, behavior, outcome
    if behavior == "refuse_with_commentary":
        if "refuse" in allowed:
            findings.append(
                _fail("refusal_not_exact", f"refusal has commentary after {REFUSAL!r}", subject, "mechanical")
            )
        else:
            findings.append(
                _fail("refusal_line_in_answer", "output starts with the refusal sentence but keeps talking", subject, "mechanical")
            )
        return findings, "answer", outcome

    if behavior == "refuse":
        if "refuse" in allowed:
            if book_answerable is None:
                findings.append(
                    _review("answerability_unknown", "book_answerable is unknown; refusal cannot be called correct", "harness", "mechanical")
                )
            elif book_answerable is True and evidence_sufficient is True:
                findings.append(
                    _review(
                        "golden_refusal_contradiction",
                        "golden allows refusal while the book answerable and the evidence sufficient",
                        "harness",
                        "mechanical",
                    )
                )
            else:
                notes.append("refusal_allowed_by_gold")
                if book_answerable is True and evidence_sufficient is False:
                    if coverage["all"]:
                        findings.append(
                            _review(
                                "golden_evidence_flag_stale",
                                "golden says the evidence is insufficient, but the actual shown evidence covers every required fact",
                                "harness",
                                "mechanical",
                            )
                        )
                    else:
                        outcome = "model_refusal_legitimate_withheld_evidence"
                return findings, behavior, outcome
        if "answer" in allowed or "boundary" in allowed:
            if book_answerable is True and evidence_sufficient is False and stage == "model":
                if coverage["all"]:
                    findings.append(
                        _review(
                            "golden_evidence_flag_stale",
                            "golden says the evidence is insufficient, but the actual shown evidence covers every required fact",
                            "harness",
                            "mechanical",
                        )
                    )
                    return findings, behavior, outcome
                notes.append("model_refusal_legitimate_withheld_evidence")
                outcome = "model_refusal_legitimate_withheld_evidence"
                return findings, behavior, outcome
            if stage == "model" and book_answerable is True and coverage["facts"] and not coverage["covered"]:
                notes.append("model_refusal_legitimate_context_insufficient")
                outcome = "model_refusal_legitimate_insufficient_context"
                return findings, behavior, outcome
            if stage == "model" and book_answerable is True and coverage["facts"] and not coverage["all"]:
                findings.append(
                    _review(
                        "model_refusal_context_partial",
                        f"actual evidence covers {coverage['covered']} of {coverage['facts']} required facts",
                        "engine",
                        "mechanical",
                    )
                )
                return findings, behavior, outcome
            if stage == "system" and book_answerable is True:
                code = "system_retrieval_miss" if not coverage["all"] else "false_refusal_generation"
                subject = "engine" if code == "system_retrieval_miss" else "model"
                findings.append(
                    _fail(
                        code,
                        f"system refused; actual evidence covers {coverage['covered']} of {coverage['facts']} facts",
                        subject,
                        "mechanical",
                    )
                )
                return findings, behavior, outcome
            findings.append(_fail("false_refusal", "output refused an answerable question", subject, "mechanical"))
            return findings, behavior, outcome
        # No behaviour is allowed to satisfy this golden.
        findings.append(_review("golden_behavior_invalid", f"allowed behaviors {allowed!r}", "harness", "mechanical"))
        return findings, behavior, outcome

    # A non-refusal output.
    if "answer" not in allowed and "boundary" not in allowed:
        findings.append(
            _fail("answer_when_refusal_expected", "golden expects a refusal; output answered", subject, "mechanical")
        )
        return findings, behavior, outcome
    if book_answerable is False:
        findings.append(
            _fail("answer_for_unanswerable_item", "golden says the book cannot answer this", subject, "mechanical")
        )
        return findings, behavior, outcome
    if stage == "model" and evidence_sufficient is False:
        if coverage["facts"] and coverage["all"]:
            findings.append(
                _review(
                    "golden_evidence_flag_stale",
                    "golden says evidence is insufficient, but actual shown evidence covers every required fact",
                    "harness",
                    "mechanical",
                )
            )
        else:
            findings.append(
                _fail(
                    "answer_with_insufficient_evidence",
                    "model answered while the golden says the provided evidence is insufficient",
                    subject,
                    "mechanical",
                )
            )
    return findings, behavior, outcome


def _quote_and_citation_findings(golden, response, stage, text, sources, kind, notes):
    findings = []
    subject = "model" if stage == "model" else "engine"
    tags = _parse_tags(text)
    quotes = _parse_quotes(text)
    structured = _structured_citations(response, stage)
    reader = response.get("reader") if isinstance(response.get("reader"), dict) else {}
    reader_provenance = reader.get("provenance")
    # Engine query disclosures describe the question, not the book. They are
    # excluded as claims (and noted) only for engine-authored SYSTEM reader
    # text; they stay in the graded bytes and the review's output binding.
    disclosures = 0
    claims = []
    for quote in quotes:
        if _engine_disclosure(text, quote, stage, reader_provenance):
            disclosures += 1
            continue
        claims.append({**quote, "structured": None})
    if disclosures:
        notes.append(f"engine_disclosure_skipped:{disclosures}")
    # A structured citation may carry the quoted text directly; that field is
    # a book-quote claim even when the graded body does not repeat it.
    for item in structured:
        value = item.get("quote")
        if not _text(value) or any(_norm_text(claim["text"]) == _norm_text(value) for claim in claims):
            continue
        claims.append({"start": None, "end": None, "text": value, "raw": value, "structured": item})

    # Citation presence is required for answer targets. At model stage only
    # the model's own visible tag counts; metadata supplied by the engine is
    # not evidence that the raw model cited anything.
    if kind == "answer":
        visible = bool(tags) if stage == "model" else bool(tags or structured)
        if not visible:
            findings.append(_review("answer_uncited", "answer has no chapter tag or structured citation", subject, "mechanical"))

    structured_by_chapter = {}
    for item in structured:
        chapter = _chapter_key(item.get("chapter"))
        chunk_id = item.get("chunk_id")
        if chapter is not None:
            structured_by_chapter.setdefault(chapter, set())
            if _text(chunk_id):
                structured_by_chapter[chapter].add(chunk_id)

    # A citation is a claim even when no quote follows it. Check its target
    # against the actual shown set before looking at any quoted text.
    for tag in tags:
        if tag["chunk_ids"]:
            for value in tag["chunk_ids"]:
                known = [source for source in sources if _source_matches_id(source, value)]
                if not known:
                    findings.append(
                        _fail("cited_chunk_not_shown", f"cited chunk {value!r} not in shown evidence", subject, "mechanical")
                    )
                elif tag["chapters"] and all(source.chapter_key not in tag["chapters"] for source in known):
                    findings.append(
                        _fail(
                            "citation_chapter_mismatch",
                            f"cited chunk {value!r} is not in chapter {tag['chapters']}",
                            subject,
                            "mechanical",
                        )
                    )
        elif tag["chapters"] and not any(source.chapter_key in tag["chapters"] for source in sources):
            findings.append(
                _fail("cited_chapter_not_shown", f"cited chapter(s) {tag['chapters']} not in shown evidence", subject, "mechanical")
            )
    if stage == "system":
        for item in structured:
            value = item.get("chunk_id")
            if not _text(value):
                continue
            known = [source for source in sources if _source_matches_id(source, value)]
            if not known:
                findings.append(
                    _fail("cited_chunk_not_shown", f"engine cited chunk {value!r} not in shown evidence", "engine", "mechanical")
                )
            elif item.get("chapter") is not None and all(
                source.chapter_key != _chapter_key(item.get("chapter")) for source in known
            ):
                findings.append(
                    _fail(
                        "citation_chapter_mismatch",
                        f"engine cited chunk {value!r} outside chapter {item.get('chapter')!r}",
                        "engine",
                        "mechanical",
                    )
                )

    for quote in claims:
        if quote.get("structured") is not None:
            tag = _structured_tag(quote["structured"])
            notes.append("quote_attached_structured_quote")
        else:
            tag = _attached_tag(text, tags, quotes, quote["start"])
            if tag is None:
                tag = _structured_quote_tag(structured, quote["text"])
                if tag is not None:
                    notes.append("quote_attached_structured_quote")
        engine_narrowed = None
        # A single engine citation does not own every untagged quotation:
        # that turned question disclosures and scare quotes into invented
        # book quotes. Only a tag run or an explicit structured citation
        # quote attributes a quotation.
        if tag is None:
            # No citation owns this quotation. If it is verbatim book text it
            # is an uncited book quote (REVIEW: the attribution is missing).
            # Anything else is ordinary prose quotation (a scare quote), not
            # a claim about the book; the semantic review still decides.
            levels = [_quote_match(quote["text"], source.text) for source in sources]
            if any(level in ("exact", "figure", "folded") for level in levels):
                if kind == "gloss":
                    notes.append("quote_untagged_gloss")
                else:
                    findings.append(
                        _review(
                            "quote_untagged",
                            "quote has no preceding [Ch. N] tag or structured citation quote",
                            subject,
                            "mechanical",
                        )
                    )
            elif _same_line_tag(text, tags, quotes, quote["start"]) is not None:
                findings.append(
                    _review(
                        "quote_attribution_ambiguous",
                        "quotation follows a citation tag on the same line but is not directly attached",
                        subject,
                        "mechanical",
                    )
                )
            else:
                notes.append("quotation_unattributed")
            continue

        candidate_ids = set(tag.get("chunk_ids") or [])
        chapters = [chapter for chapter in tag.get("chapters") or [] if chapter is not None]
        candidates = []
        if candidate_ids:
            candidates = [
                source
                for source in sources
                if any(_source_matches_id(source, value) for value in candidate_ids)
            ]
            missing = {
                value
                for value in candidate_ids
                if not any(_source_matches_id(source, value) for source in sources)
            }
            if missing:
                findings.append(
                    _fail("cited_chunk_not_shown", f"cited chunk(s) {sorted(missing)} not in shown evidence", subject, "mechanical")
                )
                continue
            if chapters:
                for source in candidates:
                    if source.chapter_key not in chapters:
                        findings.append(
                            _fail(
                                "citation_chapter_mismatch",
                                f"cited chunk {source.chunk_id!r} is chapter {source.chapter!r}, tag says {chapters}",
                                subject,
                                "mechanical",
                            )
                        )
                        break
        elif chapters:
            candidates = [source for source in sources if source.chapter_key in chapters]
            if not candidates:
                findings.append(
                    _fail("cited_chapter_not_shown", f"cited chapter(s) {chapters} not in shown evidence", subject, "mechanical")
                )
                continue
            if len(candidates) > 1:
                notes.append("chapter_only_ambiguous")
            if stage == "system":
                for chapter in chapters:
                    engine_chunks = structured_by_chapter.get(chapter, set())
                    if len(engine_chunks) == 1:
                        chosen = next(iter(engine_chunks))
                        narrowed = [source for source in candidates if _source_matches_id(source, chosen)]
                        if narrowed:
                            candidates = narrowed
                            engine_narrowed = chosen
                            notes.append(f"engine_chunk_narrowed:{chosen}")
                        break
                    if len(engine_chunks) > 1:
                        notes.append("engine_chunk_ambiguous")
        else:
            candidates = list(sources)

        if not candidates:
            findings.append(_review("evidence_unverifiable", "no shown source can carry the quote", "capture", "mechanical"))
            continue
        levels = [_quote_match(quote["text"], source.text) for source in candidates]
        if any(level in ("exact", "figure") for level in levels):
            if any(level == "figure" for level in levels):
                notes.append("figure_reference_folded")
            if len([source for source in candidates if _quote_match(quote["text"], source.text) in ("exact", "figure")]) > 1:
                notes.append("quote_matches_multiple_shown_sources")
            continue
        elsewhere = [
            source
            for source in sources
            if source not in candidates
            and _quote_match(quote["text"], source.text) in ("exact", "figure")
        ]
        if (candidate_ids or engine_narrowed) and elsewhere:
            findings.append(
                _fail(
                    "quote_not_in_cited_chunk",
                    f"quote is verbatim in {[source.chunk_id for source in elsewhere]}, not in the cited chunk",
                    subject,
                    "mechanical",
                )
            )
            continue
        if any(level == "folded" for level in levels):
            findings.append(
                _review(
                    "quote_folded_only",
                    "quote matches a cited passage only after case/whitespace folding",
                    subject,
                    "mechanical",
                )
            )
            continue
        if elsewhere:
            code = "quote_not_in_cited_chunk" if candidate_ids else "quote_outside_cited_chapter"
            findings.append(
                _fail(
                    code,
                    f"quote is verbatim in {[source.chunk_id for source in elsewhere]}, not in the cited source",
                    subject,
                    "mechanical",
                )
            )
        else:
            findings.append(
                _fail(
                    "quote_not_in_shown_evidence",
                    f"quote not found in the cited shown passage: {quote['text'][:80]!r}",
                    subject,
                    "mechanical",
                )
            )

    unclosed = _unclosed_quote(text)
    if unclosed is not None:
        tag = _attached_tag(text, tags, quotes, unclosed["start"])
        if tag is None:
            tag = _same_line_tag(text, tags, quotes, unclosed["start"])
        if tag is not None:
            findings.append(
                _review(
                    "quote_unclosed",
                    f"quotation after {tag['raw']} has no closing delimiter",
                    subject,
                    "mechanical",
                )
            )
        else:
            notes.append("unclosed_quotation_unattributed")

    if kind == "refusal":
        has_quote = bool(quotes)
        if has_quote:
            findings.append(
                _fail("refusal_with_quote", "a refusal target must not carry a quoted passage", subject, "mechanical")
            )
    return findings


def _answer_shape_findings(golden, text, kind, notes, subject):
    findings = []
    if kind not in ("answer", "gloss"):
        return findings
    question = golden.get("question") or ""
    plain = TAG_RE.sub(" ", text)
    plain = re.sub(r'"[^"]*"|“[^”]*”', " ", plain)
    if _norm_text(text) == _norm_text(question) or _norm_text(plain) == _norm_text(question):
        findings.append(_fail("echo_not_an_answer", "output repeats the question", subject, "mechanical"))
        return findings
    if not re.search(r"[^\W_]", plain, re.UNICODE):
        findings.append(
            _fail("quote_only_no_explanation", f"{kind} output is only a quote and citations", subject, "mechanical")
        )
    return findings


def _review_fact_entry(review, fact, index):
    entries = []
    for item in review.get("facts") or []:
        if not isinstance(item, dict):
            continue
        if item.get("fact_index") == index:
            entries.append(item)
        elif _norm_claim(item.get("claim")) == _norm_claim(fact.get("claim")):
            entries.append(item)
    return entries


def _validate_witness(witness, sources, notes):
    if not isinstance(witness, dict):
        return [_fail("review_fact_unwitnessed", "supported fact has no witness", "review", "semantic")]
    quote = witness.get("quote")
    if not _text(quote):
        return [_fail("review_fact_unwitnessed", "supported fact has no witness quote", "review", "semantic")]
    source, how = _source_by_witness(sources, witness)
    if source is None:
        if how == "ambiguous":
            return [_review("review_witness_source_ambiguous", "witness source id matches several shown sources", "review", "semantic")]
        return [
            _fail(
                "review_witness_source_not_shown",
                f"witness source {witness.get('source_id')!r} is not in the actual shown evidence",
                "review",
                "semantic",
            )
        ]
    if how == "chunk_id":
        notes.append("witness_matched_by_chunk_id")
    level = _quote_match(quote, source.text)
    if level in ("exact", "figure"):
        if level == "figure":
            notes.append("witness_figure_reference_folded")
        return []
    if level == "folded":
        return [
            _review(
                "review_witness_quote_folded_only",
                "witness quote matches only after case/whitespace folding",
                "review",
                "semantic",
            )
        ]
    return [
        _fail(
            "review_witness_quote_invalid",
            f"witness quote is not verbatim in {source.chunk_id or source.source_id!r}",
            "review",
            "semantic",
        )
    ]


def _review_semantics(golden, response, stage, review, bindings, notes, kind):
    findings = []
    if not isinstance(review, dict):
        return [_review("review_invalid", "review is not an object", "review", "semantic")], None
    ambiguity = review.get("ambiguity") if _text(review.get("ambiguity")) else None
    target_error = False
    if review.get("stage") != stage:
        findings.append(_review("review_stage_mismatch", f"review stage {review.get('stage')!r} != {stage!r}", "review", "semantic"))
        target_error = True
    if review.get("golden_id") != golden.get("id"):
        findings.append(_review("review_wrong_golden", "review names a different golden", "review", "semantic"))
        target_error = True
    if target_error:
        return findings, ambiguity
    if not _text(review.get("review_id")):
        findings.append(_review("review_invalid", "review_id missing", "review", "semantic"))
    if not _text(review.get("rationale")):
        findings.append(_review("review_unattributed", "review has no rationale", "review", "semantic"))
    if not _text(review.get("reviewer")):
        findings.append(_review("review_unattributed", "review has no reviewer", "review", "semantic"))
    provenance = review.get("provenance")
    if provenance not in REVIEW_PROVENANCES:
        findings.append(
            _review("review_provenance_missing", f"review provenance {provenance!r}", "review", "semantic")
        )
    author = review.get("author")
    if _text(author) and _text(review.get("reviewer")) and author.strip().casefold() == review["reviewer"].strip().casefold():
        findings.append(_fail("review_self_signed", "reviewer and author are the same", "review", "semantic"))
    verdict = review.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        findings.append(_review("review_verdict_invalid", f"verdict {verdict!r}", "review", "semantic"))
        return findings, ambiguity

    bind = review.get("bind")
    if not isinstance(bind, dict):
        findings.append(_review("review_binding_missing", "review has no bind block", "review", "semantic"))
        return findings, ambiguity
    required = (
        "output_sha256",
        "input_sha256",
        "evidence_sha256",
        "citation_sha256",
        "reference_sha256",
        "reference_version",
        "criterion_version",
    )
    missing = [name for name in required if not bind.get(name)]
    if missing:
        findings.append(_review("review_binding_missing", f"bind is missing {missing}", "review", "semantic"))
        return findings, ambiguity
    stale = []
    for name, code in (
        ("output_sha256", "review_stale_output"),
        ("input_sha256", "review_stale_input"),
        ("evidence_sha256", "review_stale_evidence"),
        ("citation_sha256", "review_stale_citation"),
        ("reference_sha256", "review_stale_reference"),
    ):
        if bind.get(name) != bindings.get(name):
            stale.append(code)
    if bind.get("reference_version") != bindings.get("reference_version"):
        stale.append("review_stale_reference")
    if bind.get("criterion_version") != bindings.get("criterion_version"):
        stale.append("review_stale_criterion")
    for name, code in (
        ("model_fingerprint", "review_stale_model"),
        ("engine_fingerprint", "review_stale_engine"),
    ):
        computed = bindings.get(name)
        bound = bind.get(name)
        if computed and not bound:
            stale.append(code.replace("stale", "binding_missing"))
        elif computed and bound != computed:
            stale.append(code)
        elif not computed and bound:
            stale.append(code)
    if stale:
        for code in stale:
            findings.append(_review(code, "review binds different bytes than this response", "review", "semantic"))
        return findings, ambiguity

    behavior = review.get("behavior")
    expected = golden.get("expected") if isinstance(golden.get("expected"), dict) else {}
    allowed = expected.get("allowed_behaviors") if isinstance(expected.get("allowed_behaviors"), list) else []
    mechanical_behavior = _behavior(_graded_text(response, stage))
    if behavior is not None:
        if behavior not in BEHAVIORS or behavior not in allowed:
            findings.append(
                _fail("review_behavior_not_allowed", f"review behavior {behavior!r} not allowed {allowed!r}", "review", "semantic")
            )
        elif behavior == "refuse" and mechanical_behavior != "refuse":
            findings.append(
                _fail("review_behavior_contradiction", "review says refusal; output did not refuse", "review", "semantic")
            )
        elif behavior == "answer" and mechanical_behavior == "refuse":
            findings.append(
                _fail("review_behavior_contradiction", "review says answer; output refused", "review", "semantic")
            )
        elif behavior == "boundary" and mechanical_behavior == "refuse":
            findings.append(
                _fail("review_behavior_contradiction", "review says boundary; output refused", "review", "semantic")
            )

    if verdict == "fail":
        findings.append(_fail("review_failed", review.get("rationale") or "reviewer failed this output", "review", "semantic"))
        return findings, ambiguity

    facts = _required_facts(golden)
    sources = _sources(response)
    for index, fact in enumerate(facts):
        entries = _review_fact_entry(review, fact, index)
        if not entries:
            code = "review_missing_fact"
            detail = f"required fact {index} has no review entry"
            findings.append(_fail(code, detail, "review", "semantic") if verdict == "pass" else _review(code, detail, "review", "semantic"))
            continue
        statuses = [entry.get("status") for entry in entries]
        if statuses.count("contradicted"):
            findings.append(_fail("review_fact_contradicted", f"fact {index} contradicted", "review", "semantic"))
            continue
        if statuses.count("uncertain"):
            findings.append(_review("review_fact_uncertain", f"fact {index} is uncertain", "review", "semantic"))
            ambiguity = ambiguity or f"fact {index} uncertain"
            continue
        if statuses.count("not_addressed"):
            findings.append(_fail("review_fact_not_addressed", f"fact {index} not addressed", "review", "semantic"))
            continue
        supported = [entry for entry in entries if entry.get("status") == "supported"]
        if not supported:
            findings.append(_review("review_fact_status_invalid", f"fact {index} status {statuses!r}", "review", "semantic"))
            continue
        mode = fact.get("support_mode", "any")
        wanted = _fact_sources(fact)
        if mode == "all":
            for source_id in wanted:
                matching = [
                    entry
                    for entry in supported
                    if isinstance(entry.get("witness"), dict)
                    and entry["witness"].get("source_id") == source_id
                ]
                if not matching:
                    shown = any(
                        source.source_id == source_id or source.chunk_id == source_id
                        for source in sources
                    )
                    if shown:
                        findings.append(
                            _fail(
                                "review_fact_unwitnessed",
                                f"fact {index} needs a witness for {source_id!r}",
                                "review",
                                "semantic",
                            )
                        )
                    else:
                        findings.append(
                            _review(
                                "review_fact_evidence_unavailable",
                                f"fact {index} witness {source_id!r} is not in actual shown evidence",
                                "capture",
                                "semantic",
                            )
                        )
            for entry in supported:
                findings.extend(_validate_witness(entry.get("witness"), sources, notes))
        else:
            trials = []
            for entry in supported:
                trial_notes = []
                trial = _validate_witness(entry.get("witness"), sources, trial_notes)
                trials.append((trial, entry, trial_notes))
            valid = [trial for trial in trials if not trial[0]]
            if valid:
                notes.extend(valid[0][2])
                witness = valid[0][1].get("witness") if isinstance(valid[0][1].get("witness"), dict) else {}
                if wanted and witness.get("source_id") not in wanted:
                    notes.append("alternative_witness")
            else:
                for trial, _, trial_notes in trials:
                    findings.extend(trial)
                    notes.extend(trial_notes)
    for index, claim in enumerate(_unsupported_claims(golden)):
        entries = []
        for item in review.get("unsupported_claims") or []:
            if not isinstance(item, dict):
                continue
            if item.get("claim_index") == index:
                entries.append(item)
            elif _norm_claim(item.get("claim")) == _norm_claim(claim.get("claim")):
                entries.append(item)
        if not entries:
            code = "review_unsupported_claim_missing"
            detail = f"unsupported claim {index} has no review entry"
            findings.append(_fail(code, detail, "review", "semantic") if verdict == "pass" else _review(code, detail, "review", "semantic"))
            continue
        statuses = [entry.get("present") for entry in entries]
        if True in statuses:
            findings.append(_fail("review_unsupported_claim_asserted", f"unsupported claim {index} is present", "review", "semantic"))
        elif "uncertain" in statuses:
            findings.append(_review("review_unsupported_claim_uncertain", f"unsupported claim {index} uncertain", "review", "semantic"))
            ambiguity = ambiguity or f"unsupported claim {index} uncertain"
        elif False not in statuses:
            findings.append(_review("review_unsupported_claim_invalid", f"unsupported claim {index} status {statuses!r}", "review", "semantic"))

    if kind in ("answer", "gloss"):
        utility = review.get("utility")
        if not isinstance(utility, dict):
            findings.append(_review("review_utility_missing", "answer/gloss review has no utility judgement", "review", "semantic"))
        else:
            value = utility.get("answers_question")
            if value is True:
                pass
            elif value is False:
                findings.append(_fail("review_utility_failed", "review says the output does not answer the question", "review", "semantic"))
            elif value == "uncertain":
                findings.append(_review("review_utility_uncertain", "review is unsure the output answers the question", "review", "semantic"))
                ambiguity = ambiguity or "utility uncertain"
            else:
                findings.append(_review("review_utility_missing", f"utility value {value!r}", "review", "semantic"))
    if ambiguity:
        findings.append(_review("review_ambiguity", ambiguity, "review", "semantic"))
    if verdict == "pass" and not any(f["verdict"] != "PASS" for f in findings):
        return findings, ambiguity
    if verdict == "review":
        findings.append(_review("review_pending", "reviewer asked for another look", "review", "semantic"))
    return findings, ambiguity


def _evaluate_one(golden, response, stage, reviews, versions, notes=None):
    notes = list(notes or [])
    findings_readiness = []
    findings_mechanical = []
    findings_semantic = []
    ambiguity = None
    outcome_class = None
    review_block = None
    kind = "answer"
    behavior = None
    text = None
    sources = []
    evidence_status = None
    capture_status = None
    semantic_not_required = False

    if not isinstance(golden, dict) or not isinstance(response, dict):
        code = "golden_invalid" if not isinstance(golden, dict) else "response_invalid"
        finding = _review(code, f"{code} record cannot be graded", "harness", "readiness")
        findings_readiness.append(finding)
        all_findings = [finding]
        return {
            "golden_id": golden.get("id") if isinstance(golden, dict) else None,
            "response_id": response.get("response_id") if isinstance(response, dict) else None,
            "stage": stage,
            "kind": kind,
            "behavior": None,
            "status": "REVIEW",
            "mechanical": {"status": "REVIEW", "causes": []},
            "semantic": {"status": "REVIEW", "causes": []},
            "readiness": {"status": "REVIEW", "causes": [code]},
            "causes": [code],
            "cause": code,
            "subject": "harness",
            "outcome_class": code,
            "notes": [],
            "ambiguity": None,
            "binding": None,
            "review": {"binding_status": "not_considered"},
            "findings": all_findings,
        }

    readiness, readiness_notes = _golden_readiness(golden, stage, versions.get("data_criteria_version"))
    mechanical, capture_notes = _response_readiness(response, stage)
    notes.extend(readiness_notes)
    notes.extend(capture_notes)
    findings_readiness = list(readiness)
    findings_mechanical = list(mechanical)
    readiness_ambiguity = None
    if any(
        finding["code"]
        in (
            "golden_unreviewed",
            "golden_rejected",
            "golden_review_unbound",
            "golden_review_unbound_criteria",
            "golden_review_stale_content",
        )
        for finding in findings_readiness
    ):
        review_golden = golden.get("review") if isinstance(golden.get("review"), dict) else {}
        readiness_ambiguity = (
            review_golden.get("notes")
            if _text(review_golden.get("notes"))
            else "golden reference is not certified"
        )

    kind = _target_kind(golden)
    text = _graded_text(response, stage)
    sources = _sources(response)
    evidence_status = _evidence_status(response)
    capture = response.get("capture") if isinstance(response.get("capture"), dict) else {}
    capture_status = capture.get("status")
    expected = golden.get("expected") if isinstance(golden.get("expected"), dict) else {}
    allowed = expected.get("allowed_behaviors") if isinstance(expected.get("allowed_behaviors"), list) else []
    semantic_checked = False

    # A capture that never produced bytes cannot be called a model failure.
    if capture_status in ("transport_error", "capture_error"):
        text = None
    if capture_status == "no_call" and evidence_status != "guard_no_call":
        findings_mechanical.append(
            _review("unverifiable_no_call", "capture recorded no model call and no guard explanation", "capture", "mechanical")
        )
        text = None
    guard = capture_status == "no_call" or evidence_status == "guard_no_call"
    if guard:
        notes.append("guard_no_model_call")
    guard_no_call_answer = False
    if guard and text is not None and _behavior(text) not in ("refuse", "refuse_with_commentary"):
        findings_mechanical.append(
            _review(
                "guard_no_model_call_answer",
                "the capture says no model call, but a non-refusal answer is present",
                "capture",
                "mechanical",
            )
        )
        guard_no_call_answer = True
    verifiable = (
        text is not None
        and capture_status not in ("transport_error", "capture_error")
        and evidence_status != "missing"
    )

    guard_false_refusal = False
    if text is not None and guard and _behavior(text) == "refuse" and "refuse" not in allowed:
        if expected.get("book_answerable") is not False:
            findings_mechanical.append(
                _fail(
                    "guard_false_refusal",
                    "the pre-LLM guard refused an answerable question; this is an engine decision, not model output",
                    "engine",
                    "mechanical",
                )
            )
            guard_false_refusal = True

    if text is not None and not guard_false_refusal and not guard_no_call_answer:
        behavior_findings, behavior, outcome = _behavior_findings(
            golden, response, stage, text, sources, kind, notes
        )
        findings_mechanical.extend(behavior_findings)
        if outcome:
            outcome_class = outcome
        # A quote/citation check applies to an answer, not to a refusal and
        # not when the evidence text itself is unavailable. Missing evidence
        # is REVIEW, not a fabricated-quote FAIL against the model.
        if verifiable and _behavior(text) not in ("empty", "refuse", "refuse_with_commentary"):
            findings_mechanical.extend(
                _answer_shape_findings(golden, text, kind, notes, "model" if stage == "model" else "system")
            )
            findings_mechanical.extend(
                _quote_and_citation_findings(golden, response, stage, text, sources, kind, notes)
            )
    behavior = _behavior(text) if text is not None else None

    model = response.get("model") if isinstance(response.get("model"), dict) else {}
    done_reason = model.get("done_reason")
    if verifiable and not guard_no_call_answer and done_reason == "length":
        findings_mechanical.append(
            _fail(
                "output_truncated_length_stop",
                "generation hit the token cap; this is a real output failure, not an excluded run",
                "model",
                "mechanical",
            )
        )
    elif verifiable and not guard_no_call_answer and done_reason not in (None, "", "stop"):
        findings_mechanical.append(
            _review("done_reason_unexpected", f"done_reason {done_reason!r}", "capture", "mechanical")
        )

    # Semantic review lookup. An unverifiable capture is never turned into a
    # model failure by a review that could not see the same bytes.
    key = (response.get("response_id"), stage)
    supplied = reviews.get(key) if isinstance(reviews, dict) else None
    if supplied:
        review = supplied[0]
        review_block = {
            "review_id": review.get("review_id") if isinstance(review, dict) else None,
            "provenance": review.get("provenance") if isinstance(review, dict) else None,
            "verdict": review.get("verdict") if isinstance(review, dict) else None,
            "reviewer": review.get("reviewer") if isinstance(review, dict) else None,
            "binding_status": "checked",
        }
        if len(supplied) > 1:
            review_block["binding_status"] = "ambiguous"
            findings_semantic.append(
                _review("review_duplicate", f"{len(supplied)} reviews for one output/stage", "review", "semantic")
            )
        elif not verifiable:
            review_block["binding_status"] = "unverifiable"
            findings_semantic.append(
                _review("review_unverifiable", "capture bytes/evidence are not verifiable; review not applied", "review", "semantic")
            )
        else:
            bindings = bindings_for(
                golden,
                response,
                stage,
                reference_version=versions["reference_version"],
                criterion_version=versions["criterion_version"],
            )
            sem, ambiguity = _review_semantics(golden, response, stage, review, bindings, notes, kind)
            semantic_checked = True
            findings_semantic.extend(sem)
            if any(
                finding["code"].startswith("review_stale") or finding["code"].startswith("review_binding")
                for finding in sem
            ):
                review_block["binding_status"] = "stale"
    else:
        if not verifiable:
            findings_semantic.append(
                _review(
                    "review_unverifiable",
                    "capture bytes/evidence are not verifiable; no review can be applied",
                    "review",
                    "semantic",
                )
            )
        elif kind in ("answer", "gloss") and outcome_class in (
            "model_refusal_legitimate_insufficient_context",
            "model_refusal_legitimate_withheld_evidence",
        ):
            semantic_not_required = True
            review_block = {
                "binding_status": "not_required",
                "reason": "legitimate refusal with insufficient or withheld context",
            }
        elif kind in ("answer", "gloss"):
            findings_semantic.append(
                _review("review_missing", "answer/gloss needs a bound source-backed review", "review", "semantic")
            )
        else:
            semantic_not_required = True
            review_block = {"binding_status": "not_required", "reason": "refusal uses golden readiness"}

    all_findings = findings_readiness + findings_mechanical + findings_semantic
    mechanical_status = _verdict(findings_mechanical)
    semantic_status = _verdict(findings_semantic)
    if not findings_semantic:
        if semantic_checked:
            semantic_status = "PASS"
        elif semantic_not_required:
            semantic_status = "NOT_REQUIRED"
        else:
            semantic_status = "REVIEW"
    readiness_status = _verdict(findings_readiness)
    statuses = [mechanical_status, readiness_status]
    if semantic_status not in ("NOT_REQUIRED", "NOT_APPLICABLE"):
        statuses.append(semantic_status)
    status = max(statuses, key=RANK.get) if statuses else "PASS"
    non_pass = [finding for finding in all_findings if finding["verdict"] != "PASS"]
    primary = non_pass[0] if non_pass else None
    if status == "PASS":
        if outcome_class:
            pass
        elif kind == "refusal":
            outcome_class = "reviewed_refusal_pass" if semantic_status == "PASS" else "mechanical_refusal_pass"
        else:
            outcome_class = "reviewed_pass"
    else:
        outcome_class = primary["code"] if primary else status

    return {
        "golden_id": golden.get("id"),
        "response_id": response.get("response_id"),
        "stage": stage,
        "kind": kind,
        "behavior": behavior,
        "status": status,
        "mechanical": {"status": mechanical_status, "causes": _codes(findings_mechanical)},
        "semantic": {"status": semantic_status, "causes": _codes(findings_semantic)},
        "readiness": {"status": readiness_status, "causes": _codes(findings_readiness)},
        "causes": _codes(all_findings),
        "cause": primary["code"] if primary else "pass",
        "subject": primary["subject"] if primary else ("model" if stage == "model" else "system"),
        "outcome_class": outcome_class,
        "notes": list(dict.fromkeys(notes)),
        "ambiguity": ambiguity or readiness_ambiguity,
        "binding": bindings_for(
            golden,
            response,
            stage,
            reference_version=versions["reference_version"],
            criterion_version=versions["criterion_version"],
        ),
        "review": review_block,
        "findings": all_findings,
    }


def _worst(statuses):
    worst = "PASS"
    for status in statuses:
        if status in RANK and RANK[status] > RANK[worst]:
            worst = status
    return worst


def _empty_report(versions):
    return {
        "evaluator": {**EVALUATOR, "criterion_version": versions["criterion_version"], "reference_version": versions["reference_version"]},
        "verdict": "PASS",
        "valid": None,
        "counts": {},
        "records": [],
        "findings": [],
        "controls": {"valid": None, "controls": {}},
        "data_readiness": None,
    }


def _read_rows(path):
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if not resolved.is_file():
        return None, str(resolved), None, f"file not readable: {resolved}"
    raw_bytes = resolved.read_bytes()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    text = raw_bytes.decode("utf-8", "replace")
    stripped = text.strip()
    if not stripped:
        return [], str(resolved), sha, None
    try:
        parsed = json.loads(stripped)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        return parsed, str(resolved), sha, None
    if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
        return parsed["records"], str(resolved), sha, None
    if isinstance(parsed, dict):
        return [parsed], str(resolved), sha, None
    rows = []
    for line, raw_line in enumerate(text.splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            rows.append(json.loads(raw_line))
        except ValueError as exc:
            rows.append({"__unreadable__": str(exc), "__line__": line, "__path__": str(resolved)})
    return rows, str(resolved), sha, None


def _index_reviews(reviews):
    table = {}
    duplicates = set()
    unreadable = []
    for row in reviews:
        if isinstance(row, dict) and "__unreadable__" in row:
            unreadable.append(row)
            continue
        if not isinstance(row, dict):
            unreadable.append({"__unreadable__": "review is not an object"})
            continue
        key = (row.get("response_id"), row.get("stage"))
        table.setdefault(key, []).append(row)
        if len(table[key]) > 1:
            duplicates.add(key)
    return table, duplicates, unreadable


def _evaluate_core(goldens, responses, reviews, *, stage, versions, split):
    rows = goldens if isinstance(goldens, list) else [goldens]
    responses = responses if isinstance(responses, list) else [responses]
    review_rows = list(reviews or [])
    notes = []
    findings = []
    records = []

    if stage not in STAGES + ("both",):
        return {
            **_empty_report(versions),
            "verdict": "FAIL",
            "findings": [_fail("stage_invalid", f"stage {stage!r}", "harness", "data")],
        }
    stages = STAGES if stage == "both" else (stage,)

    selected = []
    excluded = []
    invalid_goldens = 0
    for golden in rows:
        if not isinstance(golden, dict) or "__unreadable__" in golden:
            invalid_goldens += 1
            code = "golden_unreadable" if isinstance(golden, dict) else "golden_invalid"
            detail = (
                f"unreadable golden row: {golden.get('__unreadable__')}"
                if isinstance(golden, dict)
                else "golden row is not an object"
            )
            for one_stage in stages:
                records.append(
                    {
                        "golden_id": golden.get("id") if isinstance(golden, dict) else None,
                        "response_id": None,
                        "stage": one_stage,
                        "kind": "unknown",
                        "behavior": None,
                        "status": "REVIEW",
                        "mechanical": {"status": "REVIEW", "causes": [code]},
                        "semantic": {"status": "REVIEW", "causes": [code]},
                        "readiness": {"status": "REVIEW", "causes": [code]},
                        "causes": [code],
                        "cause": code,
                        "subject": "harness",
                        "outcome_class": code,
                        "notes": [],
                        "ambiguity": None,
                        "binding": None,
                        "review": {"binding_status": "not_considered"},
                        "findings": [_review(code, detail, "harness", "readiness")],
                    }
                )
            continue
        split_value = golden.get("split")
        if split == "all" or split_value in split:
            selected.append(golden)
        else:
            excluded.append(
                {
                    "id": golden.get("id"),
                    "split": split_value,
                    "reason": "split_not_selected",
                }
            )
    if not rows:
        findings.append(_review("dataset_empty", "no golden rows", "harness", "data"))
    if split != "all":
        for golden in rows:
            if (
                isinstance(golden, dict)
                and "__unreadable__" not in golden
                and golden.get("split") not in SPLITS
            ):
                findings.append(
                    _review(
                        "golden_split_unknown",
                        f"golden {golden.get('id')!r} split {golden.get('split')!r}",
                        "harness",
                        "readiness",
                    )
                )

    valid_responses = []
    for position, response in enumerate(responses):
        if isinstance(response, dict) and "__unreadable__" not in response:
            valid_responses.append(response)
            continue
        code = "response_unreadable" if isinstance(response, dict) else "response_invalid"
        detail = (
            f"unreadable response row: {response.get('__unreadable__')}"
            if isinstance(response, dict)
            else "response row is not an object"
        )
        for one_stage in stages:
            records.append(
                {
                    "golden_id": response.get("golden_id") if isinstance(response, dict) else None,
                    "response_id": (
                        response.get("response_id") if isinstance(response, dict) else None
                    )
                    or f"<row:{position + 1}>",
                    "stage": one_stage,
                    "kind": "unknown",
                    "behavior": None,
                    "status": "REVIEW",
                    "mechanical": {"status": "REVIEW", "causes": [code]},
                    "semantic": {"status": "REVIEW", "causes": [code]},
                    "readiness": {"status": "REVIEW", "causes": [code]},
                    "causes": [code],
                    "cause": code,
                    "subject": "harness",
                    "outcome_class": code,
                    "notes": [],
                    "ambiguity": None,
                    "binding": None,
                    "review": {"binding_status": "not_considered"},
                    "findings": [_review(code, detail, "harness", "mechanical")],
                }
            )
    responses = valid_responses

    golden_ids = {}
    duplicate_goldens = set()
    for golden in selected:
        if isinstance(golden, dict) and _text(golden.get("id")):
            golden_ids.setdefault(golden["id"], []).append(golden)
            if len(golden_ids[golden["id"]]) > 1:
                duplicate_goldens.add(golden["id"])
    for golden_id in duplicate_goldens:
        findings.append(_fail("golden_duplicate_id", f"golden id {golden_id!r} appears more than once", "harness", "readiness"))

    response_ids = {}
    for response in responses:
        if isinstance(response, dict) and _text(response.get("response_id")):
            response_ids.setdefault(response["response_id"], []).append(response)
    for response_id, group in response_ids.items():
        if len(group) > 1:
            findings.append(_fail("response_duplicate_id", f"response id {response_id!r} appears more than once", "harness", "mechanical"))

    review_table, duplicate_reviews, unreadable_reviews = _index_reviews(review_rows)
    for row in unreadable_reviews:
        findings.append(_review("review_unreadable", f"review row unreadable: {row.get('__unreadable__')}", "harness", "semantic"))
    matched_review_keys = set()

    by_golden = {}
    for response in responses:
        if not isinstance(response, dict):
            continue
        by_golden.setdefault(response.get("golden_id"), []).append(response)

    # A response whose golden is not in scope is still visible and still in N.
    for response in responses:
        if not isinstance(response, dict):
            continue
        golden_id = response.get("golden_id")
        target = golden_ids.get(golden_id)
        if target:
            continue
        for one_stage in stages:
            key = (response.get("response_id"), one_stage)
            supplied = review_table.get(key)
            record = {
                "golden_id": golden_id,
                "response_id": response.get("response_id"),
                "stage": one_stage,
                "kind": "unknown",
                "status": "REVIEW",
                "mechanical": {"status": "REVIEW", "causes": ["golden_unknown"]},
                "semantic": {"status": "REVIEW", "causes": ["review_orphan"] if supplied else ["review_missing"]},
                "readiness": {"status": "REVIEW", "causes": ["response_requires_golden"]},
                "causes": ["golden_unknown"] + (["review_orphan"] if supplied else []),
                "cause": "golden_unknown",
                "subject": "harness",
                "outcome_class": "golden_unknown",
                "notes": [],
                "ambiguity": None,
                "binding": None,
                "review": {"binding_status": "unmatched"},
                "findings": [
                    _review("golden_unknown", f"no golden {golden_id!r} in scope", "harness", "readiness")
                ],
            }
            if supplied:
                matched_review_keys.add(key)
            records.append(record)

    for golden in selected:
        golden_id = golden.get("id") if isinstance(golden, dict) else None
        group = by_golden.get(golden_id, [])
        if not group:
            for one_stage in stages:
                records.append(
                    {
                        "golden_id": golden_id,
                        "response_id": None,
                        "stage": one_stage,
                        "kind": _target_kind(golden) if isinstance(golden, dict) else "answer",
                        "status": "REVIEW",
                        "mechanical": {"status": "REVIEW", "causes": ["response_missing"]},
                        "semantic": {"status": "REVIEW", "causes": ["review_missing"]},
                        "readiness": {"status": "REVIEW", "causes": ["response_missing"]},
                        "causes": ["response_missing"],
                        "cause": "response_missing",
                        "subject": "harness",
                        "outcome_class": "response_missing",
                        "notes": [],
                        "ambiguity": None,
                        "binding": None,
                        "review": {"binding_status": "missing"},
                        "findings": [
                            _review("response_missing", f"no response captured for {golden_id!r}", "harness", "mechanical")
                        ],
                    }
                )
            continue
        for response in group:
            for one_stage in stages:
                record = _evaluate_one(golden, response, one_stage, review_table, versions, notes)
                key = (response.get("response_id"), one_stage)
                if key in review_table:
                    matched_review_keys.add(key)
                records.append(record)

    for key in review_table:
        if key not in matched_review_keys:
            findings.append(
                _review(
                    "review_orphan",
                    f"review for response {key[0]!r} stage {key[1]!r} has no graded output",
                    "harness",
                    "semantic",
                )
            )

    for key in duplicate_reviews:
        findings.append(
            _review(
                "review_duplicate",
                f"{len(review_table[key])} reviews for response {key[0]!r} stage {key[1]!r}",
                "harness",
                "semantic",
            )
        )

    if not records:
        findings.append(_review("dataset_empty", "no outputs to evaluate", "harness", "data"))

    counts = _summarize(records, rows, selected, excluded, findings, review_table, matched_review_keys, invalid_goldens)
    if (
        counts["records"] != counts["outputs_total"]
        or counts["goldens_total"]
        != counts["goldens_in_scope"] + counts["goldens_excluded"] + counts["goldens_invalid"]
    ):
        findings.append(
            _fail(
                "count_mismatch",
                "record or golden counts do not reconcile; the run cannot be called clean",
                "harness",
                "data",
            )
        )
    verdict = _worst([record["status"] for record in records] + [finding["verdict"] for finding in findings])
    report = {
        "evaluator": {
            **EVALUATOR,
            "criterion_version": versions["criterion_version"],
            "reference_version": versions["reference_version"],
            "stage": stage,
            "splits": list(split) if split != "all" else "all",
        },
        "verdict": verdict,
        "scope": "captured response only; data readiness/lineage is separate",
        "counts": counts,
        "excluded": excluded,
        "records": records,
        "findings": findings,
        "controls": {"valid": None, "controls": {}},
        "data_readiness": None,
    }
    return report


def _summarize(records, goldens, selected, excluded, findings, review_table, matched, invalid_goldens):
    counts = {
        "goldens_total": len(goldens),
        "goldens_in_scope": len(selected),
        "goldens_excluded": len(excluded),
        "goldens_invalid": invalid_goldens,
        "responses_total": len({record["response_id"] for record in records if record.get("response_id")}),
        "records": len(records),
        "outputs_total": len(records),
        "outputs_present": 0,
        "outputs_missing": 0,
        "pass": 0,
        "fail": 0,
        "review": 0,
        "mechanical": {"pass": 0, "fail": 0, "review": 0},
        "semantic": {"pass": 0, "fail": 0, "review": 0, "not_required": 0},
        "readiness": {"pass": 0, "fail": 0, "review": 0},
        "unverifiable": 0,
        "length_stop_failures": 0,
        "model_context_insufficient": 0,
        "model_refusal_withheld": 0,
        "system_retrieval_misses": 0,
        "by_subject": {},
        "by_cause": {},
        "by_behavior": {},
        "reviews": {
            "supplied": sum(len(value) for value in review_table.values()),
            "matched": len(matched),
            "missing": 0,
            "stale": 0,
            "invalid": 0,
            "orphan": 0,
            "duplicate": 0,
            "agent": 0,
            "owner": 0,
        },
    }
    for record in records:
        counts[record["status"].lower()] += 1
        if record.get("response_id") is None or any(
            code in ("model_output_unavailable", "reader_output_unavailable")
            for code in (record.get("causes") or [])
        ):
            counts["outputs_missing"] += 1
        else:
            counts["outputs_present"] += 1
        for scope in ("mechanical", "semantic", "readiness"):
            status = record[scope]["status"]
            if status in ("PASS", "FAIL", "REVIEW"):
                counts[scope][status.lower()] += 1
            elif status in ("NOT_REQUIRED", "NOT_APPLICABLE"):
                if scope == "semantic":
                    counts["semantic"]["not_required"] += 1
        if record.get("subject"):
            counts["by_subject"][record["subject"]] = counts["by_subject"].get(record["subject"], 0) + 1
        for code in record.get("causes") or []:
            counts["by_cause"][code] = counts["by_cause"].get(code, 0) + 1
        behavior = record.get("behavior") or "none"
        counts["by_behavior"][behavior] = counts["by_behavior"].get(behavior, 0) + 1
        if "output_truncated_length_stop" in (record.get("causes") or []):
            counts["length_stop_failures"] += 1
        if record.get("outcome_class") == "model_refusal_legitimate_insufficient_context":
            counts["model_context_insufficient"] += 1
        if record.get("outcome_class") == "model_refusal_legitimate_withheld_evidence":
            counts["model_refusal_withheld"] += 1
        if "system_retrieval_miss" in (record.get("causes") or []):
            counts["system_retrieval_misses"] += 1
        if any(code in ("unverifiable_transport", "unverifiable_capture", "unverifiable_no_call", "evidence_unverifiable", "evidence_text_missing", "capture_hash_mismatch", "input_hash_mismatch", "evidence_hash_mismatch", "review_unverifiable", "model_output_unavailable", "reader_output_unavailable") for code in (record.get("causes") or [])):
            counts["unverifiable"] += 1
        review = record.get("review") or {}
        if review.get("binding_status") == "stale":
            counts["reviews"]["stale"] += 1
        if review.get("binding_status") == "missing" or "review_missing" in (record.get("causes") or []):
            counts["reviews"]["missing"] += 1
        if review.get("provenance") == "agent":
            counts["reviews"]["agent"] += 1
        elif review.get("provenance") == "owner":
            counts["reviews"]["owner"] += 1
        invalid_codes = {
            "review_invalid",
            "review_unattributed",
            "review_provenance_missing",
            "review_verdict_invalid",
            "review_binding_missing",
        }
        if invalid_codes & set(record.get("causes") or []):
            counts["reviews"]["invalid"] += 1
    counts["reviews"]["orphan"] = len([finding for finding in findings if finding["code"] == "review_orphan"])
    counts["reviews"]["duplicate"] = len([finding for finding in findings if finding["code"] == "review_duplicate"])
    counts["records"] = counts["pass"] + counts["fail"] + counts["review"]
    return counts


def evaluate(
    goldens,
    responses,
    reviews=(),
    *,
    stage="model",
    split=DEFAULT_SPLITS,
    reference_version=EVALUATOR["reference_version"],
    criterion_version=EVALUATOR["criterion_version"],
    data_criteria_version=None,
    self_check=True,
):
    """Evaluate captured outputs. Pure and offline; inputs are not mutated."""
    versions = {
        "reference_version": reference_version,
        "criterion_version": criterion_version,
        "data_criteria_version": data_criteria_version,
    }
    split_set = split
    if isinstance(split, str):
        split_set = "all" if split == "all" else tuple(part.strip() for part in split.split(",") if part.strip())
    report = _evaluate_core(goldens, responses, reviews, stage=stage, versions=versions, split=split_set)
    if self_check:
        controls = self_check_report(versions)
        report["controls"] = controls
        report["valid"] = controls["valid"]
        if not controls["valid"]:
            report["findings"].append(
                _fail("controls_invalid", "built-in negative/positive controls did not behave", "harness", "data")
            )
            report["verdict"] = "FAIL"
    else:
        report["valid"] = None
    return report


def self_check_report(versions=None):
    versions = versions or {
        "reference_version": EVALUATOR["reference_version"],
        "criterion_version": EVALUATOR["criterion_version"],
        "data_criteria_version": None,
    }
    cases = _control_cases()
    controls = {}
    for name, (golden_record, response_record, review_rows, expected) in cases.items():
        report = _evaluate_core(
            [golden_record],
            [response_record],
            review_rows,
            stage="model",
            versions=versions,
            split="all",
        )
        record = report["records"][0]
        controls[name] = {
            "status": record["status"],
            "expected": expected,
            "causes": record["causes"],
            "ok": record["status"] == expected,
        }
    positive = controls.get("paraphrase_positive", {}).get("status") == "PASS"
    negatives = {
        name: row for name, row in controls.items() if name != "paraphrase_positive"
    }
    negatives_not_pass = all(row["status"] != "PASS" for row in negatives.values())
    valid = positive and negatives_not_pass and all(row["ok"] for row in controls.values())
    return {
        "valid": valid,
        "positive_pass": positive,
        "negatives_not_pass": negatives_not_pass,
        "controls": controls,
    }


def self_check():
    """Public alias for the built-in control gate."""
    return self_check_report()


def _control_golden(kind="answer"):
    record = {
        "schema_version": 1,
        "id": "control-golden",
        "family_id": "control",
        "split": "dev",
        "book_id": "fde",
        "question": "What is a watermark?",
        "history": [],
        "provided_source_ids": ["fde:ch08-039"],
        "source_refs": [
            {
                "source_id": "fde:ch08-039",
                "book_id": "fde",
                "index_path": "data/index.sqlite",
                "index_sha256": "0" * 64,
                "chunk_id": "ch08-039",
                "chapter": "8",
                "text_sha256": _sha_text(S1),
                "spans": [{"start": 0, "end": len("A watermark is a threshold"), "text": "A watermark is a threshold"}],
            }
        ],
        "expected": {
            "book_answerable": True if kind == "answer" else False,
            "evidence_sufficient": True if kind == "answer" else False,
            "allowed_behaviors": ["answer"] if kind == "answer" else ["refuse"],
            "required_facts": [{"claim": FACT, "source_ids": ["fde:ch08-039"]}] if kind == "answer" else [],
            "unsupported_claims": [],
        },
        "review": {
            "status": "accepted",
            "author": "control-author",
            "reviewer": "control-reviewer",
            "provenance": "agent",
            "notes": "synthetic control",
        },
        "origin": {
            "path": "artifacts/harnesses/reviewed_eval.py",
            "sha256": "0" * 64,
            "record": 1,
            "kind": "authored",
        },
        "target_kind": kind,
    }
    if kind == "refusal":
        record["question"] = "What is the capital of France?"
        record["provided_source_ids"] = []
        record["source_refs"] = []
    record["review"]["content_sha256"] = content_digest(record)
    record["review"]["criteria_version"] = "golden-content-v1"
    return record


S1 = (
    "A watermark is a threshold used to track the progress of a stream. "
    "It moves with the data."
)
S2 = "Batch processing handles bounded data, while stream processing handles unbounded data."
FACT = "A watermark tracks the progress of a stream."


def _control_response(body, *, golden_id="control-golden", sources=None, **over):
    record = {
        "schema_version": 1,
        "response_id": "control-response",
        "golden_id": golden_id,
        "task_stage": "model",
        "capture": {"status": "ok"},
        "input": {"question": "What is a watermark?", "history": []},
        "evidence": {
            "status": "shown",
            "sources": sources
            if sources is not None
            else [
                {
                    "source_id": "fde:ch08-039",
                    "book_id": "fde",
                    "chunk_id": "ch08-039",
                    "chapter": "8",
                    "text": S1,
                },
                {
                    "source_id": "fde:ch02-022",
                    "book_id": "fde",
                    "chunk_id": "ch02-022",
                    "chapter": "2",
                    "text": S2,
                },
            ],
        },
        "model": {
            "raw_body": body,
            "provenance": "model",
            "tag": "control-model",
            "digest": "control-digest",
            "done_reason": "stop",
        },
        "reader": {
            "final_text": body,
            "provenance": "engine",
            "code_fallback": False,
            "citations": [{"chapter": "8", "chunk_id": "ch08-039"}],
        },
    }
    record.update(over)
    return record


def _control_review(golden_record, response_record, **over):
    record = {
        "schema_version": 1,
        "review_id": "control-review",
        "golden_id": golden_record["id"],
        "response_id": response_record["response_id"],
        "stage": "model",
        "bind": bindings_for(golden_record, response_record, "model"),
        "verdict": "pass",
        "behavior": "answer",
        "rationale": "control reviewer checked the paraphrase against the shown sentence",
        "facts": [
            {
                "fact_index": 0,
                "status": "supported",
                "witness": {
                    "source_id": "fde:ch08-039",
                    "quote": "A watermark is a threshold used to track the progress of a stream.",
                },
            }
        ],
        "unsupported_claims": [],
        "utility": {"answers_question": True, "rationale": "it explains the tracking role"},
        "ambiguity": None,
        "reviewer": "control-reviewer-2",
        "provenance": "agent",
        "reviewed_at": "2026-10-29",
    }
    record.update(over)
    return record


def _control_cases():
    answer = _control_golden("answer")
    refusal = _control_golden("refusal")
    good = (
        '[Ch. 8] "A watermark is a threshold used to track the progress of a stream."\n'
        "A watermark tracks how far the incoming records have advanced."
    )
    generic = (
        '[Ch. 8] "A watermark is a threshold used to track the progress of a stream."\n'
        "Data engineering is a broad field with many practices."
    )
    paraphrase = (
        "[Ch. 8] It keeps count of how far the incoming records have advanced and "
        "uses that point to decide when to emit results."
    )
    positive_response = _control_response(paraphrase)
    positive_review = _control_review(answer, positive_response)
    forged_response = _control_response(generic)
    return {
        "echo": (answer, _control_response("What is a watermark?"), [], "FAIL"),
        "generic_correct_quote": (answer, _control_response(generic), [], "REVIEW"),
        "generic_forged_review": (
            answer,
            forged_response,
            [_control_review(answer, forged_response, facts=[])],
            "FAIL",
        ),
        "wrong_cite": (
            answer,
            _control_response(
                '[Ch. 2] "A watermark is a threshold used to track the progress of a stream."\n'
                "A watermark tracks how far a stream has advanced."
            ),
            [],
            "FAIL",
        ),
        "forged_quote": (
            answer,
            _control_response(
                '[Ch. 8] "A watermark is the capital of France and also a small moon."\n'
                "The book does not say that."
            ),
            [],
            "FAIL",
        ),
        "refuse_all": (answer, _control_response("Not in this book."), [], "FAIL"),
        "valid_refusal_absent": (
            refusal,
            _control_response(
                "Paris is the capital of France.",
                golden_id="control-golden",
                sources=[],
            ),
            [],
            "FAIL",
        ),
        "quote_only": (
            answer,
            _control_response(
                '[Ch. 8] "A watermark is a threshold used to track the progress of a stream."'
            ),
            [],
            "FAIL",
        ),
        "missing_evidence": (
            answer,
            _control_response(good, evidence={"status": "missing", "sources": []}),
            [],
            "REVIEW",
        ),
        "transport_error": (
            answer,
            _control_response(good, capture={"status": "transport_error", "error": "reset"}),
            [],
            "REVIEW",
        ),
        "paraphrase_positive": (answer, positive_response, [positive_review], "PASS"),
    }


def _data_readiness(goldens, golden_path, train_corpus):
    try:
        import dataset_integrity  # noqa: F401
    except Exception as exc:
        return {"available": False, "error": str(exc), "note": "separate data quality; never used to grade a response"}
    if not callable(getattr(dataset_integrity, "check_records", None)):
        return {"available": False, "error": "check_records missing", "note": "separate data quality; never used to grade a response"}
    try:
        report = dataset_integrity.check_records(
            goldens,
            name=golden_path or "<memory>",
            train_corpus=train_corpus,
        )
    except Exception as exc:
        return {"available": False, "error": str(exc), "note": "separate data quality; never used to grade a response"}
    return {
        "available": True,
        "verdict": report.get("verdict"),
        "counts": report.get("counts"),
        "integrity": (report.get("integrity") or {}).get("verdict"),
        "lineage": report.get("lineage"),
        "review": report.get("review"),
        "note": "separate full-N data quality; never used to grade a response",
    }


def evaluate_files(
    golden_path,
    responses_path,
    reviews_path=None,
    *,
    stage="model",
    split=DEFAULT_SPLITS,
    reference_version=EVALUATOR["reference_version"],
    criterion_version=EVALUATOR["criterion_version"],
    data_criteria_version=None,
    self_check=True,
    golden_readiness=False,
    train_corpus=None,
):
    goldens, golden_resolved, golden_sha, golden_error = _read_rows(golden_path)
    responses, responses_resolved, responses_sha, responses_error = _read_rows(responses_path)
    reviews, reviews_resolved, reviews_sha, reviews_error = (
        _read_rows(reviews_path) if reviews_path else ([], None, None, None)
    )
    inputs = {
        "golden": {"path": golden_resolved, "sha256": golden_sha},
        "responses": {"path": responses_resolved, "sha256": responses_sha},
        "reviews": {"path": reviews_resolved, "sha256": reviews_sha} if reviews_path else None,
    }
    if golden_error or responses_error or reviews_error:
        findings = []
        for label, error in (("golden", golden_error), ("responses", responses_error), ("reviews", reviews_error)):
            if error:
                findings.append(_fail("input_file_missing", f"{label}: {error}", "harness", "data"))
        report = _empty_report(
            {
                "reference_version": reference_version,
                "criterion_version": criterion_version,
            }
        )
        report["verdict"] = "FAIL"
        report["findings"] = findings
        report["inputs"] = inputs
        report["created_at"] = datetime.now(timezone.utc).isoformat()
        return report

    report = evaluate(
        goldens,
        responses,
        reviews,
        stage=stage,
        split=split,
        reference_version=reference_version,
        criterion_version=criterion_version,
        data_criteria_version=data_criteria_version,
        self_check=self_check,
    )
    report["inputs"] = inputs
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    if golden_readiness:
        report["data_readiness"] = _data_readiness(goldens, golden_resolved, train_corpus)
    return report


def _print_summary(report):
    counts = report.get("counts") or {}
    print(f"reviewed-eval: {report.get('verdict')}")
    print(
        "records {records} = pass {pass} / fail {fail} / review {review}".format(
            records=counts.get("records", 0),
            **{"pass": counts.get("pass", 0), "fail": counts.get("fail", 0), "review": counts.get("review", 0)},
        )
    )
    print(
        "goldens {goldens} in scope, {excluded} excluded".format(
            goldens=counts.get("goldens_in_scope", 0),
            excluded=counts.get("goldens_excluded", 0),
        )
    )
    causes = counts.get("by_cause") or {}
    if causes:
        top = sorted(causes.items(), key=lambda item: (-item[1], item[0]))[:8]
        print("causes: " + ", ".join(f"{name}={count}" for name, count in top))
    controls = report.get("controls") or {}
    print(f"controls: {'valid' if controls.get('valid') else 'INVALID'}")
    readiness = report.get("data_readiness")
    if readiness:
        print(
            "data readiness: {verdict} (separate from response verdict)".format(
                verdict=readiness.get("verdict") or readiness.get("error")
            )
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate captured responses with bound reviews.")
    parser.add_argument("--golden", required=True, help="canonical golden JSONL")
    parser.add_argument("--responses", required=True, help="captured response JSONL")
    parser.add_argument("--reviews", default=None, help="semantic review JSONL (optional)")
    parser.add_argument("--stage", choices=("model", "system", "both"), default="model")
    parser.add_argument(
        "--split",
        default="dev,test,review",
        help="comma-separated splits, or 'all' (default: dev,test,review)",
    )
    parser.add_argument("--criterion-version", default=EVALUATOR["criterion_version"])
    parser.add_argument("--reference-version", default=EVALUATOR["reference_version"])
    parser.add_argument("--data-criteria-version", default=None)
    parser.add_argument("--golden-readiness", action="store_true", help="run the separate dataset validator")
    parser.add_argument("--train-corpus", default=None, help="only for --golden-readiness")
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    parser.add_argument("--out", default=None, help="write JSON here; refuses to overwrite")
    parser.add_argument("--no-self-check", action="store_true", help="disable the built-in control gate")
    args = parser.parse_args(argv)

    if args.out:
        out_path = Path(args.out)
        if out_path.exists():
            print(f"refusing to overwrite existing report: {out_path}", file=sys.stderr)
            return 2

    report = evaluate_files(
        args.golden,
        args.responses,
        args.reviews,
        stage=args.stage,
        split=args.split,
        reference_version=args.reference_version,
        criterion_version=args.criterion_version,
        data_criteria_version=args.data_criteria_version,
        self_check=not args.no_self_check,
        golden_readiness=args.golden_readiness,
        train_corpus=args.train_corpus,
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")
    if args.json or args.out:
        print(payload)
    else:
        _print_summary(report)
    return EXIT.get(report.get("verdict"), 2)


if __name__ == "__main__":
    sys.exit(main())
