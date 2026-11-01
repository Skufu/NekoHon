"""Offline audit of the recovered fine-tune corpora: ledger, split manifest, review queue.

What this is
------------
An adapter from the two shapes that actually exist on disk:

* the shipped message rows (``messages`` + ``meta``), where passages are embedded
  in the user message as ``[Ch. N] chunk_id=...`` blocks;
* the canonical schema-v1 records (``source_refs`` + ``expected`` + ``review``).

It produces one ledger entry per row, a split/exposure manifest, and a review
queue. It never trains, never calls a model, an embedder, a judge, or the
network, and never rewrites an input file.

What it can prove, and what it cannot
-------------------------------------
Mechanical: a target quote is literal in the passage block the model was shown,
or it is only a normalized match, or it is absent; a source ref hash and span
match the current index; a refusal is exactly ``Not in this book.``. Those are
checks on bytes.

Not mechanical: whether a gloss is true, whether a refusal should have been an
answer, or whether a paraphrase still means the same thing. Every row is marked
``semantic_status = REVIEW_NOT_CERTIFIED`` and every gloss, refusal, required
fact, and answer-fit clause is put in the review queue. A green mechanical
result is not a semantic certificate.

Book identity is resolved by the passage text plus the declared path/id, never
by assuming every ``ch01-*`` id belongs to FDE. A synthetic domain is only
synthetic when the record declares one; a missing chunk is unresolved, not
invented.

CLI::

    python artifacts/harnesses/training_audit.py \\
        --input data/finetune/X.jsonl [--role X.jsonl=historical_train] \\
        --dataset artifacts/.../candidate.jsonl [--role ...=dev] \\
        [--index data/index.sqlite ...] [--catalog data/books.json] [--out DIR]

Stdlib only. Exit 0 mechanically clean, 1 review, 2 fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import store  # noqa: E402

SCHEMA_VERSION = 1
REFUSAL = "Not in this book."
QUOTE_LINE = re.compile(r'^\[Ch\.\s*([^\]]+)\]\s*["\u201c](.*)["\u201d]\s*$')
PASSAGE_HEAD = re.compile(r"\[Ch\.\s*([^\]]+)\]\s+chunk_id=(\S+)\n")
HISTORY_HEAD = re.compile(
    r"^Earlier in this conversation \(not a source\s*[\u2014-]\s*do not quote it\):\n(.*?)\n\nQuestion:",
    re.M | re.S,
)
HISTORY_QUOTE = re.compile(r'\[Ch\.\s*([^\]]+)\]\s*["\u201c](.*)["\u201d]')
TYPO = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u00a0": " ",
}
STOPWORDS = set(
    """a an the is are was were be been being of to in on for and or but if then
    than that this these those it its as at by from with without into over under
    about what which who whom whose how why when where does do did can could
    should would will may might must not no yes there their they them he she his
    her we our you your i me my mine also more most less least other others such
    same very just only own each any all both few many much some""".split()
)
PROMPT_SUFFIXES = (
    "\n\nExplain in 1 to 2 plain, direct sentences what the selected text means and why it is discussed here.",
    "\n\nWrite a direct 1 to 2 sentence answer that explicitly answers the follow-up question and connects it to the previous turn. Ground strictly in the passage context.",
)

PROTECTED_DEFAULT = (
    {
        "name": "sealed-2026-10-24.jsonl",
        "sha256": "24fcc1c9138e158d26891a88bb07d5ef1e9eeb21bcbe137aa40d00961404d0d7",
        "opened": False,
        "scope": "sealed evaluation set; text never read by this audit",
    },
    {
        "name": "reserved_10",
        "sha256": None,
        "opened": False,
        "scope": "reserved cases named in reports; location and text not opened",
    },
    {
        "name": "fair-locked / fair-dev",
        "sha256": None,
        "opened": False,
        "scope": "fair evaluation surfaces; not opened or trained",
    },
)
EXIT = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
RANK = {"PASS": 0, "INFO": 0, "REVIEW": 1, "FAIL": 2}


def _sha_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _question_key(question):
    return " ".join((question or "").lower().split()).rstrip("?.! ").strip()


def _ws(text):
    return " ".join((text or "").split())


def fold(text):
    text = unicodedata.normalize("NFKC", text or "")
    for before, after in TYPO.items():
        text = text.replace(before, after)
    return _ws(text)


def _casefold(text):
    return fold(text).lower()


def _tokens(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _issue(code, severity, detail, scope="integrity"):
    return {"code": code, "severity": severity, "detail": detail, "scope": scope}


def _worst(issues):
    status = "PASS"
    for issue in issues:
        if RANK.get(issue["severity"], 0) > RANK[status]:
            status = issue["severity"]
    return status


def _chapter_label(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"^chapter[\s._-]*", "", text)
    return text.strip(" .")


def _chapter_equivalent(tag, chapter):
    left, right = _chapter_label(tag), _chapter_label(chapter)
    if not left or not right:
        return False
    if left == right:
        return True
    if left.isdigit() and right.isdigit():
        return int(left) == int(right)
    if left.startswith("app") and right.startswith("app"):
        return True
    if left.startswith("preface") and right.startswith("preface"):
        return True
    return False


def _read_jsonl(path):
    data = Path(path).read_bytes()
    raw_lines = data.split(b"\n")
    if raw_lines and raw_lines[-1] == b"":
        raw_lines.pop()
    rows = []
    crlf = lf = 0
    for number, raw in enumerate(raw_lines, 1):
        had_cr = raw.endswith(b"\r")
        clean = raw[:-1] if had_cr else raw
        if had_cr:
            crlf += 1
        else:
            lf += 1
        text = clean.decode("utf-8")
        rows.append(
            {
                "line": number,
                "raw": raw,
                "clean": clean,
                "text": text,
                "raw_line_sha256": _sha_bytes(clean),
            }
        )
    info = {
        "path": str(Path(path)),
        "bytes": len(data),
        "sha256": _sha_bytes(data),
        "lf_sha256": _sha_bytes(data),
        "crlf_rejoined_sha256": _sha_bytes(b"\r\n".join(row["clean"] for row in rows) + b"\r\n")
        if rows
        else _sha_bytes(b""),
        "rows": len(rows),
        "line_endings": {"lf": lf, "crlf": crlf},
    }
    return rows, info


class BookSet:
    """Indexes loaded from disk; no retrieval, no embeddings used."""

    def __init__(self):
        self.books = {}
        self.by_path = {}
        self.by_text = defaultdict(list)
        self.by_casefold = defaultdict(list)
        self.by_id = defaultdict(list)
        self.figures = defaultdict(list)

    def add(self, path):
        path = Path(path)
        if store.is_index_db(path):
            data = store.read_index(path)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
        book_id = data.get("book_id") or path.stem
        book = {
            "book_id": book_id,
            "path": str(path),
            "sha256": _sha_bytes(path.read_bytes()),
            "chunks": {},
            "chapters": {},
        }
        for chunk in data.get("chunks", []):
            chunk_id = chunk.get("chunk_id")
            if not chunk_id:
                continue
            book["chunks"][chunk_id] = chunk
            book["chapters"][chunk_id] = str(chunk.get("chapter") or "")
            text = chunk.get("text") or ""
            entry = (book_id, chunk)
            self.by_text[_sha_text(text)].append(entry)
            self.by_casefold[_casefold(text)].append(entry)
            self.by_id[chunk_id].append(entry)
        for figure in data.get("figures", []):
            figure_id = figure.get("figure_id") or figure.get("id")
            if not figure_id:
                continue
            caption = figure.get("caption") or ""
            self.figures[(book_id, figure_id)].append(figure)
            if caption:
                self.by_text[_sha_text(caption)].append((book_id, {"chunk_id": figure_id, "text": caption, "chapter": "", "kind": "caption"}))
                self.by_casefold[_casefold(caption)].append(
                    (book_id, {"chunk_id": figure_id, "text": caption, "chapter": "", "kind": "caption"})
                )
        self.books[book_id] = book
        self.by_path[str(path.resolve())] = book
        return book

    def by_book(self, book_id):
        return self.books.get(book_id)

    def book_for_path(self, index_path):
        if not index_path:
            return None
        candidate = Path(index_path)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return self.by_path.get(str(candidate.resolve()))


def load_books(index_paths=None, catalog_path=None):
    books = BookSet()
    paths = list(index_paths or [])
    if not paths and catalog_path:
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        paths = [item["index_path"] for item in catalog if item.get("index_path")]
    for path in paths:
        if Path(path).is_file():
            books.add(path)
    return books


def _resolve_block(text, chunk_id, domain, books):
    """Resolve one provided passage block to current index truth.

    ``verbatim`` is exact bytes. ``normalized_only`` is equal only after
    NFKC/typography/whitespace/case folding. ``formatting_drift`` is the same
    chunk id with an equal token sequence but different table/CR whitespace.
    ``id_text_conflict`` is a declared chunk id whose text is not that chunk.
    """
    exact = books.by_text.get(_sha_text(text), [])
    if exact:
        if len(exact) == 1:
            book_id, chunk = exact[0]
            return _binding(book_id, chunk, "verbatim", chunk_id, text)
        narrowed = [(book_id, chunk) for book_id, chunk in exact if chunk.get("chunk_id") == chunk_id]
        if len(narrowed) == 1:
            book_id, chunk = narrowed[0]
            return _binding(book_id, chunk, "verbatim", chunk_id, text, shared_text=True)
        return _unresolved(text, chunk_id, domain, "text_matches_multiple_books")

    folded = books.by_casefold.get(_casefold(text), [])
    if folded:
        if len(folded) == 1:
            book_id, chunk = folded[0]
            return _binding(book_id, chunk, "normalized_only", chunk_id, text)
        narrowed = [(book_id, chunk) for book_id, chunk in folded if chunk.get("chunk_id") == chunk_id]
        if len(narrowed) == 1:
            book_id, chunk = narrowed[0]
            return _binding(book_id, chunk, "normalized_only", chunk_id, text, shared_text=True)
        return _unresolved(text, chunk_id, domain, "normalized_text_matches_multiple_books")

    by_id = books.by_id.get(chunk_id, [])
    if by_id:
        token_matches = [
            (book_id, chunk)
            for book_id, chunk in by_id
            if _tokens(text) == _tokens(chunk.get("text") or "")
        ]
        if len(token_matches) == 1:
            book_id, chunk = token_matches[0]
            return _binding(book_id, chunk, "formatting_drift", chunk_id, text)
        if len(token_matches) > 1:
            return _unresolved(text, chunk_id, domain, "formatting_drift_ambiguous_across_books")
        if len(by_id) == 1:
            book_id, chunk = by_id[0]
            return _binding(book_id, chunk, "id_text_conflict", chunk_id, text)
        return _unresolved(text, chunk_id, domain, "id_text_conflict_across_books")

    if domain:
        return {
            "resolution": "synthetic",
            "book_id": None,
            "index_path": None,
            "chunk_id": chunk_id,
            "chapter": "",
            "text_sha256": _sha_text(text),
            "text": text,
            "provided_text": text,
            "declared_chunk_id": chunk_id,
            "domain": domain,
            "key": f"synthetic:{domain}:{chunk_id}",
        }
    return _unresolved(text, chunk_id, domain, "no_text_or_id_match")


def _binding(book_id, chunk, resolution, declared_chunk_id, text, shared_text=False):
    chunk_text = chunk.get("text") or ""
    key = f"{book_id}:{chunk.get('chunk_id')}"
    return {
        "resolution": resolution,
        "book_id": book_id,
        "index_path": None,
        "chunk_id": chunk.get("chunk_id"),
        "chapter": str(chunk.get("chapter") or ""),
        "heading": chunk.get("heading") or "",
        "text_sha256": _sha_text(chunk_text),
        "text": chunk_text,
        "provided_text": text,
        "declared_chunk_id": declared_chunk_id,
        "shared_text_across_books": shared_text,
        "key": key,
    }


def _unresolved(text, chunk_id, domain, reason):
    return {
        "resolution": "unresolved",
        "book_id": None,
        "index_path": None,
        "chunk_id": chunk_id,
        "chapter": "",
        "text_sha256": _sha_text(text),
        "text": text,
        "provided_text": text,
        "declared_chunk_id": chunk_id,
        "domain": domain,
        "reason": reason,
        "key": None,
    }


def _parse_history(user):
    match = HISTORY_HEAD.search(user)
    if not match:
        return {"text": "", "quotes": []}
    body = match.group(1)
    quotes = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("Book:"):
            continue
        for chapter, quote in HISTORY_QUOTE.findall(line[5:]):
            quotes.append({"chapter": chapter.strip(), "quote": quote})
    return {"text": body, "quotes": quotes}


def _strip_prompt_suffix(text):
    for suffix in PROMPT_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].rstrip("\n")
    return text


def _parse_blocks(user):
    marks = list(PASSAGE_HEAD.finditer(user))
    blocks = []
    for index, match in enumerate(marks):
        start = match.end()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(user)
        block = user[start:end]
        cut = block.find("\n\nCopy one sentence")
        if cut >= 0:
            block = block[:cut]
        blocks.append(
            {
                "chapter_tag": match.group(1).strip(),
                "chunk_id": match.group(2).strip(),
                "text": _strip_prompt_suffix(block.rstrip("\n")),
                "origin": "passage",
            }
        )
    return blocks


def _parse_block_offsets(user):
    marks = list(PASSAGE_HEAD.finditer(user))
    blocks = []
    for index, match in enumerate(marks):
        start = match.end()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(user)
        raw = user[start:end]
        cut = raw.find("\n\nCopy one sentence")
        if cut >= 0:
            raw = raw[:cut]
        text = _strip_prompt_suffix(raw.rstrip("\n"))
        blocks.append(
            {
                "chapter_tag": match.group(1).strip(),
                "chunk_id": match.group(2).strip(),
                "start": start,
                "end": start + len(text),
                "text": text,
            }
        )
    if blocks:
        return blocks
    context = re.search(r"\n\nPassage context:\n", user)
    if context:
        start = context.end()
        raw = user[start:]
        cut = raw.find("\n\nCopy one sentence")
        if cut >= 0:
            raw = raw[:cut]
        text = _strip_prompt_suffix(raw.rstrip("\n"))
        blocks.append(
            {
                "chapter_tag": "",
                "chunk_id": "",
                "start": start,
                "end": start + len(text),
                "text": text,
            }
        )
    return blocks


def _parse_highlight_context(user, meta):
    match = re.search(r"^Passage context:\n(.*)$", user, re.M | re.S)
    if not match:
        return []
    block = match.group(1)
    cut = block.find("\n\nCopy one sentence")
    if cut >= 0:
        block = block[:cut]
    return [
        {
            "chapter_tag": str(meta.get("chapter") or ""),
            "chunk_id": str(meta.get("chunk_id") or ""),
            "text": _strip_prompt_suffix(block.rstrip("\n")),
            "origin": "highlight_context",
        }
    ]


def _parse_question(user, meta):
    for line in user.splitlines():
        if line.startswith("Question: "):
            return line[len("Question: "):].strip()
        if line.startswith("Highlighted text: "):
            return line[len("Highlighted text: "):].strip()
    return str(meta.get("asked") or meta.get("question") or "").strip()


def _target_quotes(target):
    quotes = []
    for line in (target or "").splitlines():
        match = QUOTE_LINE.match(line.strip())
        if match:
            quotes.append({"chapter": match.group(1).strip(), "quote": match.group(2)})
    return quotes


def _match_status(quote, text):
    if not quote:
        return None
    if quote in text:
        return "literal"
    if _casefold(quote) in _casefold(text):
        return "normalized_only"
    if fold(quote) in fold(text):
        return "normalized_only"
    return None


def _search_books(quote, books):
    literal = []
    for book_id, book in books.books.items():
        for chunk_id, chunk in book["chunks"].items():
            if quote and quote in (chunk.get("text") or ""):
                literal.append((book_id, chunk_id))
    if literal:
        return "absent_provided_literal_in_book", literal
    normalized = []
    folded = _casefold(quote)
    for book_id, book in books.books.items():
        for chunk_id, chunk in book["chunks"].items():
            if folded and folded in _casefold(chunk.get("text") or ""):
                normalized.append((book_id, chunk_id))
    if normalized:
        return "absent_provided_normalized_in_book", normalized
    return "absent_book", []


def _sentence_clauses(text):
    clauses = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or QUOTE_LINE.match(line):
            continue
        clauses.append(line)
    return clauses


def _audit_original(record, books, file_ctx):
    messages = record.get("messages") or []
    meta = record.get("meta") or {}
    system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
    user = next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")
    target = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "assistant"), "")
    question = _parse_question(user, meta)
    history = _parse_history(user)
    blocks = _parse_blocks(user)
    if not blocks and "Highlighted text:" in user:
        blocks = _parse_highlight_context(user, meta)

    domain = str(meta.get("domain") or "").strip()
    bindings = []
    for block in blocks:
        binding = _resolve_block(block["text"], block["chunk_id"], domain, books)
        binding["chapter_tag"] = block["chapter_tag"]
        binding["origin"] = block["origin"]
        binding["provided_text_sha256"] = _sha_text(block["text"])
        bindings.append(binding)

    issues = []
    for binding in bindings:
        if binding["resolution"] == "unresolved":
            issues.append(_issue("source_unresolved", "REVIEW", f"{binding.get('chunk_id')}: {binding.get('reason')}", "source"))
        elif binding["resolution"] == "id_text_conflict":
            issues.append(_issue("source_id_text_conflict", "REVIEW", f"{binding.get('chunk_id')} text does not match the index", "source"))
        elif binding["resolution"] == "normalized_only":
            issues.append(_issue("source_normalized_only", "REVIEW", f"{binding.get('chunk_id')} matches only after normalization", "source"))
        elif binding["resolution"] == "formatting_drift":
            issues.append(_issue("source_formatting_drift", "REVIEW", f"{binding.get('chunk_id')} differs only in table/CR whitespace", "source"))
        elif binding.get("shared_text_across_books"):
            issues.append(_issue("source_shared_text_across_books", "INFO", f"{binding.get('chunk_id')} text exists in more than one book", "source"))

    quote_checks = []
    support_keys = set()
    support_text_keys = set()
    for quote in _target_quotes(target):
        check = {
            "chapter_tag": quote["chapter"],
            "quote": quote["quote"],
            "quote_sha256": _sha_text(quote["quote"]),
            "status": "absent_book",
            "block_index": None,
            "book_id": None,
            "chunk_id": None,
            "source_key": None,
        }
        matches = []
        for index, binding in enumerate(bindings):
            provided_text = binding.get("provided_text") or binding.get("text") or ""
            status = _match_status(quote["quote"], provided_text)
            if not status:
                continue
            matches.append(
                {
                    "block_index": index,
                    "status": status,
                    "book_id": binding.get("book_id"),
                    "chunk_id": binding.get("chunk_id"),
                    "source_key": binding.get("key"),
                    "resolution": binding["resolution"],
                }
            )
            if binding["resolution"] != "synthetic" and binding.get("chapter") and not _chapter_equivalent(quote["chapter"], binding.get("chapter")):
                issues.append(
                    _issue("chapter_tag_mismatch", "REVIEW", f"tag {quote['chapter']!r} != chapter {binding.get('chapter')!r}", "quote")
                )
            if status == "normalized_only":
                issues.append(
                    _issue("target_quote_normalized_only", "REVIEW", f"quote {quote['quote'][:60]!r} is not byte-literal", "quote")
                )
            if binding.get("key"):
                support_keys.add(binding["key"])
                support_text_keys.add((binding.get("book_id"), binding.get("text_sha256")))
        if matches:
            first = matches[0]
            check.update(
                {
                    "status": first["status"],
                    "block_index": first["block_index"],
                    "book_id": first["book_id"],
                    "chunk_id": first["chunk_id"],
                    "source_key": first["source_key"],
                    "resolution": first["resolution"],
                    "source_keys": [match["source_key"] for match in matches if match["source_key"]],
                    "block_indexes": [match["block_index"] for match in matches],
                }
            )
        if check["block_index"] is None:
            global_status, hits = _search_books(quote["quote"], books)
            check["status"] = global_status
            check["global_hits"] = [f"{book}:{chunk}" for book, chunk in hits[:8]]
            if global_status == "absent_provided_literal_in_book":
                issues.append(
                    _issue("target_quote_wrong_source", "FAIL", f"quote exists in the book but not in the provided passages", "quote")
                )
            elif global_status == "absent_provided_normalized_in_book":
                issues.append(
                    _issue("target_quote_wrong_source_normalized", "FAIL", f"quote exists only normalized outside provided passages", "quote")
                )
            else:
                issues.append(
                    _issue("target_quote_not_in_book", "FAIL", f"quote {quote['quote'][:60]!r} is not in the provided passages or the books", "quote")
                )
        quote_checks.append(check)

    target_text = (target or "").strip()
    refusal_exact = target_text == REFUSAL
    is_gloss = bool(meta.get("row_type") == "explain_gloss" or "Highlighted text:" in user or "clear, insightful book companion" in system)
    refusal_check = None
    if target_text.startswith(REFUSAL) and not refusal_exact:
        issues.append(_issue("refusal_with_commentary", "FAIL", "refusal line is not exactly 'Not in this book.'", "target"))
    elif not refusal_exact and not quote_checks and not is_gloss:
        issues.append(_issue("answer_without_quote", "REVIEW", "answer target carries no [Ch.] quote and is not an explain gloss", "target"))

    if refusal_exact:
        terms = {word for word in re.findall(r"[a-z0-9]+", question.lower()) if word not in STOPWORDS and len(word) > 1}
        supplied = " ".join(binding["text"] for binding in bindings).lower()
        present = {word for word in terms if re.search(r"\b" + re.escape(word) + r"\b", supplied)}
        if not bindings:
            classification = "no_supplied_context"
            junk = False
            issues.append(_issue("refusal_evidence_withheld", "INFO", "refusal item supplies no passage; intentional absence is a legitimate label", "refusal"))
        elif not terms:
            classification = "no_question_terms"
            junk = False
        elif not present:
            classification = "terms_absent_from_supplied_context"
            junk = False
            issues.append(_issue("refusal_evidence_withheld", "INFO", "no question content term appears in the supplied passages; the refusal is correct with respect to the evidence shown, not junk", "refusal"))
        else:
            classification = "terms_present_in_supplied_context"
            junk = False
            issues.append(_issue("refusal_with_context_terms", "REVIEW", "some question terms appear in the supplied passages; answerability is semantic", "refusal"))
        refusal_check = {
            "classification": classification,
            "junk": junk,
            "question_terms": sorted(terms),
            "terms_present": sorted(present),
            "supplied_passages": len(bindings),
            "semantic_answerability": "REVIEW_NOT_CERTIFIED",
        }

    # A quote-free explain gloss legitimately has no quote; bind its declared anchor chunk.
    gloss_anchor = None
    if is_gloss and not quote_checks:
        anchor = str(meta.get("chunk_id") or "")
        for binding in bindings:
            if binding.get("chunk_id") == anchor and binding.get("key"):
                gloss_anchor = binding["key"]
                support_keys.add(binding["key"])
                support_text_keys.add((binding.get("book_id"), binding.get("text_sha256")))
                break
        issues.append(_issue("quote_free_gloss", "INFO", "explain gloss legitimately carries no quote; anchor chunk is declared, gloss text is semantic", "target"))

    context_keys = {
        binding["key"]
        for binding in bindings
        if binding.get("key") and binding["key"] not in support_keys
    }

    history_quotes = []
    history_keys = set()
    for quote in history["quotes"]:
        status, hits = _search_books(quote["quote"], books)
        if status == "absent_provided_literal_in_book":
            history_keys.add(f"{hits[0][0]}:{hits[0][1]}")
            history_quotes.append({"chapter": quote["chapter"], "quote": quote["quote"], "status": "literal_in_book", "book_id": hits[0][0], "chunk_id": hits[0][1]})
        elif status == "absent_provided_normalized_in_book":
            history_keys.add(f"{hits[0][0]}:{hits[0][1]}")
            history_quotes.append({"chapter": quote["chapter"], "quote": quote["quote"], "status": "normalized_in_book", "book_id": hits[0][0], "chunk_id": hits[0][1]})
        else:
            history_quotes.append({"chapter": quote["chapter"], "quote": quote["quote"], "status": "not_verbatim_in_book", "book_id": None, "chunk_id": None})
            issues.append(_issue("history_quote_not_verbatim", "INFO", "teacher-paraphrased history is not a new source and is not treated as one", "history"))

    review_clauses = []
    for check in quote_checks:
        if check["status"] == "literal" and not any(
            issue["code"] in ("chapter_tag_mismatch", "source_formatting_drift", "source_normalized_only") for issue in issues
        ):
            review_clauses.append({"kind": "quote", "text": check["quote"], "status": "MECHANICAL_PASS", "reason": "literal in the provided passage"})
        else:
            review_clauses.append({"kind": "quote", "text": check["quote"], "status": "REVIEW", "reason": f"quote status {check['status']}; chapter/source needs review"})
    if not is_gloss:
        for line in _sentence_clauses(target):
            review_clauses.append({"kind": "gloss", "text": line, "status": "REVIEW", "reason": "free gloss; semantic claim not mechanically provable"})
    if refusal_exact:
        review_clauses.append({"kind": "refusal", "text": REFUSAL, "status": "REVIEW", "reason": "semantic answerability of the supplied evidence; no model or judge called"})
    if not review_clauses or (quote_checks and not is_gloss):
        review_clauses.append({"kind": "answer_fit", "text": "", "status": "REVIEW", "reason": "whether the target answers the question is semantic, not a byte check"})

    line = file_ctx["line"] if file_ctx else None
    path = file_ctx["path"] if file_ctx else "<memory>"
    prefix = (file_ctx or {}).get("id_prefix")
    stable_id = f"{prefix}-line-{line:04d}" if prefix and line else f"{Path(path).name}:{line}"
    boundary = (file_ctx or {}).get("shard_boundary")
    task_kind = "refusal" if refusal_exact else ("explain_gloss" if is_gloss and not quote_checks else "answer_quote")
    source_scope = sorted(
        {
            binding.get("book_id") or f"synthetic:{binding.get('domain')}"
            for binding in bindings
            if binding.get("book_id") or binding.get("domain")
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "id": stable_id,
        "format": "messages",
        "source_path": path,
        "line": line,
        "raw_line_sha256": file_ctx["raw_line_sha256"] if file_ctx else None,
        "origin": {
            "path": path,
            "sha256": (file_ctx or {}).get("file_sha256"),
            "record": str(line) if line is not None else None,
            "record_ordinal": line,
            "line_sha256": file_ctx["raw_line_sha256"] if file_ctx else None,
            "line_sha256_with_lf": (file_ctx or {}).get("line_sha256_with_lf"),
        },
        "shard": ("A" if boundary and line and line <= boundary else ("B" if boundary and line else None)),
        "messages_sha256": _sha_text(_canonical_json(messages)),
        "user_prompt_sha256": _sha_text(user),
        "target_sha256": _sha_text(target),
        "review": {
            "status": "needs_review",
            "reviewer": None,
            "provenance": "agent",
            "criteria_version": "training-target-source-v1",
            "notes": "Mechanical audit only; target and gloss meaning require independent source review.",
        },
        "canonical_ready": False,
        "task_kind": task_kind,
        "source_scope": source_scope,
        "split": str(meta.get("split") or "unknown"),
        "family_id": f"question:{_question_key(question)}",
        "question": question,
        "declared_meta": {
            key: meta.get(key)
            for key in ("question", "asked", "source", "row_type", "tier", "pin", "cited", "domain", "part")
        },
        "target": {
            "kind": "refusal" if refusal_exact else ("gloss" if is_gloss and not quote_checks else "answer"),
            "refusal_exact": refusal_exact,
            "quote_free_gloss": bool(is_gloss and not quote_checks),
            "quote_count": len(quote_checks),
        },
        "quote_checks": quote_checks,
        "source_bindings": bindings,
        "support_keys": sorted(support_keys),
        "support_text_keys": sorted([list(item) for item in support_text_keys]),
        "context_keys": sorted(context_keys),
        "history_keys": sorted(history_keys),
        "history_quotes": history_quotes,
        "refusal_check": refusal_check,
        "issues": issues,
        "mechanical_status": _worst(issues),
        "semantic_status": "REVIEW_NOT_CERTIFIED",
        "train_ready": False,
        "review_clauses": review_clauses,
    }


def _resolve_ref(ref, books):
    kind = ref.get("kind") or "chunk"
    if kind == "synthetic":
        span_text = "\n".join(str(span.get("text") or "") for span in ref.get("spans") or [])
        return {
            "resolution": "synthetic",
            "key": f"synthetic:{ref.get('book_id')}:{ref.get('chunk_id')}",
            "text": ref.get("text") or span_text,
            "book_id": ref.get("book_id"),
            "chunk_id": ref.get("chunk_id"),
            "chapter": "",
        }
    book = books.by_book(ref.get("book_id")) or books.book_for_path(ref.get("index_path"))
    if not book:
        return {"resolution": "unknown_book", "key": None, "reason": "no index for declared book_id/index_path"}
    if kind == "caption":
        figure_id = ref.get("figure_id")
        figures = books.figures.get((book["book_id"], figure_id), [])
        if len(figures) != 1:
            return {"resolution": "missing_figure", "key": None, "reason": f"figure_id {figure_id!r} not unique or absent"}
        text = figures[0].get("caption") or ""
        chapter = ""
    else:
        chunk = book["chunks"].get(ref.get("chunk_id"))
        if not chunk:
            return {"resolution": "missing_chunk", "key": None, "reason": f"chunk_id {ref.get('chunk_id')!r} absent from {book['book_id']}"}
        text = chunk.get("text") or ""
        chapter = str(chunk.get("chapter") or "")
    return {
        "resolution": "verbatim",
        "key": f"{book['book_id']}:{ref.get('chunk_id')}",
        "text": text,
        "book_id": book["book_id"],
        "chunk_id": ref.get("chunk_id"),
        "chapter": chapter,
        "index_path": book["path"],
        "index_sha256": book["sha256"],
        "text_sha256": _sha_text(text),
    }


def _audit_canonical(record, books, file_ctx):
    issues = []
    record_id = str(record.get("id") or "")
    question = str(record.get("question") or "")
    split = str(record.get("split") or "unknown")
    target = record.get("target") or {}
    answer = str(target.get("answer") or "")
    expected = record.get("expected") or {}
    refs = record.get("source_refs") or []
    provided = list(record.get("provided_source_ids") or [])
    refs_by_id = {ref.get("source_id"): ref for ref in refs}
    for source_id in provided:
        if source_id not in refs_by_id:
            issues.append(_issue("provided_source_missing_ref", "FAIL", f"provided_source_ids names {source_id!r} with no source_ref", "source"))

    fact_ids = set()
    for fact in expected.get("required_facts") or []:
        for source_id in fact.get("source_ids") or []:
            fact_ids.add(source_id)
    citation_ids = set()
    for citation in target.get("citations") or []:
        if isinstance(citation, dict):
            citation_ids.add(citation.get("source_id"))
        elif isinstance(citation, str):
            citation_ids.add(citation)
    support_ids = fact_ids or citation_ids

    bindings = []
    support_keys = set()
    support_text_keys = set()
    for ref in refs:
        resolved = _resolve_ref(ref, books)
        binding = {
            "source_id": ref.get("source_id"),
            "role": "support" if ref.get("source_id") in support_ids else "context",
            "declared_role": ref.get("role"),
            "kind": ref.get("kind") or "chunk",
            "book_id": resolved.get("book_id") or ref.get("book_id"),
            "index_path": ref.get("index_path"),
            "chunk_id": ref.get("chunk_id"),
            "chapter": ref.get("chapter"),
            "resolution": resolved["resolution"],
            "key": resolved.get("key"),
            "text": resolved.get("text"),
            "text_sha256": ref.get("text_sha256"),
            "index_sha256": ref.get("index_sha256"),
            "spans": ref.get("spans") or [],
        }
        bindings.append(binding)
        if resolved["resolution"] == "synthetic":
            issues.append(_issue("canonical_synthetic_source", "INFO", f"{ref.get('source_id')} is a declared synthetic domain, not book text", "source"))
            if ref.get("source_id") in support_ids and resolved.get("key"):
                support_keys.add(resolved["key"])
                support_text_keys.add((resolved.get("book_id"), _sha_text(resolved.get("text") or "")))
            continue
        if resolved["resolution"] != "verbatim":
            issues.append(_issue("source_ref_unresolved", "FAIL", f"{ref.get('source_id')}: {resolved.get('reason', resolved['resolution'])}", "source"))
            continue
        if ref.get("text_sha256") and ref.get("text_sha256") != resolved["text_sha256"]:
            issues.append(_issue("source_text_hash_mismatch", "FAIL", f"{ref.get('source_id')} text_sha256 does not match the index", "source"))
        if ref.get("index_sha256") and ref.get("index_sha256") != resolved.get("index_sha256"):
            issues.append(_issue("source_index_hash_mismatch", "FAIL", f"{ref.get('source_id')} index_sha256 does not match the file", "source"))
        for span in ref.get("spans") or []:
            start, end, supplied = span.get("start"), span.get("end"), span.get("text")
            actual = resolved["text"]
            if not isinstance(start, int) or not isinstance(end, int) or supplied != actual[start:end]:
                issues.append(_issue("source_span_mismatch", "FAIL", f"{ref.get('source_id')} span is not exact", "source"))
        if ref.get("source_id") in support_ids:
            if resolved.get("key"):
                support_keys.add(resolved["key"])
                support_text_keys.add((resolved.get("book_id"), resolved["text_sha256"]))
            if ref.get("role") == "distractor":
                issues.append(_issue("distractor_used_as_support", "INFO", f"{ref.get('source_id')} is labelled distractor but a required fact uses it", "source"))
        elif ref.get("role") == "distractor":
            pass
    for source_id in support_ids - set(refs_by_id):
        issues.append(_issue("fact_witness_not_provided", "FAIL", f"required fact names {source_id!r} outside provided_source_ids", "split"))

    quote_checks = []
    target_text = answer.strip()
    refusal_exact = bool(target.get("refused")) or target_text == REFUSAL
    for quote in _target_quotes(answer):
        check = {
            "chapter_tag": quote["chapter"],
            "quote": quote["quote"],
            "quote_sha256": _sha_text(quote["quote"]),
            "status": "absent_book",
            "book_id": None,
            "chunk_id": None,
            "source_key": None,
        }
        for binding in bindings:
            if binding["resolution"] not in ("verbatim", "synthetic"):
                continue
            text = ""
            if binding["resolution"] == "synthetic":
                text = binding.get("text") or ""
            elif binding["kind"] == "caption":
                found = books.figures.get((binding["book_id"], binding["chunk_id"]), [])
                text = found[0].get("caption") or "" if len(found) == 1 else ""
            else:
                book = books.by_book(binding["book_id"])
                text = (book["chunks"].get(binding["chunk_id"], {}) or {}).get("text") or "" if book else ""
            status = _match_status(quote["quote"], text)
            if not status:
                continue
            check.update({"status": status, "book_id": binding["book_id"], "chunk_id": binding["chunk_id"], "source_key": binding["key"]})
            if status == "normalized_only":
                issues.append(_issue("target_quote_normalized_only", "REVIEW", f"quote {quote['quote'][:60]!r} is not byte-literal", "quote"))
            if binding["key"] not in support_keys:
                support_keys.add(binding["key"])
                support_text_keys.add((binding["book_id"], _sha_text(text)))
                issues.append(_issue("quote_adds_support_not_in_facts", "INFO", "target quote names a provided source not listed in required_facts", "quote"))
            break
        if check["book_id"] is None:
            status, hits = _search_books(quote["quote"], books)
            check["status"] = status
            check["global_hits"] = [f"{book}:{chunk}" for book, chunk in hits[:8]]
            issues.append(
                _issue(
                    "target_quote_wrong_source" if status != "absent_book" else "target_quote_not_in_book",
                    "FAIL",
                    f"quote {quote['quote'][:60]!r} is not literal in provided sources",
                    "quote",
                )
            )
        quote_checks.append(check)

    is_gloss = target.get("kind") == "gloss"
    has_target = bool(target_text or target.get("kind") or target.get("refused") or target.get("citations"))
    if not has_target:
        issues.append(_issue("prompt_only_no_target", "INFO", "prompt-only evaluation row; no target answer to check", "target"))
    elif target.get("kind") == "refusal" or target.get("refused"):
        refusal_exact = target_text == REFUSAL
        if not refusal_exact:
            issues.append(_issue("refusal_with_commentary", "FAIL", "refusal target is not exactly 'Not in this book.'", "target"))
    elif not quote_checks and not is_gloss:
        issues.append(_issue("answer_without_quote", "REVIEW", "answer target carries no [Ch.] quote and is not a gloss", "target"))

    refusal_check = None
    if target.get("kind") == "refusal" or target.get("refused") or target_text == REFUSAL:
        if expected.get("book_answerable") is True and expected.get("evidence_sufficient") is True:
            classification = "sufficient_evidence_with_refusal"
            issues.append(_issue("refusal_with_sufficient_evidence", "REVIEW", "record declares answerable/sufficient evidence but target refuses", "refusal"))
        elif record.get("absence_evidence") or not refs:
            classification = "intentional_withheld_context"
            issues.append(_issue("refusal_evidence_withheld", "INFO", "withheld/absent evidence is a legitimate refusal label, not junk", "refusal"))
        else:
            classification = "terms_present_in_supplied_context"
        refusal_check = {
            "classification": classification,
            "junk": False,
            "supplied_passages": len(refs),
            "semantic_answerability": "REVIEW_NOT_CERTIFIED",
        }

    review = record.get("review") or {}
    semantic_status = "REVIEW_NOT_CERTIFIED"
    if review.get("status") == "accepted":
        digest = review.get("content_sha256")
        try:
            sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))
            import dataset_integrity as DI  # noqa: WPS433

            expected_digest = DI.review_digest(record)
        except Exception:  # pragma: no cover - the validator may be mid-change
            payload = {key: value for key, value in record.items() if key != "review"}
            expected_digest = _sha_text(_canonical_json(payload))
        if not digest or digest != expected_digest:
            issues.append(_issue("review_digest_stale_or_missing", "FAIL", "accepted review does not bind these bytes", "review"))
        else:
            semantic_status = "ACCEPTED_EXTERNAL_REVIEW_NOT_RECHECKED"
    elif review.get("status") == "rejected":
        issues.append(_issue("review_rejected", "FAIL", "record is marked rejected", "review"))

    review_clauses = []
    for check in quote_checks:
        review_clauses.append(
            {
                "kind": "quote",
                "text": check["quote"],
                "status": "MECHANICAL_PASS" if check["status"] == "literal" else "REVIEW",
                "reason": f"quote status {check['status']}",
            }
        )
    for fact in expected.get("required_facts") or []:
        review_clauses.append(
            {
                "kind": "claim",
                "text": str(fact.get("claim") or ""),
                "status": "REVIEW",
                "reason": "required fact; independent semantic review required",
            }
        )
    if is_gloss:
        review_clauses.append(
            {
                "kind": "gloss",
                "text": answer,
                "status": "REVIEW",
                "reason": "quote-free gloss is legitimate; its truth is semantic",
            }
        )
    if target.get("kind") == "refusal" or target.get("refused") or target_text == REFUSAL:
        review_clauses.append(
            {
                "kind": "refusal",
                "text": REFUSAL,
                "status": "REVIEW",
                "reason": "semantic answerability of the supplied evidence",
            }
        )
    if not any(clause.get("status") == "REVIEW" for clause in review_clauses):
        review_clauses.append(
            {
                "kind": "answer_fit",
                "text": "",
                "status": "REVIEW",
                "reason": "expected facts and answer fit are semantic; a literal quote is not approval",
            }
        )

    line = file_ctx["line"] if file_ctx else None
    path = file_ctx["path"] if file_ctx else "<memory>"
    boundary = (file_ctx or {}).get("shard_boundary")
    if target.get("kind") == "refusal" or target.get("refused") or target_text == REFUSAL:
        task_kind = "canonical_refusal"
    elif is_gloss:
        task_kind = "canonical_gloss"
    elif not target:
        task_kind = "canonical_eval"
    else:
        task_kind = "canonical_answer"
    source_scope = sorted({binding.get("book_id") for binding in bindings if binding.get("book_id")})
    return {
        "schema_version": SCHEMA_VERSION,
        "id": record_id,
        "format": "canonical",
        "source_path": path,
        "line": line,
        "raw_line_sha256": file_ctx["raw_line_sha256"] if file_ctx else None,
        "origin": {
            "path": path,
            "sha256": (file_ctx or {}).get("file_sha256"),
            "record": record_id or (str(line) if line is not None else None),
            "record_ordinal": line,
            "line_sha256": file_ctx["raw_line_sha256"] if file_ctx else None,
            "line_sha256_with_lf": (file_ctx or {}).get("line_sha256_with_lf"),
        },
        "shard": ("A" if boundary and line and line <= boundary else ("B" if boundary and line else None)),
        "messages_sha256": _sha_text(_canonical_json({key: value for key, value in record.items() if key != "review"})),
        "user_prompt_sha256": _sha_text(
            _canonical_json(
                {
                    "question": question,
                    "history": record.get("history") or [],
                    "provided_source_ids": provided,
                }
            )
        ),
        "target_sha256": _sha_text(answer),
        "review": {
            "status": "needs_review",
            "reviewer": None,
            "provenance": "agent",
            "criteria_version": "training-target-source-v1",
            "notes": "Mechanical audit only; required facts and target meaning require independent source review.",
        },
        "canonical_ready": False,
        "task_kind": task_kind,
        "source_scope": source_scope,
        "split": split,
        "family_id": str(record.get("family_id") or f"question:{_question_key(question)}"),
        "question": question,
        "declared_meta": {
            "book_id": record.get("book_id"),
            "review_status": review.get("status"),
            "paraphrase_of": (record.get("metadata") or {}).get("paraphrase_of"),
            "coverage": record.get("coverage"),
        },
        "target": {
            "kind": "none" if not has_target else ("refusal" if (target.get("kind") == "refusal" or target.get("refused") or target_text == REFUSAL) else ("gloss" if is_gloss else "answer")),
            "refusal_exact": refusal_exact,
            "quote_free_gloss": bool(is_gloss and not quote_checks),
            "quote_count": len(quote_checks),
            "present": bool(target),
        },
        "quote_checks": quote_checks,
        "source_bindings": bindings,
        "support_keys": sorted(support_keys),
        "support_text_keys": sorted([list(item) for item in support_text_keys]),
        "context_keys": sorted({binding["key"] for binding in bindings if binding.get("key") and binding["key"] not in support_keys}),
        "history_keys": [],
        "history_quotes": [],
        "refusal_check": refusal_check,
        "issues": issues,
        "mechanical_status": _worst(issues),
        "semantic_status": semantic_status,
        "train_ready": False,
        "review_clauses": review_clauses,
        "paraphrase_of": (record.get("metadata") or {}).get("paraphrase_of") or [],
    }


def _audit_one(record, books, file_ctx=None):
    if isinstance(record, dict) and "messages" in record:
        return _audit_original(record, books, file_ctx)
    if isinstance(record, dict) and "source_refs" in record:
        return _audit_canonical(record, books, file_ctx)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": file_ctx["line"] if file_ctx else "memory",
        "format": "unknown",
        "source_path": file_ctx["path"] if file_ctx else "<memory>",
        "line": file_ctx["line"] if file_ctx else None,
        "raw_line_sha256": file_ctx["raw_line_sha256"] if file_ctx else None,
        "origin": {
            "path": file_ctx["path"] if file_ctx else "<memory>",
            "sha256": (file_ctx or {}).get("file_sha256"),
            "record": str(file_ctx["line"]) if file_ctx and file_ctx.get("line") is not None else None,
            "record_ordinal": file_ctx.get("line") if file_ctx else None,
            "line_sha256": file_ctx["raw_line_sha256"] if file_ctx else None,
            "line_sha256_with_lf": (file_ctx or {}).get("line_sha256_with_lf"),
        },
        "messages_sha256": None,
        "user_prompt_sha256": None,
        "target_sha256": None,
        "review": {
            "status": "needs_review",
            "reviewer": None,
            "provenance": "agent",
            "criteria_version": "training-target-source-v1",
            "notes": "Record shape could not be audited.",
        },
        "canonical_ready": False,
        "task_kind": "unknown",
        "source_scope": [],
        "split": "unknown",
        "family_id": None,
        "question": "",
        "declared_meta": {},
        "target": {"kind": "unknown", "refusal_exact": False, "quote_free_gloss": False, "quote_count": 0},
        "quote_checks": [],
        "source_bindings": [],
        "support_keys": [],
        "support_text_keys": [],
        "context_keys": [],
        "history_keys": [],
        "history_quotes": [],
        "refusal_check": None,
        "issues": [_issue("unknown_record_shape", "FAIL", "record has neither messages nor source_refs", "schema")],
        "mechanical_status": "FAIL",
        "semantic_status": "REVIEW_NOT_CERTIFIED",
        "train_ready": False,
        "review_clauses": [],
    }


def _input_identity(entry):
    return _sha_text(
        _canonical_json(
            {
                "question": _question_key(entry.get("question")),
                "history": entry.get("history_quotes") or [],
                "support_text_keys": entry.get("support_text_keys") or [],
                "context_keys": entry.get("context_keys") or [],
                "format": entry.get("format"),
            }
        )
    )


def _split_findings(entries):
    by_family = defaultdict(lambda: defaultdict(list))
    by_question = defaultdict(lambda: defaultdict(list))
    by_support = defaultdict(lambda: defaultdict(list))
    by_input = defaultdict(lambda: defaultdict(list))
    by_paraphrase = defaultdict(lambda: defaultdict(list))
    by_context = defaultdict(set)
    ids = {entry.get("id"): entry for entry in entries}
    for entry in entries:
        split = entry.get("split") or "unknown"
        if entry.get("family_id"):
            by_family[entry["family_id"]][split].append(entry.get("id"))
        question_key = _question_key(entry.get("question"))
        if question_key:
            by_question[question_key][split].append(entry.get("id"))
        for key in entry.get("support_keys") or []:
            by_support[key][split].append(entry.get("id"))
        by_input[_input_identity(entry)][split].append(entry.get("id"))
        for other in entry.get("paraphrase_of") or []:
            by_paraphrase[entry.get("id")][split].append(other)
            if other in ids:
                other_split = ids[other].get("split") or "unknown"
                by_paraphrase[entry.get("id")][other_split].append(other)
                by_paraphrase[other][other_split].append(entry.get("id"))
                by_paraphrase[other][split].append(entry.get("id"))
        for key in entry.get("context_keys") or []:
            by_context[key].add(split)

    findings = []

    def add(code, key, groups, detail):
        findings.append({"code": code, "key": key, "splits": sorted(groups), "ids": {split: groups[split][:8] for split in sorted(groups)}, "detail": detail})

    for family, groups in by_family.items():
        if len(groups) > 1:
            add("family_cross_split", family, groups, "one family appears in more than one split")
    for question, groups in by_question.items():
        if len(groups) > 1:
            add("question_cross_split", question, groups, "the same normalized question appears in more than one split")
    for key, groups in by_support.items():
        if len(groups) > 1:
            add("support_cross_split", key, groups, "one answer-support source appears in more than one split")
    for key, groups in by_input.items():
        if len(groups) > 1:
            add("duplicate_full_input_cross_split", key, groups, "the same model input appears in more than one split")
    for key, groups in by_paraphrase.items():
        if len(groups) > 1:
            add("paraphrase_cross_split", key, groups, "declared paraphrase variants appear in more than one split")
    context_overlaps = []
    for key, context_splits in by_context.items():
        support_splits = set(by_support.get(key, {}))
        combined = set(context_splits) | support_splits
        if len(combined) > 1:
            context_overlaps.append(
                {
                    "key": key,
                    "splits": sorted(combined),
                    "support_splits": sorted(support_splits),
                    "failed": False,
                    "detail": "context-only overlap; tracked, not a support leak unless the answer target uses it",
                }
            )
    return findings, context_overlaps


def _component_map(entries):
    parent = list(range(len(entries)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    maps = [defaultdict(list) for _ in range(5)]
    for index, entry in enumerate(entries):
        if entry.get("family_id"):
            maps[0][entry["family_id"]].append(index)
        for key in entry.get("support_keys") or []:
            maps[1][key].append(index)
        for key in entry.get("support_text_keys") or []:
            maps[2][f"text:{key[0]}:{key[1]}"].append(index)
        for key in entry.get("history_keys") or []:
            maps[3][key].append(index)
        for key in entry.get("paraphrase_of") or []:
            maps[4][key].append(index)
        maps[4][_input_identity(entry)].append(index)
    for mapping in maps:
        for members in mapping.values():
            for member in members[1:]:
                union(members[0], member)
    groups = defaultdict(list)
    for index in range(len(entries)):
        groups[find(index)].append(index)
    components = []
    for members in groups.values():
        ids = sorted(str(entries[index].get("id")) for index in members)
        components.append(
            {
                "component_id": _sha_text(_canonical_json(ids)),
                "size": len(members),
                "ids": ids,
                "roles": sorted({str(entries[index].get("role")) for index in members}),
                "splits": sorted({str(entries[index].get("split")) for index in members}),
                "families": sorted({str(entries[index].get("family_id")) for index in members if entries[index].get("family_id")}),
                "support_keys": sorted({key for index in members for key in (entries[index].get("support_keys") or [])}),
                "support_text_keys": sorted({tuple(key) for index in members for key in (entries[index].get("support_text_keys") or [])}),
                "context_keys": sorted({key for index in members for key in (entries[index].get("context_keys") or [])}),
            }
        )
    components.sort(key=lambda item: (-item["size"], item["component_id"]))
    return components


def _assign_components(entries):
    by_role = defaultdict(list)
    for entry in entries:
        by_role[str(entry.get("role"))].append(entry)
    for subset in by_role.values():
        by_id = {str(entry.get("id")): entry for entry in subset}
        for component in _component_map(subset):
            for entry_id in component["ids"]:
                entry = by_id.get(entry_id)
                if entry is not None:
                    entry["component_id"] = component["component_id"]


def _population_components(entries):
    rows = []
    by_role = defaultdict(list)
    for entry in entries:
        by_role[str(entry.get("role"))].append(entry)
    for role in sorted(by_role):
        for component in _component_map(by_role[role]):
            item = dict(component)
            item["population"] = role
            rows.append(item)
    return rows


def _components(entries):
    components = _component_map(entries)
    sizes = [component["size"] for component in components]
    return {
        "units": len(components),
        "rows": len(entries),
        "largest": sizes[0] if sizes else 0,
        "singletons": sum(1 for size in sizes if size == 1),
        "sizes": sizes[:20],
        "note": "connected by family, actual answer-support source, history referent, duplicate input, and declared paraphrase; split units are whole components, never rows",
    }


def _disposition(entry):
    target = entry.get("target") or {}
    codes = {issue["code"] for issue in entry.get("issues") or []}
    if target.get("kind") == "refusal":
        if entry.get("refusal_check", {}).get("classification") in ("terms_absent_from_supplied_context", "no_supplied_context", "intentional_withheld_context"):
            return "refusal_evidence_withheld"
        return "refusal_context_review"
    if target.get("kind") == "none":
        return "prompt_only_eval"
    if target.get("quote_free_gloss"):
        return "quote_free_gloss_anchor"
    if "target_quote_normalized_only" in codes:
        return "answer_quote_normalized_review"
    if codes & {"source_unresolved", "source_id_text_conflict", "source_normalized_only", "source_formatting_drift", "chapter_tag_mismatch"}:
        return "answer_source_review"
    if target.get("kind") == "answer" and entry.get("quote_checks"):
        return "answer_quote_literal"
    return "target_review"


def _summary(entries):
    return {
        "rows": len(entries),
        "mechanical_pass": sum(1 for entry in entries if entry["mechanical_status"] == "PASS"),
        "mechanical_review": sum(1 for entry in entries if entry["mechanical_status"] == "REVIEW"),
        "mechanical_fail": sum(1 for entry in entries if entry["mechanical_status"] == "FAIL"),
        "semantic_review_required": sum(
            1 for entry in entries if entry.get("semantic_status") in ("REVIEW_NOT_CERTIFIED", "SEMANTIC_REVIEW_BINDING_FAILED")
            or (entry.get("semantic_status") or "").endswith("_NEEDS_REVIEW")
            or (entry.get("semantic_status") or "").endswith("_REJECTED")
        ),
        "semantic_statuses": dict(Counter(entry.get("semantic_status") for entry in entries)),
        "canonical_bind_pending": sum(
            1 for entry in entries if (entry.get("semantic_review") or {}).get("decision") == "accepted" and (entry.get("semantic_review") or {}).get("binding_status") == "BOUND"
        ),
        "train_ready": 0,
        "formats": dict(Counter(entry["format"] for entry in entries)),
        "splits": dict(Counter(entry["split"] for entry in entries)),
        "target_kinds": dict(Counter(entry["target"]["kind"] for entry in entries)),
        "dispositions": dict(Counter(entry.get("disposition") for entry in entries)),
        "quote_statuses": dict(Counter(check["status"] for entry in entries for check in entry.get("quote_checks") or [])),
        "binding_resolutions": dict(Counter(binding["resolution"] for entry in entries for binding in entry.get("source_bindings") or [])),
        "refusal_classifications": dict(Counter(entry["refusal_check"]["classification"] for entry in entries if entry.get("refusal_check"))),
        "issue_codes": dict(Counter(issue["code"] for entry in entries for issue in entry.get("issues") or [])),
    }


def _review_queue(entries):
    queue = []
    for entry in entries:
        clauses = [clause for clause in entry.get("review_clauses") or [] if clause.get("status") == "REVIEW"]
        if not clauses and entry["mechanical_status"] == "PASS":
            continue
        semantic = entry.get("semantic_review") or {}
        queue_kind = "canonical_bind" if semantic.get("decision") == "accepted" and semantic.get("binding_status") == "BOUND" else "semantic_review"
        queue.append(
            {
                "id": entry.get("id"),
                "source_path": entry.get("source_path"),
                "line": entry.get("line"),
                "split": entry.get("split"),
                "mechanical_status": entry["mechanical_status"],
                "semantic_decision": semantic.get("decision"),
                "semantic_binding_status": semantic.get("binding_status"),
                "queue_kind": queue_kind,
                "issues": [issue for issue in entry.get("issues") or [] if issue["severity"] in ("FAIL", "REVIEW")],
                "clauses": clauses,
                "priority": "high" if entry["mechanical_status"] == "FAIL" else ("medium" if entry["mechanical_status"] == "REVIEW" else "normal"),
            }
        )
    return queue


def audit_records(records, *, index_paths=None, catalog_path=None, dataset_name="<memory>", roles=None):
    books = load_books(index_paths=index_paths, catalog_path=catalog_path)
    entries = []
    for index, record in enumerate(records, 1):
        entry = _audit_one(record, books, {"path": dataset_name, "line": index, "raw_line_sha256": None})
        if roles and record.get("id") in roles:
            entry["role"] = roles[record.get("id")]
        entry["disposition"] = _disposition(entry)
        entries.append(entry)
    _assign_components(entries)
    findings, overlaps = _split_findings(entries)
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": dataset_name,
        "entries": entries,
        "summary": _summary(entries),
        "split_findings": findings,
        "context_overlaps": overlaps,
        "components": _components(entries),
        "review_queue": _review_queue(entries),
    }


def _role_for(path, entry, explicit):
    if explicit:
        return explicit
    split = entry.get("split")
    if split in ("dev", "test"):
        return "dev"
    if split == "review":
        return "pending_review"
    if entry.get("format") == "messages":
        return "historical_train"
    return "pending_review"


def _exposure(entries, train_roles, dev_roles):
    train_support = set()
    train_context = set()
    train_questions = set()
    train_ids = []
    for entry in entries:
        if entry.get("role") not in train_roles:
            continue
        train_ids.append(entry.get("id"))
        train_support.update(entry.get("support_keys") or [])
        train_context.update(entry.get("context_keys") or [])
        train_questions.add(_question_key(entry.get("question")))
    dev_entries = [entry for entry in entries if entry.get("role") in dev_roles]
    support_exposed = []
    context_seen = []
    unseen = []
    exact_questions = []
    for entry in dev_entries:
        support = set(entry.get("support_keys") or [])
        if support & train_support:
            support_exposed.append(entry.get("id"))
        elif support & train_context:
            context_seen.append(entry.get("id"))
        else:
            unseen.append(entry.get("id"))
        key = _question_key(entry.get("question"))
        if key and key in train_questions:
            exact_questions.append(entry.get("id"))
    return {
        "train_entries": len(train_ids),
        "dev_entries": len(dev_entries),
        "dev_support_exposed": len(support_exposed),
        "dev_context_seen": len(context_seen),
        "dev_source_unseen": len(unseen),
        "dev_exact_question_collisions": len(exact_questions),
        "support_exposed_ids": support_exposed,
        "context_seen_ids": context_seen,
        "exact_question_ids": exact_questions,
        "method": "exact chunk key + exact text hash against actual target/fact witnesses; context-only overlaps are counted separately; no semantic-leakage zero is claimed",
    }


def _pending_compare(pending_entries, historical_entries, dev_entries):
    historical_support = set()
    historical_context = set()
    historical_questions = set()
    historical_answer_targets = set()
    historical_refusal_labels = set()
    for entry in historical_entries:
        historical_support.update(entry.get("support_keys") or [])
        historical_context.update(entry.get("context_keys") or [])
        historical_questions.add(_question_key(entry.get("question")))
        if entry.get("target", {}).get("kind") == "refusal":
            historical_refusal_labels.add(entry.get("target_sha256"))
        else:
            historical_answer_targets.add(entry.get("target_sha256"))
    dev_support = set()
    dev_questions = set()
    for entry in dev_entries:
        dev_support.update(entry.get("support_keys") or [])
        dev_questions.add(_question_key(entry.get("question")))
    return {
        "rows": len(pending_entries),
        "exact_question_matches_historical": sum(1 for entry in pending_entries if _question_key(entry.get("question")) in historical_questions),
        "exact_answer_target_matches_historical": sum(
            1
            for entry in pending_entries
            if entry.get("target", {}).get("kind") != "refusal" and entry.get("target_sha256") in historical_answer_targets
        ),
        "exact_refusal_label_matches_historical": sum(
            1
            for entry in pending_entries
            if entry.get("target", {}).get("kind") == "refusal" and entry.get("target_sha256") in historical_refusal_labels
        ),
        "support_overlap_historical": sum(1 for entry in pending_entries if set(entry.get("support_keys") or []) & historical_support),
        "context_overlap_historical": sum(1 for entry in pending_entries if set(entry.get("support_keys") or []) & historical_context),
        "support_or_context_overlap_historical": sum(
            1
            for entry in pending_entries
            if set(entry.get("support_keys") or []) & (historical_support | historical_context)
        ),
        "support_overlap_dev": sum(1 for entry in pending_entries if set(entry.get("support_keys") or []) & dev_support),
        "exact_question_matches_dev": sum(1 for entry in pending_entries if _question_key(entry.get("question")) in dev_questions),
        "note": "pending rows are not train-ready; overlaps are exposure evidence, not semantic proof",
    }


def _exact_witness_text(entry, review_row):
    """The reviewer's own exact source witness for a normalized target quote."""
    for claim in review_row.get("target_claims") or []:
        for witness in claim.get("witnesses") or []:
            if witness.get("role") != "provided_source":
                continue
            text = witness.get("text") or ""
            for check in entry.get("quote_checks") or []:
                if check.get("status") == "literal":
                    continue
                if fold(text) == fold(check.get("quote")):
                    return text
                if _casefold(text) == _casefold(check.get("quote")):
                    return text
    return None


