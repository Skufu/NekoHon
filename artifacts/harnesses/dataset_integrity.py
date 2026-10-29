"""Dataset integrity: is this data ready to be used as training or eval truth?

Every rule here exists because a dataset lied once: a quote that appeared
nowhere in the book, a chapter that moved after a re-chunk, gold that was never
shown to the model, a family split across train and test, and a "clean"
leakage result produced without reading the training corpus.

Verdicts are about the DATA. The validator never reads an answer for
correctness, never scores a model, and never decides truth from word overlap.
A shared keyword is not a fact; claim-level entailment is a reviewer's
attestation, and the validator checks that the attestation exists, is signed by
someone other than the author, and binds the exact bytes reviewed
(``review.content_sha256 = review_digest(record)``). That binding protects the
attestation from stale changes; it is not proof the claim is true. Every cited
witness must resolve to the source it names. Literal book quotes in the target
(a line starting ``[Ch. N] "`` or a ``citations[].quote``) are checked verbatim
against provided sources, wrapped lines included; unmarked prose is never
compared.

Two scopes are reported separately:

- ``integrity``  — record readiness (source truth, schema, provenance, review).
- ``lineage``    — cross-split exposure: families and answer-support sources.

A missing training corpus is ``lineage.status: "unknown"``, never a clean bill.
Disjointness is proven only against the corpus supplied; earlier corpora are
not implied, and no old corpus has to be recovered for a new one to pass.

Contract and scope rules: ``artifacts/runs/data-repair-2026-10-29/validator/
SCHEMA.md``. Stdlib only.

CLI::

    python artifacts/harnesses/dataset_integrity.py \\
        --dataset artifacts/datasets/X.jsonl [--dataset ...] \\
        [--train-corpus data/finetune/Y.jsonl] [--verify-origins] [--release]

JSON on stdout. Exit 0 PASS, 1 REVIEW, 2 FAIL. ``--release`` is the acceptance
wrapper: it requires ``--verify-origins`` and marks the report scope.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

VALIDATOR = {"name": "dataset_integrity", "version": "1.1.0", "schema_version": 1}
REFUSAL = "Not in this book."

SPLITS = ("train", "dev", "test", "review")
EVAL_SPLITS = ("dev", "test", "review")
BEHAVIORS = ("answer", "refuse", "boundary")
REVIEW_STATUSES = ("accepted", "needs_review", "rejected")
PROVENANCES = ("agent", "owner")
ORIGIN_KINDS = ("original", "reconstructed", "repaired", "authored")
TARGET_KINDS = ("answer", "gloss", "refusal")
SOURCE_KINDS = ("chunk", "caption", "synthetic")
SOURCE_ROLES = ("support", "distractor", "refusal_nearby", "history")
CONTEXT_ROLES = ("distractor", "refusal_nearby", "history")
TASK_STAGES = ("model", "system")
SUPPORT_MODES = ("any", "all")

LINEAGE_CODES = (
    "family_split_leak",
    "source_component_split_leak",
    "source_text_split_leak",
    "paraphrase_split_leak",
    "duplicate_full_input_across_splits",
)
RANK = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
EXIT = {"PASS": 0, "REVIEW": 1, "FAIL": 2}


def _fail(code, detail, scope="integrity"):
    return {"code": code, "verdict": "FAIL", "detail": detail, "scope": scope}


def _review(code, detail, scope="integrity"):
    return {"code": code, "verdict": "REVIEW", "detail": detail, "scope": scope}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _sha(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _verdict(findings):
    worst = "PASS"
    for finding in findings:
        if RANK[finding["verdict"]] > RANK[worst]:
            worst = finding["verdict"]
    return worst


def review_digest(record):
    """sha256 of the canonical record with its whole ``review`` block removed.

    The review names content it approved; hashing the record without the review
    keeps the signature out of its own input. Canonical form: UTF-8,
    ``json.dumps(sort_keys=True, separators=(",", ":")), ensure_ascii=False``,
    no NFKC and no whitespace folding.
    """
    payload = {key: value for key, value in record.items() if key != "review"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _question_key(question):
    return " ".join((question or "").lower().split()).rstrip("?.! ").strip()


def _input_identity(record, refs_by_id):
    """The model input: question, history, provided source content, prompt family.

    Provided sources are identified by ``(book_id, text_sha256)``, never by
    ``source_id``: renaming an id must not launder the same text into a
    different input.
    """
    question = _question_key(record.get("question") or "")
    history = record.get("history")
    try:
        history_key = json.dumps(
            history if isinstance(history, list) else [],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        history_key = ""
    contents = set()
    provided = record.get("provided_source_ids")
    if isinstance(provided, list):
        for source_id in provided:
            ref = refs_by_id.get(source_id)
            if isinstance(ref, dict) and _text(ref.get("book_id")) and _sha(ref.get("text_sha256")):
                contents.add((ref["book_id"], ref["text_sha256"]))
            elif _text(source_id):
                contents.add(("unresolved", source_id))
    metadata = record.get("metadata")
    prompt = metadata.get("prompt_family") if isinstance(metadata, dict) else None
    prompt_family = prompt.strip() if _text(prompt) else ""
    ordered = tuple(sorted(contents))
    return question, (question, history_key, ordered, prompt_family)


def _linked(first, second):
    """Deliberate variants: one family, or a declared paraphrase link."""
    if first["family_id"] and first["family_id"] == second["family_id"]:
        return True
    if second["id"] and second["id"] in first.get("paraphrase_of", []):
        return True
    if first["id"] and first["id"] in second.get("paraphrase_of", []):
        return True
    return False


def _citation_key(citation):
    if isinstance(citation, str):
        return citation
    if isinstance(citation, dict):
        return next(
            (citation[name] for name in ("source_id", "chunk_id", "id") if _text(citation.get(name))),
            None,
        )
    return None


class _Indexes:
    """Read-only index cache; each file is hashed and parsed at most once."""

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self._cache = {}

    def _resolve(self, raw):
        path = Path(raw)
        return path if path.is_absolute() else self.root / path

    def load(self, raw):
        if raw not in self._cache:
            path = self._resolve(raw)
            if not path.is_file():
                self._cache[raw] = (None, _fail("source_index_missing", f"index not found: {path}"))
            else:
                raw_bytes = path.read_bytes()
                sha = hashlib.sha256(raw_bytes).hexdigest()
                try:
                    doc = json.loads(raw_bytes.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    self._cache[raw] = (
                        None,
                        _fail("source_index_unreadable", f"{path}: {exc}"),
                    )
                else:
                    self._cache[raw] = (
                        {"path": str(path), "sha256": sha, "doc": doc},
                        None,
                    )
        return self._cache[raw]


def _span_findings(spans, text):
    findings = []
    for i, span in enumerate(spans):
        if not isinstance(span, dict):
            findings.append(_fail("schema", f"spans[{i}] must be an object"))
            continue
        start, end, literal = span.get("start"), span.get("end"), span.get("text")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
        ):
            findings.append(_fail("schema", f"spans[{i}] start/end must be integers"))
            continue
        if not isinstance(literal, str):
            findings.append(_fail("schema", f"spans[{i}].text must be a string"))
            continue
        if start < 0 or end <= start or end > len(text):
            findings.append(
                _fail("span_bounds", f"spans[{i}] [{start},{end}) outside 0..{len(text)}")
            )
            continue
        if text[start:end] == literal:
            continue
        if literal and literal in text:
            findings.append(
                _fail(
                    "span_offsets_wrong",
                    f"spans[{i}] text sits at offset {text.index(literal)}, not [{start},{end})",
                )
            )
        else:
            findings.append(
                _fail("span_text_mismatch", f"spans[{i}] is not a literal slice of the source")
            )
    return findings


def _check_source(ref, record_book, indexes):
    """Resolve one source_ref against its index. Returns (resolved, findings)."""
    findings = []
    if not isinstance(ref, dict):
        return None, [_fail("schema", "source_refs entries must be objects")]

    source_id = ref.get("source_id")
    book = ref.get("book_id")
    index_path = ref.get("index_path")
    index_sha = ref.get("index_sha256")
    text_sha = ref.get("text_sha256")
    chapter = ref.get("chapter")
    kind = ref.get("kind", "chunk")
    role = ref.get("role")
    spans = ref.get("spans", [])

    for name, value in (
        ("source_id", source_id),
        ("book_id", book),
        ("index_path", index_path),
        ("chapter", chapter),
    ):
        if not _text(value):
            findings.append(_fail("schema", f"source_refs[].{name} missing or empty"))
    if not _sha(index_sha):
        findings.append(_fail("schema", "source_refs[].index_sha256 must be 64 lowercase hex"))
    if not _sha(text_sha):
        findings.append(_fail("schema", "source_refs[].text_sha256 must be 64 lowercase hex"))
    if kind not in SOURCE_KINDS:
        findings.append(_fail("source_kind_invalid", f"source kind {kind!r} is not one of {SOURCE_KINDS}"))
    if role is not None and role not in SOURCE_ROLES:
        findings.append(_fail("source_role_invalid", f"source role {role!r} is not one of {SOURCE_ROLES}"))
    if not isinstance(spans, list):
        findings.append(_fail("schema", "source_refs[].spans must be a list"))
        spans = []
    if record_book and book and book != record_book:
        findings.append(
            _fail("mixed_book_id", f"record is {record_book!r} but source is {book!r}")
        )
    if not (_text(book) and _text(index_path)):
        return None, findings

    entry, error = indexes.load(index_path)
    if error:
        return None, findings + [error]
    doc = entry["doc"]
    if index_sha != entry["sha256"]:
        findings.append(
            _fail(
                "source_index_stale",
                f"record pins {str(index_sha)[:12]}…, file is {entry['sha256'][:12]}…",
            )
        )
    if doc.get("book_id") != book:
        findings.append(
            _fail("book_id_mismatch", f"index book is {doc.get('book_id')!r}, source says {book!r}")
        )

    if kind == "caption":
        figure_id = ref.get("figure_id")
        if not _text(figure_id):
            findings.append(_fail("caption_figure_missing", "kind=caption requires figure_id"))
            return None, findings
        matches = [f for f in doc.get("figures", []) if f.get("id") == figure_id]
        if not matches:
            findings.append(_fail("source_missing", f"figure {figure_id!r} not in {index_path}"))
            return None, findings
        if len(matches) > 1:
            findings.append(_fail("source_ambiguous", f"figure {figure_id!r} appears {len(matches)} times"))
            return None, findings
        item = matches[0]
        chunk_id = None
        component = f"caption:{figure_id}"
        text = item.get("caption") or ""
    else:
        chunk_id = ref.get("chunk_id")
        if not _text(chunk_id):
            findings.append(_fail("schema", "source_refs[].chunk_id missing or empty"))
            return None, findings
        matches = [c for c in doc.get("chunks", []) if c.get("chunk_id") == chunk_id]
        if not matches:
            findings.append(_fail("source_missing", f"chunk {chunk_id!r} not in {index_path}"))
            return None, findings
        if len(matches) > 1:
            findings.append(
                _fail("source_ambiguous", f"chunk {chunk_id!r} appears {len(matches)} times")
            )
            return None, findings
        item = matches[0]
        component = f"chunk:{chunk_id}"
        text = item.get("text") or ""

    actual_chapter = item.get("chapter")
    if _text(chapter) and str(actual_chapter) != str(chapter):
        findings.append(
            _fail(
                "source_chapter_mismatch",
                f"record says chapter {chapter!r}, index has {actual_chapter!r}",
            )
        )
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != text_sha:
        findings.append(
            _fail("source_text_hash_mismatch", f"{component} text does not hash to text_sha256")
        )
    findings.extend(_span_findings(spans, text))

    resolved = {
        "source_id": source_id,
        "book_id": book,
        "chunk_id": chunk_id,
        "chapter": actual_chapter,
        "kind": kind,
        "role": role,
        "text": text,
        "component": (book, index_sha, component),
        "text_key": (book, text_sha),
        "spans": [
            (span.get("start"), span.get("end"))
            for span in spans
            if isinstance(span, dict)
            and isinstance(span.get("start"), int)
            and isinstance(span.get("end"), int)
        ],
    }
    return resolved, findings


_QUOTE_OPEN = re.compile(r'^\s*\[\s*(Ch\.[^\]]*)\]\s*["“]')
_QUOTE_CLOSE = re.compile(r'["”]')
_CHUNKISH = re.compile(r"^[A-Za-z]+\d*-\d+[A-Za-z0-9-]*$")


def _marked_quotes(answer):
    """Split an answer into marked book quotes, allowing wrapped lines.

    Only a line that starts with ``[Ch. N] "`` is a quote claim. A quote ends at
    the first closing delimiter; everything inside, newlines included, must
    match the source literally. A quote with no closer before another
    ``[Ch. …] "`` marker is unparsed, never fused into the next quote.
    """
    quotes, unparsed = [], []
    lines = answer.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        marker = _QUOTE_OPEN.match(lines[index])
        if not marker:
            index += 1
            continue
        tag = marker.group(1).strip()
        cursor = index
        start = marker.end()
        body = []
        closed = False
        while cursor < len(lines):
            text = lines[cursor]
            begin = start if cursor == index else 0
            if cursor > index and _QUOTE_OPEN.match(text):
                break
            close = _QUOTE_CLOSE.search(text, begin)
            if close:
                body.append(text[begin : close.start()])
                closed = True
                break
            body.append(text[begin:])
            cursor += 1
            start = 0
        if closed:
            quotes.append({"tag": tag, "text": "".join(body)})
            index = cursor + 1
        else:
            snippet = ("".join(body).strip() or lines[index].strip())[:60]
            unparsed.append(snippet)
            index = cursor if cursor > index else index + 1
    return quotes, unparsed


def _tag_locator(tag, provided):
    """Resolve a quote tag to a chunk id or a chapter set, never to the book."""
    chunk_ids = {source.get("chunk_id") for source in provided if source.get("chunk_id")}
    tokens = [token.strip() for token in re.split(r"[,\s]+", tag) if token.strip()]
    for token in tokens:
        if token in chunk_ids:
            return ("chunk", token), []
    for token in tokens:
        if _CHUNKISH.match(token):
            return None, [
                _fail(
                    "target_quote_source_unmatched",
                    f"quote names chunk {token!r}, not in provided sources",
                )
            ]
    chapters = re.findall(r"Ch\.\s*([A-Za-z0-9]+)", tag)
    if chapters:
        return ("chapter", set(chapters)), []
    return None, [
        _review("target_quote_unparsed", f"quote tag has no chapter or provided chunk id: {tag!r}")
    ]


def _quote_candidates(kind, value, provided):
    if kind == "chunk":
        found = [source for source in provided if source.get("chunk_id") == value]
        if not found:
            return None, [
                _fail("target_quote_source_unmatched", f"quote names chunk {value!r}, not in provided sources")
            ]
    elif kind == "source":
        found = [source for source in provided if source.get("source_id") == value]
        if not found:
            return None, [
                _fail("target_quote_source_unmatched", f"quote names source {value!r}, not provided")
            ]
    elif kind == "chapter":
        found = [source for source in provided if str(source.get("chapter")) in value]
        if not found:
            return None, [
                _fail(
                    "target_quote_chapter_unmatched",
                    f"quote names chapter(s) {sorted(value)}, not in provided sources",
                )
            ]
    else:
        found = list(provided)
        if not found:
            return None, [
                _fail("target_quote_source_unmatched", "no provided source to check the quote against")
            ]
    return found, []


def _match_quote(text, candidates, label, allow_multi=False):
    if not text.strip():
        return [_review("target_quote_unparsed", f"{label}: empty marked quote")]
    matches = [source for source in candidates if text in (source.get("text") or "")]
    if not matches:
        return [
            _fail(
                "target_quote_not_in_source",
                f"{label}: quote is not a literal substring of the named source",
            )
        ]
    if len(matches) > 1 and not allow_multi:
        return [
            _review(
                "target_quote_ambiguous",
                f"{label}: quote appears in {len(matches)} provided sources",
            )
        ]
    return []


def _check_target_quotes(target, resolved, provided):
    """Literal book quotes in the target are claims; unmarked prose is not."""
    if not isinstance(target, dict):
        return []
    if target.get("kind") == "refusal" or target.get("refused") is True:
        return []
    provided_sources = [resolved[sid] for sid in dict.fromkeys(provided) if sid in resolved]
    findings = []

    answer = target.get("answer")
    if isinstance(answer, str):
        quotes, unparsed = _marked_quotes(answer)
        for line in unparsed:
            findings.append(
                _review(
                    "target_quote_unparsed",
                    f"marked quote does not close on its line: {line[:60]!r}",
                )
            )
        for quote in quotes:
            locator, locator_findings = _tag_locator(quote["tag"], provided_sources)
            findings.extend(locator_findings)
            if locator is None:
                continue
            kind, value = locator
            candidates, candidate_findings = _quote_candidates(kind, value, provided_sources)
            findings.extend(candidate_findings)
            if candidates is None:
                continue
            findings.extend(
                _match_quote(
                    quote["text"],
                    candidates,
                    f"answer quote [{quote['tag']}]",
                    allow_multi=(kind == "chapter" and len(value) > 1),
                )
            )

    citations = target.get("citations")
    if isinstance(citations, list):
        for citation in citations:
            if not isinstance(citation, dict) or citation.get("quote") is None:
                continue
            quote = citation.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                findings.append(
                    _review("target_quote_unparsed", "citation.quote is empty or not a string")
                )
                continue
            if _text(citation.get("chunk_id")):
                locator = ("chunk", citation["chunk_id"])
            elif _text(citation.get("source_id")):
                locator = ("source", citation["source_id"])
            elif _text(citation.get("chapter")):
                locator = ("chapter", {str(citation["chapter"])})
            else:
                locator = ("any", None)
            candidates, candidate_findings = _quote_candidates(locator[0], locator[1], provided_sources)
            findings.extend(candidate_findings)
            if candidates is None:
                continue
            findings.extend(
                _match_quote(
                    quote,
                    candidates,
                    "citation.quote",
                    allow_multi=(locator[0] == "chapter" and len(locator[1]) > 1),
                )
            )
    return findings


def _check_origin(origin, indexes, verify, dataset=None):
    findings = []
    if not isinstance(origin, dict):
        return [_fail("schema", "origin must be an object")]
    for name in ("path", "sha256"):
        if not _text(origin.get(name)):
            findings.append(_fail("schema", f"origin.{name} missing or empty"))
    if origin.get("sha256") and not _sha(origin.get("sha256")):
        findings.append(_fail("schema", "origin.sha256 must be 64 lowercase hex"))
    if origin.get("kind") not in ORIGIN_KINDS:
        findings.append(_fail("origin_kind_invalid", f"origin kind {origin.get('kind')!r}"))
    record_ref = origin.get("record")
    if not (isinstance(record_ref, (int, str)) and str(record_ref).strip()):
        findings.append(_fail("schema", "origin.record missing"))
    if dataset and _text(origin.get("path")):
        origin_path = Path(origin["path"])
        if not origin_path.is_absolute():
            origin_path = indexes.root / origin_path
        if origin_path.resolve() == Path(dataset).resolve():
            findings.append(
                _fail(
                    "origin_self_reference",
                    "origin.path is the dataset being validated; point it at the upstream "
                    "input (index, capture, or seed file) and keep the output hash in an "
                    "external manifest",
                )
            )
    if verify and _text(origin.get("path")):
        path = Path(origin["path"])
        if not path.is_absolute():
            path = indexes.root / path
        if not path.is_file():
            findings.append(_review("origin_unverified", f"{path} is not readable"))
        elif hashlib.sha256(path.read_bytes()).hexdigest() != origin.get("sha256"):
            findings.append(_fail("origin_stale", f"{path} does not match origin.sha256"))
    return findings


def _check_review(review, facts, digest):
    findings = []
    if not isinstance(review, dict):
        return [_fail("schema", "review must be an object")], {}
    status = review.get("status")
    author = review.get("author")
    reviewer = review.get("reviewer")
    provenance = review.get("provenance")
    if status not in REVIEW_STATUSES:
        findings.append(_fail("schema", f"review.status {status!r} is not one of {REVIEW_STATUSES}"))
    if status == "accepted":
        if not _text(author) or not _text(reviewer):
            findings.append(_fail("review_unattributed", "accepted review needs author and reviewer"))
        elif author.strip().casefold() == reviewer.strip().casefold():
            findings.append(_fail("self_review", f"{reviewer!r} reviewed their own record"))
        if provenance not in PROVENANCES:
            findings.append(
                _fail("review_provenance", f"review.provenance {provenance!r} is not one of {PROVENANCES}")
            )
        if not _text(review.get("criteria_version")):
            findings.append(
                _fail(
                    "review_criteria_missing",
                    "accepted review needs a non-empty criteria_version (e.g. source-grounding-v1)",
                )
            )
        recorded = review.get("content_sha256")
        if not _sha(recorded):
            findings.append(
                _fail(
                    "review_digest_missing",
                    "accepted review needs content_sha256 = review_digest(record)",
                )
            )
        elif recorded != digest:
            findings.append(
                _fail(
                    "review_digest_stale",
                    f"review signed {recorded[:12]}…, record now hashes to {digest[:12]}…",
                )
            )
    elif status == "rejected":
        findings.append(_fail("review_rejected", "reviewer rejected this record"))
    elif status == "needs_review":
        findings.append(_review("review_pending", "review.status is needs_review"))
    if facts and status != "accepted":
        findings.append(
            _review("facts_unreviewed", "required facts have no accepted reviewer attestation")
        )
    stats = {
        "status": status,
        "provenance": provenance,
        "reviewer": reviewer.strip() if _text(reviewer) else None,
        "criteria_version": review.get("criteria_version") if _text(review.get("criteria_version")) else None,
        "facts": len(facts) if status == "accepted" else 0,
    }
    return findings, stats


def _check_record(record, indexes, verify_origins, dataset=None):
    result = {
        "id": None,
        "dataset": None,
        "line": None,
        "split": None,
        "family_id": None,
        "book_id": None,
        "verdict": "PASS",
        "findings": [],
        "notes": [],
    }
    meta = {
        "id": None,
        "family_id": None,
        "split": None,
        "question": "",
        "support": [],
        "context": [],
        "paraphrase_of": [],
        "review": {},
    }
    findings = result["findings"]
    notes = result["notes"]

    if not isinstance(record, dict):
        findings.append(_fail("schema", "record is not a JSON object"))
        return result, meta

    if record.get("schema_version") != 1:
        findings.append(_fail("schema", "schema_version must be the integer 1"))
    for name in ("id", "family_id", "book_id", "question"):
        if not _text(record.get(name)):
            findings.append(_fail("schema", f"{name} missing or empty"))
    split = record.get("split")
    if split not in SPLITS:
        findings.append(_fail("schema", f"split {split!r} is not one of {SPLITS}"))
        split = None
    history = record.get("history")
    if not isinstance(history, list):
        findings.append(_fail("schema", "history must be a list"))
    provided = record.get("provided_source_ids")
    if not isinstance(provided, list):
        findings.append(_fail("schema", "provided_source_ids must be a list"))
        provided = []
    refs = record.get("source_refs")
    if not isinstance(refs, list) or not refs:
        findings.append(_fail("schema", "source_refs must be a non-empty list"))
        refs = []
    expected = record.get("expected")
    if not isinstance(expected, dict):
        findings.append(_fail("schema", "expected must be an object"))
        expected = {}
    stage = record.get("task_stage", "model")
    if stage not in TASK_STAGES:
        findings.append(_fail("schema", f"task_stage {stage!r} is not one of {TASK_STAGES}"))
        stage = "model"
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        findings.append(_fail("schema", "metadata must be an object"))
        metadata = {}
    absence = record.get("absence_evidence")
    if absence is not None and (not isinstance(absence, dict) or not _text(absence.get("reason"))):
        findings.append(
            _fail("schema", "absence_evidence must be an object with a non-empty reason")
        )

    result.update(
        {
            "id": record.get("id") if _text(record.get("id")) else None,
            "split": split,
            "family_id": record.get("family_id") if _text(record.get("family_id")) else None,
            "book_id": record.get("book_id") if _text(record.get("book_id")) else None,
        }
    )
    refs_by_id = {}
    for ref in refs:
        if isinstance(ref, dict) and _text(ref.get("source_id")):
            refs_by_id.setdefault(ref["source_id"], ref)
    question_key, input_key = _input_identity(record, refs_by_id)
    meta.update(
        {
            "id": result["id"],
            "family_id": result["family_id"],
            "split": split,
            "question": question_key,
            "input_key": input_key,
        }
    )

    # -- sources ---------------------------------------------------------
    resolved = {}
    declared = []
    for ref in refs:
        source, bad = _check_source(ref, result["book_id"], indexes)
        findings.extend(bad)
        if isinstance(ref, dict) and isinstance(ref.get("source_id"), str):
            declared.append(ref["source_id"])
        if source and source["source_id"] and source["source_id"] not in resolved:
            resolved[source["source_id"]] = source
    for source_id in set(declared):
        count = declared.count(source_id)
        if count > 1:
            findings.append(_fail("source_id_duplicate", f"source_id {source_id!r} declared {count} times"))
    for source_id in provided:
        if source_id not in declared:
            findings.append(_fail("provided_source_unknown", f"provided id {source_id!r} has no source_ref"))
    if len(set(provided)) != len(provided):
        findings.append(_fail("provided_source_duplicate", "provided_source_ids repeats an id"))

    synthetic = any(source["kind"] == "synthetic" for source in resolved.values())
    if synthetic:
        if metadata.get("synthetic") is not True:
            findings.append(
                _fail("synthetic_undeclared", "a synthetic source needs metadata.synthetic = true")
            )
        else:
            notes.append("synthetic_source")

    # -- expected --------------------------------------------------------
    book_answerable = expected.get("book_answerable")
    if book_answerable is not None and not isinstance(book_answerable, bool):
        findings.append(_fail("schema", "expected.book_answerable must be bool or null"))
    evidence_sufficient = expected.get("evidence_sufficient")
    if evidence_sufficient is not None and not isinstance(evidence_sufficient, bool):
        findings.append(_fail("schema", "expected.evidence_sufficient must be bool or null"))
    behaviors = expected.get("allowed_behaviors")
    if not isinstance(behaviors, list) or not behaviors:
        findings.append(_fail("schema", "expected.allowed_behaviors must be a non-empty list"))
        behaviors = []
    elif any(behavior not in BEHAVIORS for behavior in behaviors):
        findings.append(_fail("behaviors_invalid", f"allowed_behaviors {behaviors!r}"))
    if "answer" in behaviors and "refuse" in behaviors:
        findings.append(_review("behavior_allows_anything", "answer and refuse are both allowed"))

    facts = expected.get("required_facts", [])
    if not isinstance(facts, list):
        findings.append(_fail("schema", "expected.required_facts must be a list"))
        facts = []
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict) or not _text(fact.get("claim")):
            findings.append(_fail("schema", f"required_facts[{i}].claim missing"))
            continue
        ids = fact.get("source_ids")
        if not isinstance(ids, list) or not ids or any(not _text(sid) for sid in ids):
            findings.append(_fail("schema", f"required_facts[{i}].source_ids must name sources"))
            continue
        if fact.get("support_mode") not in (None,) + SUPPORT_MODES:
            findings.append(
                _fail("support_mode_invalid", f"required_facts[{i}].support_mode {fact.get('support_mode')!r}")
            )
        for source_id in ids:
            if source_id not in declared:
                findings.append(
                    _fail("fact_source_missing", f"required_facts[{i}] cites undeclared {source_id!r}")
                )
    unsupported = expected.get("unsupported_claims", [])
    if not isinstance(unsupported, list):
        findings.append(_fail("schema", "expected.unsupported_claims must be a list"))

    if split in EVAL_SPLITS:
        if book_answerable is None:
            findings.append(_review("book_answerability_unknown", "book_answerable is null on an eval row"))
        if evidence_sufficient is None:
            findings.append(_review("evidence_sufficiency_unknown", "evidence_sufficient is null on an eval row"))

    if evidence_sufficient is False and "answer" in behaviors:
        if stage == "system":
            notes.append("system_retrieval_diagnostic")
        else:
            findings.append(
                _fail(
                    "answer_with_insufficient_evidence",
                    "an answer is expected from evidence the record says is insufficient",
                )
            )
    if stage == "model" and "answer" in behaviors and not provided:
        findings.append(_fail("no_provided_sources_for_answer", "answer expected but no context is provided"))
    if stage == "model" and "answer" in behaviors and evidence_sufficient is not False and facts:
        provided_set = set(provided)
        for i, fact in enumerate(facts):
            if not isinstance(fact, dict) or not isinstance(fact.get("source_ids"), list):
                continue
            ids = [sid for sid in fact["source_ids"] if sid in declared]
            if not ids:
                continue
            if fact.get("support_mode") == "all":
                missing = [sid for sid in ids if sid not in provided_set]
            else:
                missing = [] if any(sid in provided_set for sid in ids) else ids
            if missing:
                findings.append(
                    _fail(
                        "gold_context_unprovided",
                        f"required_facts[{i}] witness {missing[0]!r} is not in provided_source_ids",
                    )
                )

    # -- review and origin ----------------------------------------------
    try:
        digest = review_digest(record)
    except (TypeError, ValueError):
        findings.append(_fail("schema", "record holds a value that is not canonical JSON"))
        digest = ""
    review_findings, review_stats = _check_review(record.get("review"), facts, digest)
    findings.extend(review_findings)
    meta["review"] = review_stats
    result["review"] = review_stats
    findings.extend(_check_origin(record.get("origin"), indexes, verify_origins, dataset))

    # -- target ----------------------------------------------------------
    target = record.get("target")
    is_refusal = False
    if target is not None:
        if not isinstance(target, dict):
            findings.append(_fail("schema", "target must be an object"))
            target = {}
        kind = target.get("kind")
        if kind not in TARGET_KINDS:
            findings.append(_fail("schema", f"target.kind {kind!r} is not one of {TARGET_KINDS}"))
        refused = target.get("refused", False)
        if not isinstance(refused, bool):
            findings.append(_fail("schema", "target.refused must be boolean"))
            refused = False
        if kind == "refusal" and refused is False:
            findings.append(_fail("target_kind_conflict", "kind=refusal with refused=false"))
        is_refusal = kind == "refusal" or refused is True
        answer = target.get("answer")
        if is_refusal:
            if not isinstance(answer, str) or answer.strip() != REFUSAL:
                findings.append(
                    _fail("refusal_not_exact", f"refusal target must be exactly {REFUSAL!r}")
                )
            if "refuse" not in behaviors:
                findings.append(_fail("behavior_target_conflict", "refusal target without 'refuse' allowed"))
            if book_answerable is True and evidence_sufficient is True and not unsupported:
                findings.append(
                    _review(
                        "refusal_on_answerable_book_question",
                        "book answers it and evidence is sufficient, yet the target refuses",
                    )
                )
            if not provided and evidence_sufficient is not False:
                findings.append(
                    _review(
                        "absence_unexplained",
                        "refusal target has no context, yet evidence_sufficient is not false",
                    )
                )
            elif not provided and isinstance(absence, dict):
                notes.append("intentional_absence")
            if evidence_sufficient is False and facts:
                notes.append("book_level_gold")
        else:
            if not _text(answer):
                findings.append(_fail("schema", "non-refusal target needs a non-empty answer"))
            if "answer" not in behaviors:
                findings.append(_fail("behavior_target_conflict", "answer target without 'answer' allowed"))
            citations = target.get("citations", [])
            if not isinstance(citations, list):
                findings.append(_fail("schema", "target.citations must be a list"))
                citations = []
            provided_chunks = {
                source["chunk_id"]
                for source_id, source in resolved.items()
                if source_id in provided and source.get("chunk_id")
            }
            for citation in citations:
                key = _citation_key(citation)
                if key not in provided and key not in provided_chunks:
                    findings.append(
                        _fail("citation_not_provided", f"citation {key!r} is not in provided_source_ids")
                    )
            if kind == "answer" and not citations:
                findings.append(
                    _review("uncited_answer_target", "answer target carries no citation")
                )

    findings.extend(_check_target_quotes(target, resolved, provided))

    # -- exposure classification (support vs context only) --------------
    support = {
        sid
        for fact in facts
        if isinstance(fact, dict) and isinstance(fact.get("source_ids"), list)
        for sid in fact["source_ids"]
    }
    support.update(
        source_id for source_id, source in resolved.items() if source.get("role") == "support"
    )
    if target:
        citations = target.get("citations") or []
        for citation in citations if isinstance(citations, list) else []:
            key = _citation_key(citation)
            if key in resolved:
                support.add(key)
            else:
                support.update(
                    source_id
                    for source_id, source in resolved.items()
                    if source.get("chunk_id") == key
                )
    context = set(provided) | {
        source_id for source_id, source in resolved.items() if source.get("role") in CONTEXT_ROLES
    }
    context -= support
    meta["support"] = [resolved[sid] for sid in support if sid in resolved]
    meta["context"] = [resolved[sid] for sid in context if sid in resolved]

    paraphrase = metadata.get("paraphrase_of")
    if paraphrase is not None:
        values = [paraphrase] if isinstance(paraphrase, str) else paraphrase
        if not isinstance(values, list) or any(not _text(value) for value in values):
            findings.append(_fail("schema", "metadata.paraphrase_of must be an id or a list of ids"))
        else:
            meta["paraphrase_of"] = values

    result["verdict"] = _verdict(findings)
    return result, meta


def _attach(result, finding):
    result["findings"].append(finding)
    result["verdict"] = _verdict(result["findings"])


def _cross_split(dataset_pairs, corpus_metas):
    """Cross-record rules. Dataset records get findings; corpus rows are exposure."""
    corpus_pairs = [(None, meta) for meta in corpus_metas]
    everything = dataset_pairs + corpus_pairs

    train_families = {meta["family_id"] for _, meta in everything if meta["split"] == "train" and meta["family_id"]}
    train_components = set()
    train_texts = set()
    train_context = set()
    for _, meta in everything:
        if meta["split"] != "train":
            continue
        train_components.update(support["component"] for support in meta["support"])
        train_texts.update(support["text_key"] for support in meta["support"])
        train_context.update(item["component"] for item in meta["context"])

    context_overlaps = 0
    for result, meta in dataset_pairs:
        if not result:
            continue
        if meta["split"] in EVAL_SPLITS:
            if meta["family_id"] and meta["family_id"] in train_families:
                _attach(
                    result,
                    _fail("family_split_leak", f"family {meta['family_id']!r} also appears in train"),
                )
            leaked = {support["component"] for support in meta["support"]} & train_components
            if leaked:
                _attach(
                    result,
                    _fail("source_component_split_leak", f"support chunk(s) {sorted(leaked)} also in train"),
                )
            leaked_text = {support["text_key"] for support in meta["support"]} & train_texts
            if leaked_text:
                _attach(
                    result,
                    _fail("source_text_split_leak", "support text also appears in train under another index"),
                )
        if meta["split"] in EVAL_SPLITS:
            seen = {
                item["component"] for item in meta["support"] + meta["context"]
            } & train_context
            context_overlaps += len(seen)

    by_id = {}
    for result, meta in everything:
        if meta["id"]:
            by_id.setdefault(meta["id"], []).append((result, meta))
    for record_id, rows in by_id.items():
        if len(rows) > 1:
            ids = [meta["id"] for _, meta in rows]
            for result, _ in rows:
                if result:
                    _attach(result, _fail("duplicate_id", f"id {record_id!r} appears {len(ids)} times"))

    for result, meta in dataset_pairs:
        if not result or not meta["paraphrase_of"]:
            continue
        for other_id in meta["paraphrase_of"]:
            other = by_id.get(other_id)
            if not other:
                _attach(result, _review("paraphrase_unresolved", f"paraphrase_of {other_id!r} is not in the run"))
                continue
            other_split = other[0][1]["split"]
            if meta["split"] != other_split and "train" in (meta["split"], other_split):
                _attach(
                    result,
                    _fail("paraphrase_split_leak", f"declared paraphrase {other_id!r} is in {other_split}"),
                )

    duplicates = {"question_repeats": 0, "variants": 0, "full_input_duplicates": 0}
    variant_metas, duplicate_metas = set(), set()

    question_groups = {}
    for result, meta in dataset_pairs:
        if meta["question"]:
            question_groups.setdefault(meta["question"], []).append((result, meta))
    for rows in question_groups.values():
        if len(rows) < 2:
            continue
        # Repeats are an information count, not a verdict: different history,
        # book, or provided sources make two rows independent inputs.
        duplicates["question_repeats"] += len(rows) - 1
        for index in range(1, len(rows)):
            if any(_linked(rows[index][1], rows[earlier][1]) for earlier in range(index)):
                variant_metas.add(id(rows[index][1]))

    input_groups = {}
    for result, meta in everything:
        if meta.get("input_key") and meta["input_key"][0]:
            input_groups.setdefault(meta["input_key"], []).append((result, meta))
    for rows in input_groups.values():
        if len(rows) < 2:
            continue
        for index in range(1, len(rows)):
            result, meta = rows[index]
            earlier = [row[1] for row in rows[:index]]
            if any(_linked(meta, other) for other in earlier):
                if result:
                    variant_metas.add(id(meta))
                continue
            if not result:
                continue
            duplicate_metas.add(id(meta))
            splits = {meta["split"]} | {other["split"] for other in earlier}
            across = "train" in splits and bool(splits & set(EVAL_SPLITS))
            code = "duplicate_full_input_across_splits" if across else "duplicate_full_input"
            _attach(
                result,
                _review(
                    code,
                    "same question, history, provided source content, and prompt family as "
                    f"{[other['id'] for other in earlier]}; dedupe or declare a weight policy",
                ),
            )

    duplicates["variants"] = len(variant_metas)
    duplicates["full_input_duplicates"] = len(duplicate_metas)
    return context_overlaps, duplicates


def _read_corpus(path):
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if not resolved.is_file():
        return None, [_fail("train_corpus_missing", f"training corpus not readable: {resolved}", "lineage")]
    raw = resolved.read_bytes()
    records, legacy, unreadable = [], 0, 0
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            unreadable += 1
            continue
        if isinstance(row, dict) and row.get("schema_version") == 1:
            records.append(row)
        else:
            legacy += 1
    corpus = {
        "path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "records": records,
        "rows_without_provenance": legacy,
        "unreadable": unreadable,
    }
    findings = []
    if not records and not legacy and not unreadable:
        findings.append(_review("train_corpus_empty", f"{resolved} has no rows", "lineage"))
    if legacy or unreadable:
        findings.append(
            _review(
                "train_provenance_missing",
                f"{legacy + unreadable} corpus row(s) carry no canonical source provenance",
                "lineage",
            )
        )
    return corpus, findings


def _corpus_meta(record):
    """Minimal exposure view of a corpus row; corpus rows are train by definition."""
    refs = record.get("source_refs") if isinstance(record, dict) else []
    refs_by_id = {
        ref.get("source_id"): ref
        for ref in refs if isinstance(ref, dict) and _text(ref.get("source_id"))
    } if isinstance(refs, list) else {}
    question_key, input_key = _input_identity(record, refs_by_id)
    support, context = [], []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict):
            continue
        if ref.get("role") in CONTEXT_ROLES:
            context.append(_exposure(ref))
        else:
            support.append(_exposure(ref))
    facts = (record.get("expected") or {}).get("required_facts") if isinstance(record.get("expected"), dict) else []
    witness = {
        sid
        for fact in facts or []
        if isinstance(fact, dict) and isinstance(fact.get("source_ids"), list)
        for sid in fact["source_ids"]
    }
    meta = {
        "id": record.get("id") if _text(record.get("id")) else None,
        "family_id": record.get("family_id") if _text(record.get("family_id")) else None,
        "split": "train",
        "question": question_key,
        "input_key": input_key,
        "support": [item for item in support if item["id"] in witness] or support,
        "context": context,
        "paraphrase_of": [],
        "review": {},
    }
    return meta


def _exposure(ref):
    kind = ref.get("kind", "chunk")
    component = (
        f"caption:{ref.get('figure_id')}"
        if kind == "caption"
        else f"chunk:{ref.get('chunk_id')}"
    )
    return {
        "id": ref.get("source_id"),
        "book_id": ref.get("book_id"),
        "component": (ref.get("book_id"), ref.get("index_sha256"), component),
        "text_key": (ref.get("book_id"), ref.get("text_sha256")),
    }


def _summarize(results):
    counts = {"records": len(results), "pass": 0, "fail": 0, "review": 0, "unreadable": 0}
    for result in results:
        counts[result["verdict"].lower()] += 1
        if result.get("unreadable"):
            counts["unreadable"] += 1
    return counts


def _dataset_summary(path, results):
    return {"path": path, **_summarize(results)}


def _review_summary(results):
    accepted = [result for result in results if result.get("review", {}).get("status") == "accepted"]
    reviewers = {result["review"]["reviewer"] for result in accepted if result.get("review", {}).get("reviewer")}
    return {
        "accepted": len(accepted),
        "agent": sum(1 for result in accepted if result["review"].get("provenance") == "agent"),
        "owner": sum(1 for result in accepted if result["review"].get("provenance") == "owner"),
        "distinct_reviewers": len(reviewers),
        "records_with_required_facts": sum(1 for result in results if result.get("review", {}).get("facts")),
        "facts_attested": sum(result.get("review", {}).get("facts", 0) for result in results),
        "criteria_versions": sorted(
            {
                result["review"]["criteria_version"]
                for result in accepted
                if result["review"].get("criteria_version")
            }
        ),
    }


def _integrity(findings, results):
    relevant = list(findings) + [finding for result in results for finding in result["findings"]]
    relevant = [
        finding
        for finding in relevant
        if finding.get("scope") != "lineage" and finding["code"] not in LINEAGE_CODES
    ]
    return _verdict(relevant)


def _lineage_verdict(status, findings, results):
    lineage_findings = [finding for finding in findings if finding.get("scope") == "lineage"]
    base = _verdict(lineage_findings)
    record_findings = [
        finding for result in results for finding in result["findings"] if finding["code"] in LINEAGE_CODES
    ]
    verdict = max([base] + [finding["verdict"] for finding in record_findings], key=RANK.get)
    if verdict == "PASS" and status != "checked":
        return "REVIEW"
    return verdict


def _build(entries, unreadable, corpus, corpus_findings, dataset_paths, extra_findings, verify_origins=False):
    indexes = _Indexes()
    results, pairs = [], []
    for record, dataset, line, verify in entries:
        result, meta = _check_record(record, indexes, verify, dataset)
        result["dataset"] = dataset
        result["line"] = line
        results.append(result)
        pairs.append((result, meta))
    for dataset, line, error in unreadable:
        results.append(
            {
                "id": None,
                "dataset": dataset,
                "line": line,
                "split": None,
                "family_id": None,
                "book_id": None,
                "verdict": "FAIL",
                "findings": [_fail("unreadable_record", f"line {line}: {error}")],
                "notes": [],
                "review": {},
                "unreadable": True,
            }
        )
    order = {path: index for index, path in enumerate(dataset_paths)}
    results.sort(key=lambda result: (order.get(result["dataset"], len(order)), result["line"] or 0))
    pairs.sort(key=lambda pair: (order.get(pair[0]["dataset"], len(order)), pair[0]["line"] or 0))

    corpus_metas = [_corpus_meta(record) for record in corpus["records"]] if corpus else []
    context_overlaps, duplicates = _cross_split(pairs, corpus_metas)

    if corpus is None:
        status, provenance = "unknown", "unknown"
        extra_findings = extra_findings + [
            _review(
                "train_corpus_absent",
                "no --train-corpus: disjointness from any training corpus is unknown; "
                "supply the full candidate corpus to check it",
                "lineage",
            )
        ]
    else:
        tainted = bool(corpus["rows_without_provenance"] or corpus["unreadable"])
        if not tainted:
            provenance = "canonical"
        elif corpus["records"]:
            provenance = "partial"
        else:
            provenance = "unknown"
        status = ("checked" if provenance == "canonical" else "partial") if corpus["records"] else "unknown"

    findings = list(extra_findings) + list(corpus_findings)
    synthetic = sum(1 for result in results if "synthetic_source" in result["notes"])
    exposure = {"support": 0, "context_only": 0, "unexposed": 0}
    for _, meta in pairs:
        exposure["support"] += len(meta["support"])
        exposure["context_only"] += len(meta["context"])
    declarations = sum(
        len(record.get("source_refs") or []) for record, _, _, _ in entries if isinstance(record, dict)
    )
    exposure["unexposed"] = max(0, declarations - exposure["support"] - exposure["context_only"])

    report = {
        "validator": dict(VALIDATOR),
        "verdict": "PASS",
        "scope": "check",
        "origin_verification": "checked" if verify_origins else "not_checked",
        "counts": _summarize(results),
        "integrity": {
            "verdict": _integrity(findings, results),
            "origin_verification": "checked" if verify_origins else "not_checked",
        },
        "lineage": {
            "verdict": "PASS",
            "status": status,
            "provenance": provenance,
            "train_corpus": corpus["path"] if corpus else None,
            "train_records": len(corpus["records"]) if corpus else 0,
            "train_rows_without_provenance": corpus["rows_without_provenance"] if corpus else 0,
            "basis": "supplied corpus only; earlier corpora are not implied",
            "context_only_overlaps": context_overlaps,
            "exposure": exposure,
        },
        "review": _review_summary(results),
        "duplicates": {},
        "synthetic_records": synthetic,
        "datasets": [
            _dataset_summary(
                path, [result for result in results if result["dataset"] == path]
            )
            for path in dataset_paths
        ],
        "findings": findings,
        "records": results,
    }
    with_input = sum(
        1 for _, meta in pairs if meta.get("input_key") and meta["input_key"][0]
    )
    duplicates["independent_records"] = max(
        0, with_input - duplicates["variants"] - duplicates["full_input_duplicates"]
    )
    report["duplicates"] = duplicates
    report["lineage"]["verdict"] = _lineage_verdict(status, findings, results)
    report["verdict"] = max(
        [report["integrity"]["verdict"], report["lineage"]["verdict"]], key=RANK.get
    )
    return report


def check_records(records, *, name="<memory>", train_corpus=None, verify_origins=False):
    """Check a list of parsed records. Returns the JSON report as a dict."""
    entries = [(record, name, index, verify_origins) for index, record in enumerate(records, 1)]
    corpus, corpus_findings = _read_corpus(train_corpus) if train_corpus else (None, [])
    return _build(
        entries, [], corpus, corpus_findings, [name], [], verify_origins=verify_origins
    )


def _read_dataset(path):
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = ROOT / resolved
    if not resolved.is_file():
        return None, str(resolved), _fail("dataset_missing", f"dataset not readable: {resolved}")
    raw = resolved.read_bytes()
    rows = []
    for line, text in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        if not text.strip():
            continue
        try:
            rows.append((json.loads(text), line, None))
        except ValueError as exc:
            rows.append((None, line, str(exc)))
    return {"path": str(resolved), "sha256": hashlib.sha256(raw).hexdigest(), "rows": rows}, None, None


def check_datasets(paths, *, train_corpus=None, verify_origins=False):
    """Check one or more JSONL dataset files as one run (lineage spans files)."""
    entries, unreadable, findings, dataset_paths = [], [], [], []
    missing = {}
    for path in paths:
        loaded, resolved_path, error = _read_dataset(path)
        if loaded is None:
            findings.append(error)
            dataset_paths.append(resolved_path)
            missing[resolved_path] = error["detail"]
            continue
        dataset_paths.append(loaded["path"])
        for record, line, parse_error in loaded["rows"]:
            if record is None:
                unreadable.append((loaded["path"], line, parse_error))
            else:
                entries.append((record, loaded["path"], line, verify_origins))
    corpus, corpus_findings = _read_corpus(train_corpus) if train_corpus else (None, [])
    report = _build(
        entries,
        unreadable,
        corpus,
        corpus_findings,
        dataset_paths,
        findings,
        verify_origins=verify_origins,
    )
    for item in report["datasets"]:
        if item["path"] in missing:
            item["error"] = missing[item["path"]]
    return report



def main(argv=None):
    parser = argparse.ArgumentParser(description="Check dataset readiness; JSON on stdout.")
    parser.add_argument("--dataset", action="append", default=[], help="JSONL dataset (repeatable)")
    parser.add_argument("--train-corpus", default=None, help="canonical training corpus JSONL")
    parser.add_argument("--verify-origins", action="store_true", help="hash origin.path files")
    parser.add_argument(
        "--release",
        action="store_true",
        help="acceptance wrapper: requires --verify-origins and marks the report scope",
    )
    args = parser.parse_args(argv)

    if not args.dataset:
        report = {
            "validator": dict(VALIDATOR),
            "verdict": "FAIL",
            "scope": "release" if args.release else "check",
            "origin_verification": "checked" if args.verify_origins else "not_checked",
            "counts": {"records": 0, "pass": 0, "fail": 0, "review": 0, "unreadable": 0},
            "integrity": {"verdict": "FAIL"},
            "lineage": {
                "verdict": "REVIEW",
                "status": "unknown",
                "provenance": "unknown",
                "train_corpus": args.train_corpus,
                "train_records": 0,
                "train_rows_without_provenance": 0,
                "basis": "supplied corpus only; earlier corpora are not implied",
                "context_only_overlaps": 0,
                "exposure": {"support": 0, "context_only": 0, "unexposed": 0},
            },
            "review": _review_summary([]),
            "synthetic_records": 0,
            "datasets": [],
            "findings": [_fail("dataset_missing", "--dataset is required")],
            "records": [],
        }
    else:
        report = check_datasets(
            args.dataset,
            train_corpus=args.train_corpus,
            verify_origins=args.verify_origins,
        )
        report["scope"] = "release" if args.release else "check"
        if args.release and not args.verify_origins:
            report["findings"].append(
                _fail(
                    "release_requires_origin_verification",
                    "--release requires --verify-origins: an acceptance run cannot claim "
                    "origin bytes it never hashed",
                )
            )
            report["integrity"]["verdict"] = _integrity(
                report["findings"], report["records"]
            )
            report["lineage"]["verdict"] = _lineage_verdict(
                report["lineage"]["status"], report["findings"], report["records"]
            )
            report["verdict"] = max(
                [report["integrity"]["verdict"], report["lineage"]["verdict"]], key=RANK.get
            )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return EXIT[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