def _bind_semantic_review(entries, review_path, shard, records_by_id, books, seen_review_ids=None, expected_sha256=None):
    seen_review_ids = seen_review_ids if seen_review_ids is not None else set()
    review_path = Path(review_path)
    review_bytes = review_path.read_bytes()
    review_sha = _sha_bytes(review_bytes)
    hash_match = True if not expected_sha256 else review_sha == expected_sha256
    review_rows = []
    for number, raw in enumerate(review_bytes.split(b"\n"), 1):
        if not raw.strip():
            continue
        try:
            review_rows.append(json.loads(raw.decode("utf-8")))
        except ValueError:
            review_rows.append({"_parse_error": str(number)})
    by_id = {entry.get("id"): entry for entry in entries}
    summary = {
        "shard": shard,
        "path": str(review_path),
        "sha256": review_sha,
        "expected_sha256": expected_sha256,
        "hash_match": hash_match,
        "rows": len(review_rows),
        "bound": 0,
        "invalid": 0,
        "missing_entries": [],
        "duplicate_ids": [],
        "decisions": Counter(),
        "witnesses": {"total": 0, "valid": 0, "invalid": 0},
        "mechanical_repairs": 0,
        "canonical_binding": "PENDING_INDEPENDENT_FINAL_BIND",
    }
    for review in review_rows:
        entry_id = review.get("id")
        entry = by_id.get(entry_id)
        if entry is None:
            summary["invalid"] += 1
            summary["missing_entries"].append(entry_id)
            continue
        decision = (review.get("review") or {}).get("status") or "unknown"
        summary["decisions"][decision] += 1
        record = records_by_id.get(entry_id)
        if record is None:
            try:
                source_lines = Path(entry["source_path"]).read_bytes().split(b"\n")
                record = json.loads(source_lines[entry["line"] - 1].decode("utf-8"))
            except Exception:
                record = None
        invalid_codes = [] if hash_match else ["review_ledger_hash_mismatch"]
        origin = review.get("origin") or {}
        if entry_id in seen_review_ids:
            invalid_codes.append("semantic_review_duplicate")
            summary["duplicate_ids"].append(entry_id)
        else:
            seen_review_ids.add(entry_id)
        if str(entry.get("line")) != str(origin.get("record")):
            invalid_codes.append("semantic_review_record_mismatch")
        if entry.get("messages_sha256") != review.get("messages_sha256"):
            invalid_codes.append("semantic_review_hash_mismatch")
        if entry.get("user_prompt_sha256") != review.get("user_prompt_sha256"):
            invalid_codes.append("semantic_review_user_hash_mismatch")
        if entry.get("target_sha256") != review.get("target_sha256"):
            invalid_codes.append("semantic_review_target_hash_mismatch")
        if (entry.get("origin") or {}).get("line_sha256") != origin.get("line_sha256"):
            invalid_codes.append("semantic_review_line_hash_mismatch")
        full_file_sha = None
        origin_dialect = None
        try:
            full_file_sha = _sha_bytes(Path(entry["source_path"]).read_bytes())
            if (entry.get("origin") or {}).get("sha256") != full_file_sha:
                invalid_codes.append("semantic_review_full_file_hash_mismatch")
            if origin.get("sha256") == full_file_sha:
                origin_dialect = "full_file"
            elif origin.get("sha256") == (entry.get("origin") or {}).get("line_sha256_with_lf"):
                origin_dialect = "line_with_lf"
            else:
                invalid_codes.append("semantic_review_origin_dialect_mismatch")
        except OSError:
            invalid_codes.append("semantic_review_source_missing")

        witness_details = []
        blocks = _parse_block_offsets(_user_content(record)) if record else []
        for claim_index, claim in enumerate(review.get("target_claims") or []):
            for witness_index, witness in enumerate(claim.get("witnesses") or []):
                summary["witnesses"]["total"] += 1
                detail = {
                    "claim_index": claim_index,
                    "witness_index": witness_index,
                    "message_index": witness.get("message_index"),
                    "start": witness.get("start"),
                    "end": witness.get("end"),
                    "role": witness.get("role"),
                    "valid": False,
                    "reason": None,
                }
                messages = (record or {}).get("messages") or []
                message_index = witness.get("message_index")
                if not isinstance(message_index, int) or message_index < 0 or message_index >= len(messages):
                    detail["reason"] = "message_index_out_of_range"
                elif witness.get("role") != "provided_source":
                    detail["reason"] = "witness_role_not_provided_source"
                else:
                    content = messages[message_index].get("content") or ""
                    start, end = witness.get("start"), witness.get("end")
                    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end > len(content):
                        detail["reason"] = "offset_out_of_range"
                    elif content[start:end] != witness.get("text"):
                        detail["reason"] = "offset_text_mismatch"
                    else:
                        for block_index, block in enumerate(blocks):
                            if block["start"] <= start and end <= block["end"]:
                                binding = entry.get("source_bindings", [])[block_index] if block_index < len(entry.get("source_bindings", [])) else None
                                detail.update(
                                    {
                                        "valid": True,
                                        "passage_scope": True,
                                        "block_index": block_index,
                                        "chunk_id": block.get("chunk_id"),
                                        "book_id": (binding or {}).get("book_id"),
                                        "resolution": (binding or {}).get("resolution"),
                                        "source_key": (binding or {}).get("key"),
                                    }
                                )
                                if not binding or (binding or {}).get("resolution") not in ("verbatim", "normalized_only", "formatting_drift", "synthetic"):
                                    detail["valid"] = False
                                    detail["reason"] = "passage_scope_unresolved"
                                break
                        if not detail.get("passage_scope"):
                            detail["reason"] = "offset_outside_provided_passage"
                if detail["valid"]:
                    summary["witnesses"]["valid"] += 1
                else:
                    summary["witnesses"]["invalid"] += 1
                witness_details.append(detail)

        if any(not detail["valid"] for detail in witness_details):
            invalid_codes.append("semantic_review_witness_invalid")
        claim_has_valid = {detail["claim_index"] for detail in witness_details if detail["valid"]}
        claims = review.get("target_claims") or []
        if decision == "accepted":
            is_exact_refusal = bool((entry.get("target") or {}).get("refusal_exact"))
            if not is_exact_refusal:
                if not claims:
                    invalid_codes.append("accepted_non_refusal_without_claims")
                elif not any(
                    claim.get("verdict") == "supported" and claim_index in claim_has_valid
                    for claim_index, claim in enumerate(claims)
                ):
                    invalid_codes.append("accepted_non_refusal_without_supported_witness")
            for claim_index in range(len(claims)):
                if claim_index not in claim_has_valid:
                    invalid_codes.append("semantic_review_accepted_claim_without_valid_witness")
                    break
        if invalid_codes:
            summary["invalid"] += 1
            summary["bound"] += 0
        else:
            summary["bound"] += 1

        repair = None
        normalized = [check for check in entry.get("quote_checks") or [] if check.get("status") == "normalized_only"]
        if normalized:
            exact = _exact_witness_text(entry, review)
            if exact:
                repair = {
                    "kind": "quote_exact_restoration",
                    "applied": False,
                    "peer_rebind_required": True,
                    "before_text": normalized[0].get("quote"),
                    "after_text": exact,
                    "reason": "book wrapping/case copy is semantically valid but native dataset-integrity strictness needs the exact source quote",
                }
                summary["mechanical_repairs"] += 1

        entry["semantic_review"] = {
            "shard": shard,
            "review_ledger_path": str(review_path),
            "review_ledger_sha256": review_sha,
            "decision": decision,
            "binding_status": "INVALID" if invalid_codes else "BOUND",
            "reviewer": (review.get("review") or {}).get("reviewer"),
            "criteria_version": (review.get("review") or {}).get("criteria_version"),
            "notes": (review.get("review") or {}).get("notes"),
            "task_kind": review.get("task_kind"),
            "source_scope": review.get("source_scope"),
            "hash_binding": {
                "messages_sha256": review.get("messages_sha256"),
                "user_prompt_sha256": review.get("user_prompt_sha256"),
                "target_sha256": review.get("target_sha256"),
                "review_origin_sha256": origin.get("sha256"),
                "origin_dialect": origin_dialect,
                "full_file_sha256": full_file_sha,
                "record_ordinal": origin.get("record"),
                "line_sha256_no_lf": origin.get("line_sha256"),
                "line_sha256_with_lf": (entry.get("origin") or {}).get("line_sha256_with_lf"),
                "all_match": not invalid_codes,
            },
            "witnesses": {
                "total": len(witness_details),
                "valid": sum(1 for detail in witness_details if detail["valid"]),
                "invalid": sum(1 for detail in witness_details if not detail["valid"]),
                "details": witness_details,
            },
            "mechanical_repair": repair,
            "canonical_binding": {
                "status": "PENDING_INDEPENDENT_FINAL_BIND",
                "reason": "canonical review_digest covers the final canonical record without its review block; it is not the original messages digest",
                "required_after": ["split_metadata_frozen", "canonical_record_built"],
                "reviewer": None,
            },
        }
        if invalid_codes:
            entry["semantic_status"] = "SEMANTIC_REVIEW_BINDING_FAILED"
            for code in sorted(set(invalid_codes)):
                entry.setdefault("issues", []).append(
                    _issue(code, "REVIEW", f"semantic decision not transferred from {review_path.name}", "review")
                )
        elif decision == "accepted":
            entry["semantic_status"] = f"SEMANTIC_REVIEW_{shard}_ACCEPTED_PENDING_CANONICAL_BIND"
        elif decision == "needs_review":
            entry["semantic_status"] = f"SEMANTIC_REVIEW_{shard}_NEEDS_REVIEW"
        elif decision == "rejected":
            entry["semantic_status"] = f"SEMANTIC_REVIEW_{shard}_REJECTED"
        else:
            entry["semantic_status"] = "REVIEW_NOT_CERTIFIED"
        entry["train_ready"] = False
        entry["mechanical_status"] = _worst(entry.get("issues") or [])
    summary["decisions"] = dict(summary["decisions"])
    return summary


def _user_content(record):
    for message in (record or {}).get("messages") or []:
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _candidate_fold(component_id, seed, validation_percent):
    score = int(_sha_text(f"{seed}:{component_id}")[:8], 16) % 100
    return "validation" if score < validation_percent else "train"


def build_candidate(entries, dev_entries, records_by_id, *, seed=20261030, validation_percent=10):
    """Select reviewed + mechanically eligible rows and split whole components.

    Semantic acceptance alone is not train readiness. This function records an
    exclusion for every 844 row, keeps complete-input duplicates once, excludes
    components that touch the 86 dev support/context graph, and assigns whole
    components to train or validation by a deterministic seeded hash. It never
    edits a target or a prompt.
    """
    historical = [entry for entry in entries if entry.get("role") == "historical_train"]
    dev_support = {key for entry in dev_entries for key in entry.get("support_keys") or []}
    dev_context = {key for entry in dev_entries for key in entry.get("context_keys") or []}
    excluded = {}
    eligible = []
    for entry in sorted(historical, key=lambda item: item.get("line") or 0):
        review = entry.get("semantic_review") or {}
        decision = review.get("decision")
        if decision != "accepted" or review.get("binding_status") != "BOUND":
            reason = "semantic_needs_review" if decision == "needs_review" else ("semantic_rejected" if decision == "rejected" else "semantic_binding_failed")
            excluded[entry["id"]] = {"reason": reason, "detail": review.get("notes")}
            continue
        codes = {issue["code"] for issue in entry.get("issues") or []}
        if "target_quote_normalized_only" in codes:
            excluded[entry["id"]] = {"reason": "target_quote_normalization_requires_repair", "detail": "strict quote checker needs an exact source quote and a peer rebind"}
            continue
        if codes & {"source_formatting_drift", "source_normalized_only"}:
            excluded[entry["id"]] = {"reason": "source_identity_repair_pending", "detail": sorted(codes & {"source_formatting_drift", "source_normalized_only"})}
            continue
        if "chapter_tag_mismatch" in codes:
            excluded[entry["id"]] = {"reason": "chapter_tag_repair_pending", "detail": "wrong chapter tag; semantic review does not waive it"}
            continue
        if entry.get("mechanical_status") == "FAIL" or codes & {"target_quote_not_in_book", "target_quote_wrong_source", "source_unresolved", "source_id_text_conflict"}:
            excluded[entry["id"]] = {"reason": "mechanical_ineligible", "detail": sorted(codes)}
            continue
        eligible.append(entry)

    seen_inputs = {}
    deduped = []
    for entry in eligible:
        digest = entry.get("messages_sha256")
        if digest in seen_inputs:
            excluded[entry["id"]] = {"reason": "duplicate_complete_input", "detail": f"duplicate of {seen_inputs[digest]}"}
        else:
            seen_inputs[digest] = entry["id"]
            deduped.append(entry)

    dev_support_text = {
        tuple(key) for entry in dev_entries for key in entry.get("support_text_keys") or []
    }
    full_population = historical + list(dev_entries)
    full_components = _component_map(full_population)
    full_component_members = {component["component_id"]: component["ids"] for component in full_components}
    full_component_by_entry = {
        entry_id: component["component_id"]
        for component in full_components
        for entry_id in component["ids"]
    }
    dev_ids = {entry.get("id") for entry in dev_entries}
    by_id = {entry.get("id"): entry for entry in full_population}
    protected_full_components = {}
    for component in full_components:
        contains_dev = any(entry_id in dev_ids for entry_id in component["ids"])
        historical_members = [
            by_id[entry_id]
            for entry_id in component["ids"]
            if entry_id in by_id and by_id[entry_id].get("role") == "historical_train"
        ]
        historical_support = {key for entry in historical_members for key in entry.get("support_keys") or []}
        historical_support_text = {tuple(key) for entry in historical_members for key in entry.get("support_text_keys") or []}
        historical_context = {key for entry in historical_members for key in entry.get("context_keys") or []}
        support_overlap = historical_support & dev_support
        text_overlap = historical_support_text & dev_support_text
        context_overlap = (historical_support | historical_context) & (dev_support | dev_context)
        if support_overlap or text_overlap:
            detail = sorted(str(key) for key in support_overlap) + [
                f"text:{book}:{digest}" for book, digest in sorted(text_overlap)
            ]
            protected_full_components[component["component_id"]] = ("dev_support_component_overlap", detail[:8])
        elif context_overlap:
            protected_full_components[component["component_id"]] = ("dev_context_component_overlap", sorted(context_overlap)[:8])
        elif contains_dev:
            protected_full_components[component["component_id"]] = ("dev_full_component_overlap", sorted(component["ids"])[:8])

    kept_entries = []
    for entry in deduped:
        full_component_id = full_component_by_entry.get(entry["id"])
        entry["full_component_id"] = full_component_id
        protected = protected_full_components.get(full_component_id)
        if protected:
            excluded[entry["id"]] = {"reason": protected[0], "detail": protected[1]}
            continue
        kept_entries.append(entry)

    candidate_components = _component_map(kept_entries)
    candidate_component = {
        entry_id: component["component_id"]
        for component in candidate_components
        for entry_id in component["ids"]
    }
    fold_by_full_component = {
        component_id: _candidate_fold(component_id, seed, validation_percent)
        for component_id in {full_component_by_entry.get(entry["id"]) for entry in kept_entries}
        if component_id
    }
    selected_entries = kept_entries
    selected_ids = {entry["id"] for entry in selected_entries}
    for entry in selected_entries:
        entry["candidate_component_id"] = candidate_component.get(entry["id"])
        entry["candidate_fold"] = fold_by_full_component.get(entry.get("full_component_id"))

    train = [entry for entry in selected_entries if entry.get("candidate_fold") == "train"]
    validation = [entry for entry in selected_entries if entry.get("candidate_fold") == "validation"]
    train_support = {key for entry in train for key in entry.get("support_keys") or []}
    validation_support = {key for entry in validation for key in entry.get("support_keys") or []}
    train_support_text = {tuple(key) for entry in train for key in entry.get("support_text_keys") or []}
    validation_support_text = {tuple(key) for entry in validation for key in entry.get("support_text_keys") or []}
    train_questions = {_question_key(entry.get("question")) for entry in train}
    validation_questions = {_question_key(entry.get("question")) for entry in validation}
    train_inputs = {entry.get("messages_sha256") for entry in train}
    validation_inputs = {entry.get("messages_sha256") for entry in validation}
    dev_questions = {_question_key(entry.get("question")) for entry in dev_entries}
    checks = {
        "dev_question_overlap": sorted({_question_key(entry.get("question")) for entry in selected_entries} & dev_questions),
        "support_key_cross_fold": sorted(train_support & validation_support),
        "support_text_cross_fold": sorted(train_support_text & validation_support_text),
        "question_cross_fold": sorted(train_questions & validation_questions),
        "duplicate_input_cross_fold": sorted(train_inputs & validation_inputs),
        "full_component_cross_fold": sorted(
            {entry.get("full_component_id") for entry in train}
            & {entry.get("full_component_id") for entry in validation}
        ),
        "candidate_component_cross_fold": sorted(
            {entry.get("candidate_component_id") for entry in train}
            & {entry.get("candidate_component_id") for entry in validation}
        ),
    }
    checks["zero_target_support_straddle"] = not (checks["support_key_cross_fold"] or checks["support_text_cross_fold"])
    prospective_eligible = bool(
        selected_entries
        and validation
        and not any(
            checks[key]
            for key in (
                "support_key_cross_fold",
                "support_text_cross_fold",
                "question_cross_fold",
                "duplicate_input_cross_fold",
                "full_component_cross_fold",
                "candidate_component_cross_fold",
                "dev_question_overlap",
            )
        )
    )

    ledger = []
    for entry in historical:
        exclusion = excluded.get(entry["id"])
        ledger.append(
            {
                "id": entry["id"],
                "line": entry.get("line"),
                "origin": entry.get("origin"),
                "messages_sha256": entry.get("messages_sha256"),
                "target_sha256": entry.get("target_sha256"),
                "semantic_decision": (entry.get("semantic_review") or {}).get("decision"),
                "semantic_binding_status": (entry.get("semantic_review") or {}).get("binding_status"),
                "mechanical_status": entry.get("mechanical_status"),
                "original_mechanical_status": entry.get("mechanical_status"),
                "original_issue_codes": sorted({issue["code"] for issue in entry.get("issues") or []}),
                "target_kind": (entry.get("target") or {}).get("kind"),
                "task_kind": (entry.get("semantic_review") or {}).get("task_kind"),
                "support_keys": entry.get("support_keys") or [],
                "context_keys": entry.get("context_keys") or [],
                "component_id": entry.get("full_component_id"),
                "full_component_id": entry.get("full_component_id"),
                "candidate_component_id": entry.get("candidate_component_id"),
                "selected": entry["id"] in selected_ids,
                "fold": entry.get("candidate_fold") if entry["id"] in selected_ids else None,
                "exclusion_reason": exclusion["reason"] if exclusion else None,
                "exclusion_detail": exclusion["detail"] if exclusion else None,
                "mechanical_repair_required": bool(
                    {issue["code"] for issue in entry.get("issues") or []}
                    & {"source_formatting_drift", "source_normalized_only"}
                ),
            }
        )
    payload = []
    for entry in sorted(selected_entries, key=lambda item: item.get("line") or 0):
        record = records_by_id.get(entry["id"])
        if record is not None:
            payload.append(record)
    excluded_ids = {reason: [entry["id"] for entry in ledger if entry["exclusion_reason"] == reason] for reason in sorted({row["exclusion_reason"] for row in ledger if row["exclusion_reason"]})}
    accepted_rows = [entry for entry in historical if (entry.get("semantic_review") or {}).get("decision") == "accepted"]
    semantic_warning_codes = ("refusal_with_context_terms", "quote_free_gloss", "refusal_evidence_withheld")
    mechanical_warning_codes = (
        "target_quote_normalized_only",
        "source_formatting_drift",
        "source_normalized_only",
        "chapter_tag_mismatch",
        "source_unresolved",
        "source_id_text_conflict",
        "target_quote_not_in_book",
        "target_quote_wrong_source",
    )
    kind_disposition = {}
    for kind in ("answer", "refusal", "gloss"):
        kind_rows = [entry for entry in historical if (entry.get("target") or {}).get("kind") == kind and (entry.get("semantic_review") or {}).get("decision") == "accepted"]
        kind_disposition[kind] = {
            "accepted": len(kind_rows),
            "selected": sum(1 for entry in kind_rows if entry["id"] in selected_ids),
            "excluded_by_reason": dict(
                Counter(
                    excluded[entry["id"]]["reason"]
                    for entry in kind_rows
                    if entry["id"] in excluded
                )
            ),
        }
    warning_resolution = {
        "resolved_by_source_review": {
            code: [entry["id"] for entry in accepted_rows if any(issue["code"] == code for issue in entry.get("issues") or [])]
            for code in semantic_warning_codes
        },
        "still_mechanically_ineligible": {
            code: [entry["id"] for entry in accepted_rows if any(issue["code"] == code for issue in entry.get("issues") or [])]
            for code in mechanical_warning_codes
        },
        "semantic_declined": {
            "needs_review": [entry["id"] for entry in historical if (entry.get("semantic_review") or {}).get("decision") == "needs_review"],
            "rejected": [entry["id"] for entry in historical if (entry.get("semantic_review") or {}).get("decision") == "rejected"],
        },
        "note": "source-review acceptance resolves semantic warnings (for example refusal context terms and quote-free gloss eligibility); it does not waive byte/source identity, stale binding, wrong chapter, or target normalization repairs",
    }
    protected_component_counts = defaultdict(int)
    protected_component_rows = Counter()
    for component_id, (reason, _detail) in protected_full_components.items():
        protected_component_counts[reason] += 1
        protected_component_rows[reason] += sum(
            1
            for entry_id in full_component_members.get(component_id, [])
            if by_id.get(entry_id, {}).get("role") == "historical_train"
        )
    excluded_by_reason_components = defaultdict(set)
    excluded_by_reason_rows = Counter()
    for entry in historical:
        exclusion = excluded.get(entry["id"])
        if not exclusion:
            continue
        excluded_by_reason_rows[exclusion["reason"]] += 1
        component_id = full_component_by_entry.get(entry["id"])
        if component_id:
            excluded_by_reason_components[exclusion["reason"]].add(component_id)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PROVISIONAL_REVIEWED_INPUTS_NOT_CERTIFIED",
        "ready_for_training": False,
        "prospective_eligible": prospective_eligible,
        "launchable": False,
        "canonical_bind_pending": True,
        "certified_gpu_release": False,
        "seed": seed,
        "validation_percent_requested": validation_percent,
        "validation_percent_achieved": round(100 * len(validation) / len(selected_entries), 2) if selected_entries else 0,
        "split_assigned_before_candidate_baseline": True,
        "assignment_method": "whole connected component -> sha256(seed:component_id) bucket; no row randomness, no response-quality scoring",
        "counts": {
            "input_844": len(historical),
            "accepted_semantic": sum(1 for entry in historical if (entry.get("semantic_review") or {}).get("decision") == "accepted"),
            "selected": len(selected_entries),
            "train": len(train),
            "validation": len(validation),
            "excluded": len(historical) - len(selected_entries),
        },
        "exclusions": excluded_ids,
        "warning_resolution": warning_resolution,
        "semantic_kind_disposition": kind_disposition,
        "components": {
            "full_graph_units": len(full_components),
            "eligible_units": len(candidate_components),
            "kept_units": len(candidate_components),
            "dev_overlap_excluded_units": len(protected_full_components),
            "train_units": len({entry.get("full_component_id") for entry in train}),
            "validation_units": len({entry.get("full_component_id") for entry in validation}),
            "largest_kept": max((component["size"] for component in candidate_components), default=0),
        },
        "checks": checks,
        "coverage": {
            "books": sorted({book for entry in selected_entries for book in (entry.get("source_scope") or [])}),
            "support_keys": len({key for entry in selected_entries for key in entry.get("support_keys") or []}),
            "context_keys": len({key for entry in selected_entries for key in entry.get("context_keys") or []}),
            "target_kinds": dict(Counter((entry.get("target") or {}).get("kind") for entry in selected_entries)),
            "task_kinds": dict(Counter((entry.get("semantic_review") or {}).get("task_kind") for entry in selected_entries)),
            "refusals": sum(1 for entry in selected_entries if (entry.get("target") or {}).get("kind") == "refusal"),
            "synthetic_rows": sum(1 for entry in selected_entries if any(str(scope).startswith("synthetic:") for scope in entry.get("source_scope") or [])),
            "mechanical_repair_required": sum(1 for entry in selected_entries if {issue["code"] for issue in entry.get("issues") or []} & {"source_formatting_drift", "source_normalized_only"}),
        },
        "dev_separation": {
            "dev_support_keys": sorted(dev_support),
            "dev_context_keys": sorted(dev_context),
            "excluded_support_components": len(excluded_by_reason_components.get("dev_support_component_overlap", set())),
            "excluded_context_components": len(excluded_by_reason_components.get("dev_context_component_overlap", set())),
            "excluded_full_components": len(excluded_by_reason_components.get("dev_full_component_overlap", set())),
            "excluded_support_rows": excluded_by_reason_rows.get("dev_support_component_overlap", 0),
            "excluded_context_rows": excluded_by_reason_rows.get("dev_context_component_overlap", 0),
            "excluded_full_rows": excluded_by_reason_rows.get("dev_full_component_overlap", 0),
            "protected_full_components": len(protected_full_components),
            "protected_full_rows": sum(protected_component_rows.values()),
            "protected_by_reason": {
                reason: {"components": protected_component_counts[reason], "rows": protected_component_rows[reason]}
                for reason in sorted(protected_component_counts)
            },
            "excluded_support_component_ids": sorted(excluded_by_reason_components.get("dev_support_component_overlap", set())),
            "excluded_context_component_ids": sorted(excluded_by_reason_components.get("dev_context_component_overlap", set())),
            "excluded_full_component_ids": sorted(excluded_by_reason_components.get("dev_full_component_overlap", set())),
            "claim": "answer-support, exact-text, and dev-family components are excluded at the FULL graph level; context-overlapping components are also excluded here",
            "context_only_familiarity": "Historical context-only overlap is reported separately; this candidate is not claimed completely unseen to the already shipped model.",
        },
        "membership": {
            "selected_ids_sha256": _sha_text(_canonical_json(sorted(entry["id"] for entry in selected_entries))),
            "train_ids_sha256": _sha_text(_canonical_json(sorted(entry["id"] for entry in train))),
            "validation_ids_sha256": _sha_text(_canonical_json(sorted(entry["id"] for entry in validation))),
            "selected_lines_sha256": _sha_text(_canonical_json(sorted(entry.get("line") for entry in selected_entries))),
        },
        "notes": [
            "Provisional reviewed-inputs candidate; not a certified GPU release.",
            "The shipped/legacy model may already have seen these sources; this is only a prospective fine-tune candidate, not an unseen set for the current model.",
            "No target, prompt, gloss, or source fact was repaired or rewritten.",
            "The 48 builder-gloss rows and the separate 12 follow-up review track are not merged into this candidate.",
            "Reserved, fair-locked, and sealed text was not used for selection.",
        ],
    }
    return {"manifest": manifest, "ledger": ledger, "payload": payload}


def _write_candidate(candidate, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "candidate-proposal.jsonl").open("w", encoding="utf-8") as handle:
        for record in candidate["payload"]:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with (out / "candidate-ledger.jsonl").open("w", encoding="utf-8") as handle:
        for row in candidate["ledger"]:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    candidate["manifest"]["artifacts"] = {
        "candidate_proposal_sha256": _sha_bytes((out / "candidate-proposal.jsonl").read_bytes()),
        "candidate_ledger_sha256": _sha_bytes((out / "candidate-ledger.jsonl").read_bytes()),
    }
    manifest_text = json.dumps(candidate["manifest"], ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (out / "candidate-manifest.json").write_text(manifest_text, encoding="utf-8")
    (out / "candidate-manifest.sha256").write_text(_sha_text(manifest_text) + "\n", encoding="utf-8")


def _load_baseline(path):
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["path"] = str(path)
    payload["sha256"] = _sha_bytes(Path(path).read_bytes())
    return payload


def _manifest(result, file_infos, protected, baseline=None):
    entries = result["entries"]
    populations = {}
    for role in sorted({entry.get("role") for entry in entries}):
        subset = [entry for entry in entries if entry.get("role") == role]
        populations[role or "unassigned"] = {
            "rows": len(subset),
            "mechanical": dict(Counter(entry["mechanical_status"] for entry in subset)),
            "splits": dict(Counter(entry["split"] for entry in subset)),
            "formats": dict(Counter(entry["format"] for entry in subset)),
            "support_rows": sum(1 for entry in subset if entry.get("support_keys")),
            "quote_free_gloss_rows": sum(1 for entry in subset if entry["target"].get("quote_free_gloss")),
            "refusal_rows": sum(1 for entry in subset if entry["target"].get("kind") == "refusal"),
            "dispositions": dict(Counter(entry.get("disposition") for entry in subset)),
            "components": _components(subset),
        }
    historical = [entry for entry in entries if entry.get("role") in ("historical_train", "derived_historical_train")]
    dev = [entry for entry in entries if entry.get("role") == "dev"]
    pending = [entry for entry in entries if entry.get("role") == "pending_review"]
    exposure = {
        "dev_vs_844": _exposure(entries, {"historical_train"}, {"dev"}) if dev else None,
        "dev_vs_777": _exposure(entries, {"derived_historical_train"}, {"dev"}) if dev else None,
        "dev_vs_historical_union": _exposure(entries, {"historical_train", "derived_historical_train"}, {"dev"}) if dev else None,
    }
    union_exposure = exposure.get("dev_vs_historical_union")
    baseline_manifest = None
    if baseline:
        selected = list(baseline.get("ids") or [])
        by_id = {entry.get("id"): entry for entry in entries}
        found_ids = [entry_id for entry_id in selected if entry_id in by_id]
        missing = [entry_id for entry_id in selected if entry_id not in by_id]
        support_exposed = set((union_exposure or {}).get("support_exposed_ids") or [])
        context_seen = set((union_exposure or {}).get("context_seen_ids") or [])
        baseline_manifest = {
            "path": baseline.get("path"),
            "sha256": baseline.get("sha256"),
            "status": baseline.get("status"),
            "scope": baseline.get("scope"),
            "selection_rule": baseline.get("selection_rule"),
            "selected": len(selected),
            "found": len(found_ids),
            "missing": missing,
            "dev_only": True,
            "unseen_claim": False,
            "gold_source_injection": False,
            "exposure": {
                entry_id: (
                    "support_exposed"
                    if entry_id in support_exposed
                    else ("context_seen" if entry_id in context_seen else "source_unseen_or_not_matched")
                )
                for entry_id in found_ids
            },
            "capture_status": "15 selections captured: 17 model calls plus 1 guard, source-prompt substring checks done; no grading yet",
            "note": "Frozen dev diagnostic slice, not an unseen test or model-selection holdout. Dev goldens are not changed by this audit.",
        }
    primary_dev = [
        {
            "path": info.get("path"),
            "sha256": info.get("sha256"),
            "rows": info.get("rows"),
            "review_status_counts": info.get("review_status_counts"),
            "role": "dev_reviewed",
        }
        for info in file_infos
        if info.get("role") == "dev"
    ]
    author_dev = [
        {
            "path": info.get("path"),
            "sha256": info.get("sha256"),
            "rows": info.get("rows"),
            "review_status_counts": info.get("review_status_counts"),
            "role": info.get("role"),
        }
        for info in result.get("reference_inputs") or []
        if info.get("role") == "dev_author_candidate"
    ]
    def status_phrase(counts):
        counts = counts or {}
        return ", ".join(f"{counts[key]} {key}" for key in sorted(counts)) or "no review statuses"

    primary_summary = "; ".join(
        f"{info['rows']} rows ({status_phrase(info.get('review_status_counts'))})" for info in primary_dev
    ) or "no primary reviewed dev file supplied"
    author_summary = "; ".join(
        f"{info['rows']} rows ({status_phrase(info.get('review_status_counts'))})" for info in author_dev
    ) or "no author candidate reference supplied"
    dev_review_source = {
        "primary": primary_dev,
        "author_candidate_reference": author_dev,
        "note": "reviewed-records.jsonl is the primary dev source; candidate-v2.jsonl is the author candidate and is not overwritten",
    }
    dev_decision = (
        f"DEV DIAGNOSTIC ONLY: primary reviewed file {primary_summary}; "
        f"author candidate {author_summary}; not a certified holdout"
    )
    dev_unknown = (
        f"primary dev review status comes from the reviewed file ({primary_summary}); "
        f"the author candidate is separate ({author_summary}) and is not the primary dev state"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "audit": "training_audit",
        "semantic_certification": "NOT CLAIMED",
        "config": {
            "seed": 20261029,
            "random_assignment": "none",
            "split_policy": "connected components over exact question, family, actual answer-support source, history referent, duplicate full input, and declared paraphrase; whole components only, never rows",
            "normalization": "NFKC + typographic fold + whitespace; case folding kept distinct from byte-literal",
            "similarity_thresholds": "none; no ML threshold is fitted or used for a verdict",
            "semantic_verdicts": "none; every row is REVIEW_NOT_CERTIFIED",
        },
        "inputs": file_infos,
        "reference_inputs": result.get("reference_inputs") or [],
        "dev_review_source": dev_review_source,
        "populations": populations,
        "exposure": exposure,
        "pending": {
            "rows": len(pending),
            "comparison_to_historical": _pending_compare(pending, historical, dev) if pending else None,
            "comparison_to_dev": _pending_compare(pending, dev, dev) if pending else None,
            "by_file": {
                Path(path).name: _pending_compare(
                    [entry for entry in pending if entry.get("source_path") == path],
                    historical,
                    dev,
                )
                for path in sorted({entry.get("source_path") for entry in pending})
            },
        },
        "split_findings": result["split_findings"],
        "context_overlaps": result["context_overlaps"],
        "decisions": {
            "historical_train_844": "HISTORICAL TRAIN, content verified with the original CRLF line endings; weight-to-data tie UNVERIFIED; never an evaluation or holdout set",
            "derived_clean_777": "DERIVED HISTORICAL TRAIN, order-preserving exact message subset; NOT a clean held-out set, and the old decontamination list did not include the 86 dev batch",
            "dev_86": dev_decision,
            "pending_assets": "REVIEW ONLY; not train-ready; reconstructed highlights are redundant with the 844 and authored follow-ups sit on already-trained sources",
            "prospective_holdout": "NONE certified; a future candidate must be a new component outside every historical support/context component and must be independently reviewed",
            "current_model": "The current weights saw the historical corpus. Renaming a split cannot make those examples unseen to the current model.",
            "no_train_export": "No train-ready export is produced while any target or required fact remains unreviewed.",
        },
        "baseline_selection": baseline_manifest,
        "semantic_review": {
            "shards": result.get("semantic_reviews") or [],
            "shards_expected": ["A", "B"],
            "missing_review_ids": [
                entry.get("id")
                for entry in entries
                if entry.get("role") == "historical_train" and not entry.get("semantic_review")
            ],
            "duplicate_review_ids": sorted(
                {
                    entry_id
                    for shard in result.get("semantic_reviews") or []
                    for entry_id in shard.get("duplicate_ids") or []
                }
            ),
            "denominator": sum(1 for entry in entries if entry.get("role") == "historical_train"),
            "decision_counts": dict(
                Counter(
                    (entry.get("semantic_review") or {}).get("decision")
                    for entry in entries
                    if entry.get("role") == "historical_train" and entry.get("semantic_review")
                )
            ),
            "canonical_binding": "PENDING_INDEPENDENT_FINAL_BIND after split metadata is frozen; canonical review_digest is not the original messages digest",
            "train_ready": False,
        },
        "authored_followups_review": {
            "rows": 12,
            "status": "final accepted",
            "path": "artifacts/runs/data-release-2026-10-29/training-review/final-reviewed-v3.jsonl",
            "sha256": "e2449c2d7829dd2ebca35a383af1510a47ef0c3d709357fe354b92948ab228ed",
            "source_refs_parent_verified": 39,
            "separate_track": True,
            "merged_into_pending": False,
            "train_ready": False,
            "note": "latest final accepted follow-up review; not merged with the 48 builder-gloss reconstruction and not approved for training",
        },
        "comparison_repairs_8": {
            "rows": 8,
            "status": "all 8 accepted in final-reviewed-v2",
            "path": "artifacts/runs/data-release-2026-10-29/comparison-review/final-reviewed-v2.jsonl",
            "sha256": "beab7e1377bed464951d556ade592eb2cac1ef99235d7608a69658c7d19a3b1c",
            "parent_check": "artifacts/runs/data-release-2026-10-29/comparison-review/parent-final-v2-check.json",
            "retained_six_byte_identical": True,
            "source_spans_parent_checked": 37,
            "separate_track": True,
            "merged_into_pending": False,
            "train_ready": False,
            "note": "target-only replacement track; the next assembly must use these 8 as replacements of old bad targets, not append both old and new. Original bad targets stay preserved but excluded from release.",
        },
        "protected_sets": list(protected),
        "unknowns": [
            "semantic truth of target glosses, required facts, and refusal answerability is not certified; no model or judge was called",
            "weight-to-data tie for the adopted 844 is unverified; line-ending equivalence is not a training-lineage proof",
            "near-paraphrase and weak semantic leakage are heuristics only; zero semantic leakage is not claimed",
            dev_unknown,
            "reserved/fair-locked/sealed text was not opened",
            "the FTS5 runtime defect and live HTTP behaviour were not measured by this audit",
        ],
        "summary": result["summary"],
    }


def audit_files(
    paths,
    *,
    out_dir=None,
    index_paths=None,
    catalog_path=None,
    roles=None,
    dataset_name=None,
    protected=None,
    baseline_selection_path=None,
    semantic_review_paths=None,
    reference_inputs=None,
    candidate_out=None,
    candidate_seed=20261030,
    candidate_validation_percent=10,
    date=None,
):
    books = load_books(index_paths=index_paths, catalog_path=catalog_path)
    entries = []
    records_by_id = {}
    file_infos = []
    for item in paths:
        if isinstance(item, dict):
            path = item["path"]
            explicit_role = item.get("role")
            id_prefix = item.get("id_prefix")
            shard_boundary = item.get("shard_boundary")
        else:
            path = item
            explicit_role = None
            id_prefix = None
            shard_boundary = None
        if roles and path in roles:
            explicit_role = roles[path]
        rows, info = _read_jsonl(path)
        info["role"] = explicit_role
        info["id_prefix"] = id_prefix
        info["shard_boundary"] = shard_boundary
        file_infos.append(info)
        status_counts = Counter()
        for row in rows:
            context = {
                "path": str(path),
                "line": row["line"],
                "raw_line_sha256": row["raw_line_sha256"],
                "line_sha256_with_lf": _sha_bytes(row["raw"] + b"\n"),
                "file_sha256": info["sha256"],
                "id_prefix": id_prefix,
                "shard_boundary": shard_boundary,
            }
            try:
                record = json.loads(row["text"])
            except ValueError as error:
                entry = _audit_one({}, books, context)
                entry["issues"] = [_issue("json_parse_error", "FAIL", str(error), "schema")]
                entry["mechanical_status"] = "FAIL"
                entry["role"] = _role_for(path, entry, explicit_role)
                entry["disposition"] = "parse_error"
                entries.append(entry)
                continue
            status = ((record.get("review") or {}).get("status"))
            if status:
                status_counts[status] += 1
            entry = _audit_one(record, books, context)
            entry["role"] = _role_for(path, entry, explicit_role)
            entry["disposition"] = _disposition(entry)
            entries.append(entry)
            records_by_id[entry["id"]] = record
        info["review_status_counts"] = dict(status_counts)
    baseline = _load_baseline(baseline_selection_path)
    if baseline:
        selected = set(baseline.get("ids") or [])
        for entry in entries:
            entry["baseline_selected"] = entry.get("id") in selected
    reference_infos = []
    for item in reference_inputs or []:
        if isinstance(item, dict):
            ref_path = item["path"]
            ref_role = item.get("role") or "reference"
        else:
            ref_path = item
            ref_role = "reference"
        ref_rows, ref_info = _read_jsonl(ref_path)
        ref_info["role"] = ref_role
        statuses = Counter()
        for ref_row in ref_rows:
            try:
                ref_record = json.loads(ref_row["text"])
            except ValueError:
                continue
            status = ((ref_record.get("review") or {}).get("status"))
            if status:
                statuses[status] += 1
        ref_info["review_status_counts"] = dict(statuses)
        reference_infos.append(ref_info)
    semantic_reviews = []
    seen_review_ids = set()
    for item in semantic_review_paths or []:
        if isinstance(item, dict):
            review_path = item["path"]
            shard = item.get("shard") or "A"
            expected_sha = item.get("expected_sha256")
        else:
            review_path = item
            shard = "A"
            expected_sha = None
        semantic_reviews.append(
            _bind_semantic_review(
                entries,
                review_path,
                shard,
                records_by_id,
                books,
                seen_review_ids,
                expected_sha256=expected_sha,
            )
        )
    _assign_components(entries)
    candidate = None
    if candidate_out:
        candidate = build_candidate(
            entries,
            [entry for entry in entries if entry.get("role") == "dev"],
            records_by_id,
            seed=candidate_seed,
            validation_percent=candidate_validation_percent,
        )
        _write_candidate(candidate, candidate_out)
    findings, overlaps = _split_findings(entries)
    result = {
        "schema_version": SCHEMA_VERSION,
        "dataset": dataset_name or str(paths[0]) if paths else "<memory>",
        "entries": entries,
        "summary": _summary(entries),
        "split_findings": findings,
        "context_overlaps": overlaps,
        "components": _components(entries),
        "review_queue": _review_queue(entries),
        "semantic_reviews": semantic_reviews,
        "reference_inputs": reference_infos,
        "candidate": candidate["manifest"] if candidate else None,
    }
    result["manifest"] = _manifest(result, file_infos, protected or PROTECTED_DEFAULT, baseline)
    result["manifest"]["candidate"] = candidate["manifest"] if candidate else None
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        def dump(name, rows):
            with (out / name).open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        dump("ledger.jsonl", entries)
        dump("review-queue.jsonl", result["review_queue"])
        dump("split-findings.jsonl", findings)
        dump("context-overlaps.jsonl", overlaps)
        dump("components.jsonl", _population_components(entries))
        dump("repair-ledger.jsonl", _repair_candidates(entries))
        (out / "manifest.json").write_text(json.dumps(result["manifest"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _repair_candidates(entries):
    rows = []
    for entry in entries:
        for binding in entry.get("source_bindings") or []:
            if binding.get("resolution") in ("formatting_drift", "normalized_only"):
                rows.append(
                    {
                        "id": entry.get("id"),
                        "source_path": entry.get("source_path"),
                        "line": entry.get("line"),
                        "chunk_id": binding.get("chunk_id"),
                        "book_id": binding.get("book_id"),
                        "kind": binding.get("resolution"),
                        "applied": False,
                        "reason": "mechanical source-text drift; original row preserved; no target or gloss is rewritten",
                        "before_text_sha256": binding.get("provided_text_sha256"),
                        "after_text_sha256": binding.get("text_sha256"),
                    }
                )
    return rows


def _print_summary(result):
    summary = dict(result["summary"])
    summary["manifest_decisions"] = result.get("manifest", {}).get("decisions", {})
    summary["split_findings"] = len(result.get("split_findings") or [])
    summary["context_overlaps"] = len(result.get("context_overlaps") or [])
    exposure = (result.get("manifest") or {}).get("exposure") or {}
    summary["exposure"] = {
        key: {
            "support_exposed": value.get("dev_support_exposed"),
            "context_seen": value.get("dev_context_seen"),
            "source_unseen": value.get("dev_source_unseen"),
            "exact_question_collisions": value.get("dev_exact_question_collisions"),
        }
        for key, value in exposure.items()
        if value
    }
    candidate = (result.get("manifest") or {}).get("candidate")
    if candidate:
        summary["candidate"] = {
            "status": candidate.get("status"),
            "ready_for_training": candidate.get("ready_for_training"),
            "selected": candidate["counts"]["selected"],
            "train": candidate["counts"]["train"],
            "validation": candidate["counts"]["validation"],
            "excluded": candidate["counts"]["excluded"],
            "validation_percent_achieved": candidate.get("validation_percent_achieved"),
            "checks": candidate.get("checks"),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline training-data ledger, split manifest, and review queue.")
    parser.add_argument("--input", action="append", default=[], help="historical training JSONL (repeatable)")
    parser.add_argument("--dataset", action="append", default=[], help="eval or pending JSONL (repeatable)")
    parser.add_argument("--index", action="append", default=[], help="index JSON (repeatable); defaults to --catalog")
    parser.add_argument("--catalog", default=str(ROOT / "data" / "books.json"), help="books.json catalog")
    parser.add_argument("--role", action="append", default=[], help="PATH=ROLE override (repeatable)")
    parser.add_argument("--id-prefix", action="append", default=[], help="PATH=PREFIX stable id prefix (repeatable)")
    parser.add_argument("--shard-boundary", action="append", default=[], help="PATH=LINE split ids into A/B at this physical line (repeatable)")
    parser.add_argument("--out", help="write ledger, manifest, review queue, and repair ledger here")
    parser.add_argument("--baseline-selection", default=None, help="frozen dev baseline-selection JSON (metadata only)")
    parser.add_argument("--semantic-review", action="append", default=[], help="PATH=SHARD independent semantic ledger (repeatable)")
    parser.add_argument("--combined-review-check", default=None, help="frozen combined-review-check.json with expected shard hashes")
    parser.add_argument("--reference", action="append", default=[], help="PATH=ROLE metadata-only input (repeatable)")
    parser.add_argument("--candidate-out", default=None, help="write a provisional reviewed-inputs candidate here")
    parser.add_argument("--candidate-seed", type=int, default=20261030)
    parser.add_argument("--candidate-validation-percent", type=float, default=10.0)
    parser.add_argument("--dataset-name", default=None)
    parser.add_argument("--date", default=None)
    args = parser.parse_args(argv)

    def mapping(values, label):
        out = {}
        for item in values:
            if "=" not in item:
                parser.error(f"{label} expects PATH=VALUE, got {item!r}")
            path, value = item.rsplit("=", 1)
            out[path] = value
        return out

    roles = mapping(args.role, "--role")
    prefixes = mapping(args.id_prefix, "--id-prefix")
    boundaries = {path: int(value) for path, value in mapping(args.shard_boundary, "--shard-boundary").items()}
    expected_by_shard = {}
    if args.combined_review_check:
        check = json.loads(Path(args.combined_review_check).read_text(encoding="utf-8"))
        expected_by_shard = {
            str(part.get("shard", "")).upper(): part.get("sha256")
            for part in check.get("parts") or []
            if part.get("sha256")
        }
    semantic_reviews = [
        {"path": path, "shard": shard, "expected_sha256": expected_by_shard.get(str(shard).upper())}
        for path, shard in mapping(args.semantic_review, "--semantic-review").items()
    ]
    references = [{"path": path, "role": role} for path, role in mapping(args.reference, "--reference").items()]
    paths = []
    for path in args.input:
        paths.append(
            {
                "path": path,
                "role": "historical_train",
                "id_prefix": prefixes.get(path),
                "shard_boundary": boundaries.get(path),
            }
        )
    for path in args.dataset:
        paths.append(
            {
                "path": path,
                "role": None,
                "id_prefix": prefixes.get(path),
                "shard_boundary": boundaries.get(path),
            }
        )
    if not paths:
        parser.error("give at least one --input or --dataset")
    result = audit_files(
        paths,
        out_dir=args.out,
        index_paths=args.index or None,
        catalog_path=args.catalog if not args.index else None,
        roles=roles,
        dataset_name=args.dataset_name,
        baseline_selection_path=args.baseline_selection,
        semantic_review_paths=semantic_reviews,
        reference_inputs=references,
        candidate_out=args.candidate_out,
        candidate_seed=args.candidate_seed,
        candidate_validation_percent=args.candidate_validation_percent,
        date=args.date,
    )
    _print_summary(result)
    if result["summary"]["mechanical_fail"]:
        return 2
    if (
        result["summary"]["mechanical_review"]
        or result["summary"]["semantic_review_required"]
        or result["summary"]["canonical_bind_pending"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
