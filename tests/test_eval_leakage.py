"""No eval question may appear in the finetune corpus without an explicit allowlist.

Why this test exists: the training files were authored from the same books the
eval sets score, so question overlap is the way a "hold-out" quietly stops
being held out. `qa-questions-overnight.json` was the historical proof — 81 of
its 124 questions were verbatim training rows, so it cannot be a test.

Rules asserted here:

1. `sealed-2026-10-24.jsonl` matches its frozen sha256. Changing the set is a
   deliberate act, and this test is the tripwire.
2. Every eval set (sealed, hard-mt, hard-bench, highlight-golden, adrian, crossbook)
   is checked against EVERY training corpus under data/finetune/.
3. Known overlaps (such as sealed-def-02 'What is data lineage?' in train-x3) are
   strictly tracked in KNOWN_LEAKS. Any NEW leak fails. Any STALE allowlist entry fails.
4. Gold chunk passage overlap is tracked per eval set via a strict ratchet asserting
   that passage overlap does not exceed measured baselines. Training-row source
   chunks only count from answer rows; refusal-distractor passages are excluded.
5. `qa-questions-overnight.json` is not listed as a sealed eval surface.

The training files are gitignored. On a machine without them the corpus checks
skip; the sha256 freeze still runs.
"""

import difflib
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINETUNE = ROOT / "data" / "finetune"
TRAIN = FINETUNE / "quote-refuse-2026-10-17.train-x3.jsonl"
DATASETS = ROOT / "artifacts" / "datasets"
SEALED = DATASETS / "sealed-2026-10-24.jsonl"
SEALED_SHA256 = "24fcc1c9138e158d26891a88bb07d5ef1e9eeb21bcbe137aa40d00961404d0d7"

NEAR_RATIO = 0.85
# Short questions are string-similar without asking the same thing:
# "what is replication" vs "what is location" scores 0.857. A near-duplicate
# must also share its content words, so both guards apply.
NEAR_CONTENT_JACCARD = 0.7
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can",
}

TRAINING_DERIVED = {"qa-questions-overnight.json"}

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
HIGHLIGHT_RE = re.compile(r"^Highlighted text:\s*(.+?)(?:\n|$)", re.M)

# Training corpora under data/finetune/ identified from reports and schema:
# train-x2f, train-x3, train-r3, train-r4, train-r5, history, trap rows, etc.
TRAINING_CORPORA_FILENAMES = [
    "quote-refuse-2026-10-16.train-x2f.jsonl",
    "quote-refuse-2026-10-17.train-x3.jsonl",
    "quote-refuse-2026-10-24.train-r3.jsonl",
    "quote-refuse-2026-10-24.train-r4.jsonl",
    "quote-refuse-2026-10-25.train-r5.jsonl",
    "quote-refuse-2026-10-24.history.jsonl",
    "trap-crossbook-rows-2026-10-24.jsonl",
    "quote-refuse-2026-10-16.train-x2g.jsonl",
    "quote-refuse-2026-10-15.train-x2e.jsonl",
    "quote-refuse-2026-10-13.train-x2d.jsonl",
]

# Explicit, documented allowlist of known overlaps keyed by (eval id, corpus filename)
KNOWN_LEAKS = {
    # Sealed set: sealed-def-02 ('What is data lineage?') was included as training row 299 in train-x3
    ("sealed-def-02", "quote-refuse-2026-10-15.train-x2e.jsonl"): "What is data lineage? introduced in x2e",
    ("sealed-def-02", "quote-refuse-2026-10-16.train-x2g.jsonl"): "What is data lineage? present in x2g",
    ("sealed-def-02", "quote-refuse-2026-10-17.train-x3.jsonl"): "What is data lineage? row 299 in adopted train-x3",
    ("sealed-def-02", "quote-refuse-2026-10-24.train-r3.jsonl"): "What is data lineage? inherited in candidate R3",
    ("sealed-def-02", "quote-refuse-2026-10-24.train-r4.jsonl"): "What is data lineage? inherited in candidate R4",
    ("sealed-def-02", "quote-refuse-2026-10-25.train-r5.jsonl"): "What is data lineage? inherited in candidate R5",

    # Adrian set: conversational turns and specific topics
    ("adrian-18", "quote-refuse-2026-10-16.train-x2f.jsonl"): "What is change data capture? in x2f",
    ("adrian-18", "quote-refuse-2026-10-13.train-x2d.jsonl"): "What is change data capture? in x2d",
    ("adrian-03", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'why?' in x2e",
    ("adrian-03", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'why?' in x2g",
    ("adrian-03", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'why?' in train-x3",
    ("adrian-03", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'why?' in R3",
    ("adrian-03", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'why?' in R4",
    ("adrian-03", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'why?' in R5",
    ("adrian-04", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-ups 'why?' / 'how does this work' in x2e",
    ("adrian-04", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-ups 'why?' / 'how does this work' in x2g",
    ("adrian-04", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-ups 'why?' / 'how does this work' in train-x3",
    ("adrian-04", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-ups 'why?' / 'how does this work' in R3",
    ("adrian-04", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-ups 'why?' / 'how does this work' in R4",
    ("adrian-04", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-ups 'why?' / 'how does this work' in R5",
    ("adrian-11", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'why' in x2e",
    ("adrian-11", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'why' in x2g",
    ("adrian-11", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'why' in train-x3",
    ("adrian-11", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'why' in R3",
    ("adrian-11", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'why' in R4",
    ("adrian-11", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'why' in R5",
    ("adrian-12", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'how does this work' in x2e",
    ("adrian-12", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'how does this work' in x2g",
    ("adrian-12", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'how does this work' in train-x3",
    ("adrian-12", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'how does this work' in R3",
    ("adrian-12", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'how does this work' in R4",
    ("adrian-12", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'how does this work' in R5",
    ("adrian-16", "quote-refuse-2026-10-15.train-x2e.jsonl"): "What is ddr5 / RAM in x2e",
    ("adrian-16", "quote-refuse-2026-10-16.train-x2g.jsonl"): "What is ddr5 / RAM in x2g",
    ("adrian-16", "quote-refuse-2026-10-17.train-x3.jsonl"): "What is ddr5 / RAM in train-x3",
    ("adrian-16", "quote-refuse-2026-10-24.train-r3.jsonl"): "What is ddr5 / RAM in R3",
    ("adrian-16", "quote-refuse-2026-10-24.train-r4.jsonl"): "What is ddr5 / RAM in R4",
    ("adrian-16", "quote-refuse-2026-10-25.train-r5.jsonl"): "What is ddr5 / RAM in R5",
    ("adrian-17", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Stages of data engineering lifecycle in x2e",
    ("adrian-17", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Stages of data engineering lifecycle in x2g",
    ("adrian-17", "quote-refuse-2026-10-17.train-x3.jsonl"): "Stages of data engineering lifecycle in train-x3",
    ("adrian-17", "quote-refuse-2026-10-24.train-r3.jsonl"): "Stages of data engineering lifecycle in R3",
    ("adrian-17", "quote-refuse-2026-10-24.train-r4.jsonl"): "Stages of data engineering lifecycle in R4",
    ("adrian-17", "quote-refuse-2026-10-25.train-r5.jsonl"): "Stages of data engineering lifecycle in R5",
    ("adrian-18", "quote-refuse-2026-10-15.train-x2e.jsonl"): "What is change data capture? / how does it work in x2e",
    ("adrian-18", "quote-refuse-2026-10-16.train-x2g.jsonl"): "What is change data capture? / how does it work in x2g",
    ("adrian-18", "quote-refuse-2026-10-17.train-x3.jsonl"): "What is change data capture? / how does it work in train-x3",
    ("adrian-18", "quote-refuse-2026-10-24.train-r3.jsonl"): "What is change data capture? / how does it work in R3",
    ("adrian-18", "quote-refuse-2026-10-24.train-r4.jsonl"): "What is change data capture? / how does it work in R4",
    ("adrian-18", "quote-refuse-2026-10-25.train-r5.jsonl"): "What is change data capture? / how does it work in R5",
    ("adrian-24", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-ups 'Why?' / 'How?' in x2e",
    ("adrian-24", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-ups 'Why?' / 'How?' in x2g",
    ("adrian-24", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-ups 'Why?' / 'How?' in train-x3",
    ("adrian-24", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-ups 'Why?' / 'How?' in R3",
    ("adrian-24", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-ups 'Why?' / 'How?' in R4",
    ("adrian-24", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-ups 'Why?' / 'How?' in R5",
    ("adrian-34", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'why does it matter?' in x2e",
    ("adrian-34", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'why does it matter?' in x2g",
    ("adrian-34", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'why does it matter?' in train-x3",
    ("adrian-34", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'why does it matter?' in R3",
    ("adrian-34", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'why does it matter?' in R4",
    ("adrian-34", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'why does it matter?' in R5",

    # Crossbook set: conversational follow-ups
    ("crossbook-13", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'why?' in x2e",
    ("crossbook-13", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'why?' in x2g",
    ("crossbook-13", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'why?' in train-x3",
    ("crossbook-13", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'why?' in R3",
    ("crossbook-13", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'why?' in R4",
    ("crossbook-13", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'why?' in R5",
    ("crossbook-14", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'why does this matter' in x2e",
    ("crossbook-14", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'why does this matter' in x2g",
    ("crossbook-14", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'why does this matter' in train-x3",
    ("crossbook-14", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'why does this matter' in R3",
    ("crossbook-14", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'why does this matter' in R4",
    ("crossbook-14", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'why does this matter' in R5",
    ("crossbook-16", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'why?' in x2e",
    ("crossbook-16", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'why?' in x2g",
    ("crossbook-16", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'why?' in train-x3",
    ("crossbook-16", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'why?' in R3",
    ("crossbook-16", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'why?' in R4",
    ("crossbook-16", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'why?' in R5",
    ("crossbook-17", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Conversational follow-up 'how does this work' in x2e",
    ("crossbook-17", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Conversational follow-up 'how does this work' in x2g",
    ("crossbook-17", "quote-refuse-2026-10-17.train-x3.jsonl"): "Conversational follow-up 'how does this work' in train-x3",
    ("crossbook-17", "quote-refuse-2026-10-24.train-r3.jsonl"): "Conversational follow-up 'how does this work' in R3",
    ("crossbook-17", "quote-refuse-2026-10-24.train-r4.jsonl"): "Conversational follow-up 'how does this work' in R4",
    ("crossbook-17", "quote-refuse-2026-10-25.train-r5.jsonl"): "Conversational follow-up 'how does this work' in R5",

    # Highlight golden set: near-duplicates resulting from template question structure
    ("ch01-065:data", "quote-refuse-2026-10-13.train-x2d.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-16.train-x2f.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-17.train-x3.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-24.train-r3.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-24.train-r4.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch01-065:data", "quote-refuse-2026-10-25.train-r5.jsonl"): "Near template match on 'What is data in Chief technology officer?'",
    ("ch02-007:state", "quote-refuse-2026-10-17.train-x3.jsonl"): "Near template match on 'What is state in Evaluating source systems...'",
    ("ch02-007:state", "quote-refuse-2026-10-24.train-r3.jsonl"): "Near template match on 'What is state in Evaluating source systems...'",
    ("ch02-007:state", "quote-refuse-2026-10-24.train-r4.jsonl"): "Near template match on 'What is state in Evaluating source systems...'",
    ("ch02-007:state", "quote-refuse-2026-10-25.train-r5.jsonl"): "Near template match on 'What is state in Evaluating source systems...'",
    ("ch02-085:source", "quote-refuse-2026-10-16.train-x2f.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch02-085:source", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch02-085:source", "quote-refuse-2026-10-17.train-x3.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch02-085:source", "quote-refuse-2026-10-24.history.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch02-085:source", "quote-refuse-2026-10-24.train-r3.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch02-085:source", "quote-refuse-2026-10-24.train-r4.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch02-085:source", "quote-refuse-2026-10-25.train-r5.jsonl"): "Near template match on 'What is source in Development of open source frameworks?'",
    ("ch07-049:load", "quote-refuse-2026-10-13.train-x2d.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-15.train-x2e.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-16.train-x2f.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-16.train-x2g.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-17.train-x3.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-24.train-r3.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-24.train-r4.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
    ("ch07-049:load", "quote-refuse-2026-10-25.train-r5.jsonl"): "Near template match on 'What is load in Direct Database Connection?'",
}

# Measured passage-overlap ratchet limits against training source passages:
# Assert that gold chunk overlap never exceeds these measured maximums.
MAX_SOURCE_PASSAGE_OVERLAPS = {
    "sealed-2026-10-24.jsonl": 3,           # 3 / 27 (11.1%) answer items
    "hard-bench-2026-10-17.jsonl": 24,       # 24 / 37 (64.9%) in-book answer items
    "highlight-golden-2026-10-16.jsonl": 5,  # 5 / 24 (20.8%) items
    "hard-mt-2026-10-24.jsonl": 1,           # 1 / 9 (11.1%) answer items (mt-elision-01)
    "wide-net-2026-10-23.jsonl": 9,          # 9 / 57 (15.8%) items
    "crossbook-evil-eval-2026-10-18.json": 0,# 0 / 20 (0.0%) scenarios
    "adrian-realworld-eval-2026-10-17.json": 7, # 7 / 30 (23.3%) scenarios
}


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(folded):
    return {word for word in folded.split() if word not in STOPWORDS}


def extract_train_questions(path):
    questions = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if "messages" in record:
                user = next(
                    (m.get("content") or "" for m in record.get("messages", [])
                     if m.get("role") == "user"),
                    "",
                )
                qm = QUESTION_RE.search(user)
                if qm:
                    questions.append(fold(qm.group(1)))
                hm = HIGHLIGHT_RE.search(user)
                if hm:
                    questions.append(fold(hm.group(1)))
                meta = record.get("meta") or {}
                if meta.get("question"):
                    questions.append(fold(meta["question"]))
                if meta.get("asked"):
                    questions.append(fold(meta["asked"]))
            elif "q" in record:
                questions.append(fold(record["q"]))
            elif "question" in record:
                questions.append(fold(record["question"]))
    return questions


def train_questions(path=TRAIN):
    return extract_train_questions(path)


def get_source_chunks_strict(row):
    """Training-row source chunks only (NOT the refusal-distractor passages in refusal rows)."""
    asst = next((m.get("content") or "" for m in row.get("messages", []) if m.get("role") == "assistant"), "")
    if asst.strip() == "Not in this book.":
        return set()
    meta = row.get("meta") or {}
    cited = list(meta.get("cited") or [])
    if meta.get("chunk_id"):
        cited.append(meta["chunk_id"])
    if meta.get("pin"):
        cited.append(meta["pin"])
    if not cited:
        user = next((m.get("content") or "" for m in row.get("messages", []) if m.get("role") == "user"), "")
        qm = re.search(r'"([^"]{10,})"', asst)
        if qm:
            quote = qm.group(1).strip()
            for cid, ptext in re.findall(r"chunk_id=(\S+)\s*\n(.*?)(?=\n\[Ch|\Z)", user, re.S):
                if quote[:30] in ptext:
                    cited.append(cid)
                    break
    return set(cited)


def load_train_source_chunks(path=TRAIN):
    if not path.is_file():
        return set()
    chunks = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                chunks.update(get_source_chunks_strict(row))
    return chunks


def jsonl_questions(path):
    items = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            question = record.get("question") or record.get("prompt") or ""
            if not question and record.get("selection"):
                question = "[selection] " + record["selection"]
            if not question and record.get("meta", {}).get("asked"):
                question = record["meta"]["asked"]
            if not question and record.get("meta", {}).get("selection"):
                question = "[selection] " + record["meta"]["selection"]
            item_id = record.get("id")
            if not item_id and "meta" in record:
                item_id = f"{record['meta'].get('chunk_id')}:{record['meta'].get('selection')}"
            if question:
                items.append((item_id, question))
    return items


def scenario_questions(path):
    items = []
    with path.open(encoding="utf-8") as fh:
        for scenario in json.load(fh):
            for turn in scenario.get("turns") or []:
                question = turn.get("question") or ""
                if not question and turn.get("selection"):
                    question = "[selection] " + turn["selection"]
                if question:
                    items.append((scenario.get("id"), question))
    return items


def adrian_questions(path=DATASETS / "adrian-realworld-eval-2026-10-17.json"):
    return scenario_questions(path)


def crossbook_questions(path=DATASETS / "crossbook-evil-eval-2026-10-18.json"):
    return scenario_questions(path)


def leaks(questions, corpus):
    """[(id, question, kind)] where kind is 'exact' or 'near <ratio>'."""
    found = []
    corpus_entries = [(text, content(text)) for text in corpus]
    corpus_set = set(corpus)
    for item_id, question in questions:
        folded = fold(question)
        if not folded:
            continue
        if folded in corpus_set:
            found.append((item_id, question, "exact"))
            continue
        words = content(folded)
        if not words:
            continue
        best = 0.0
        for text, text_words in corpus_entries:
            if not text_words:
                continue
            overlap = len(words & text_words) / len(words | text_words)
            if overlap < NEAR_CONTENT_JACCARD:
                continue
            best = max(best, difflib.SequenceMatcher(None, folded, text).ratio())
        if best >= NEAR_RATIO:
            found.append((item_id, question, f"near {best:.3f}"))
    return found


def existing_training_corpora():
    """Return all training corpora files present on this machine."""
    corpora = []
    for fname in TRAINING_CORPORA_FILENAMES:
        p = FINETUNE / fname
        if p.is_file():
            corpora.append(p)
    return corpora


class SealedSetTest(unittest.TestCase):
    def test_sealed_sha256_is_frozen(self):
        self.assertTrue(SEALED.is_file(), f"missing {SEALED}")
        digest = hashlib.sha256(SEALED.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        self.assertEqual(
            digest,
            SEALED_SHA256,
            "sealed-2026-10-24.jsonl changed. If that was deliberate, update the "
            "constant here and in artifacts/harnesses/sealed-eval.py, and re-run "
            "the leakage audit.",
        )

    def test_sealed_set_has_no_training_overlap(self):
        self.assertTrue(SEALED.is_file())
        items = jsonl_questions(SEALED)
        self.assertEqual(len(items), 30, "sealed set size changed")
        ids = [item_id for item_id, _ in items]
        self.assertEqual(len(ids), len(set(ids)), "duplicate sealed ids")

        corpora = existing_training_corpora()
        if not corpora:
            self.skipTest("training corpora not on this machine (data/ is gitignored)")

        observed_allowlisted = set()
        for cpath in corpora:
            cname = cpath.name
            corpus_q = extract_train_questions(cpath)
            found = leaks(items, corpus_q)
            for item_id, question, kind in found:
                key = (item_id, cname)
                self.assertIn(
                    key,
                    KNOWN_LEAKS,
                    f"New sealed leak found: {item_id} ({kind}: {question!r}) in {cname}. "
                    "Sealed questions must be strictly held out.",
                )
                observed_allowlisted.add(key)

        # Stale allowlist entry check for sealed set:
        for (item_id, cname), reason in KNOWN_LEAKS.items():
            if str(item_id).startswith("sealed-") and (FINETUNE / cname).is_file():
                self.assertIn(
                    (item_id, cname),
                    observed_allowlisted,
                    f"Stale KNOWN_LEAKS entry for sealed: ({item_id!r}, {cname!r}) was not observed in data.",
                )

    def test_shipped_benchmarks_have_no_training_overlap(self):
        corpora = existing_training_corpora()
        if not corpora:
            self.skipTest("training corpora not on this machine (data/ is gitignored)")

        for cpath in corpora:
            corpus = extract_train_questions(cpath)
            for name in ("hard-bench-2026-10-17.jsonl", "wide-net-2026-10-23.jsonl", "hard-mt-2026-10-24.jsonl"):
                found = leaks(jsonl_questions(DATASETS / name), corpus)
                self.assertEqual(
                    found,
                    [],
                    f"{name} leaks training rows in {cpath.name}: {found}",
                )

    def test_all_eval_sets_question_overlap_guarded(self):
        """Generalized leak check for all eval sets against EVERY training corpus."""
        corpora = existing_training_corpora()
        if not corpora:
            self.skipTest("training corpora not on this machine (data/ is gitignored)")

        eval_sets = {
            "sealed": jsonl_questions(DATASETS / "sealed-2026-10-24.jsonl"),
            "hard-mt": jsonl_questions(DATASETS / "hard-mt-2026-10-24.jsonl"),
            "hard-bench": jsonl_questions(DATASETS / "hard-bench-2026-10-17.jsonl"),
            "highlight-golden": jsonl_questions(DATASETS / "highlight-golden-2026-10-16.jsonl"),
            "adrian": adrian_questions(),
            "crossbook": crossbook_questions(),
        }

        observed_allowlisted = set()
        for cpath in corpora:
            cname = cpath.name
            corpus_q = extract_train_questions(cpath)
            for ename, items in eval_sets.items():
                found = leaks(items, corpus_q)
                for item_id, question, kind in found:
                    key = (item_id, cname)
                    self.assertIn(
                        key,
                        KNOWN_LEAKS,
                        f"New unallowlisted leak in {ename}: item {item_id!r} ({kind} on {question!r}) in {cname}.",
                    )
                    observed_allowlisted.add(key)

        # Stale allowlist guard: fail if any entry in KNOWN_LEAKS disappears from a present corpus
        for (item_id, cname), reason in KNOWN_LEAKS.items():
            if (FINETUNE / cname).is_file():
                self.assertIn(
                    (item_id, cname),
                    observed_allowlisted,
                    f"Stale KNOWN_LEAKS entry: ({item_id!r}, {cname!r}) was not observed in {cname}.",
                )

    def test_adrian_has_only_the_known_leak(self):
        corpora = existing_training_corpora()
        if not corpora:
            self.skipTest("training corpora not on this machine (data/ is gitignored)")

        items = adrian_questions()
        for cpath in corpora:
            cname = cpath.name
            corpus_q = extract_train_questions(cpath)
            found = leaks(items, corpus_q)
            for item_id, question, kind in found:
                key = (item_id, cname)
                self.assertIn(
                    key,
                    KNOWN_LEAKS,
                    f"Unexpected leak in adrian set: {item_id} in {cname} ({kind}: {question!r})",
                )

    def test_passage_overlap_ratchet(self):
        """Records gold chunk passage overlap against training source passages and asserts ratchet."""
        if not TRAIN.is_file():
            self.skipTest("adopted training corpus train-x3 not on disk")

        source_chunks = load_train_source_chunks(TRAIN)
        self.assertGreater(len(source_chunks), 100, "source chunks failed to load")

        def count_overlaps(path):
            records = []
            if path.suffix == ".jsonl":
                with path.open(encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            records.append(json.loads(line))
            elif path.suffix == ".json":
                with path.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                    records = data if isinstance(data, list) else data.get("items") or []

            overlapping = 0
            eligible = 0
            for r in records:
                expect = r.get("expect", "answer")
                cat = r.get("category", "")
                if expect == "refuse" or cat in ("adversarial_injection", "zero_shot_unseen_book"):
                    continue
                gold = r.get("gold_chunks") or r.get("gold_chunk") or r.get("pin") or r.get("chunk_id")
                if not gold and "meta" in r:
                    gold = r["meta"].get("chunk_id")
                if not gold and "turns" in r:
                    golds = []
                    for t in r["turns"]:
                        tg = t.get("gold_chunks") or t.get("gold_chunk") or t.get("pin") or t.get("chunk_id")
                        if isinstance(tg, list):
                            golds.extend(tg)
                        elif isinstance(tg, str):
                            golds.append(tg)
                    gold = list(dict.fromkeys(golds))

                gold_list = [gold] if isinstance(gold, str) else list(gold or [])
                if any(g.startswith("net-") for g in gold_list) or not gold_list:
                    continue

                eligible += 1
                if any(g in source_chunks for g in gold_list):
                    overlapping += 1
            return overlapping, eligible

        for fname, max_allowed in MAX_SOURCE_PASSAGE_OVERLAPS.items():
            path = DATASETS / fname
            if not path.is_file():
                continue
            measured, eligible = count_overlaps(path)
            self.assertLessEqual(
                measured,
                max_allowed,
                f"Passage overlap ratchet exceeded for {fname}: measured {measured}/{eligible} > limit {max_allowed}",
            )

    def test_refusal_distractor_exclusion_verified(self):
        """Verifies that refusal rows do not count their distractor passages as training source passages."""
        if not TRAIN.is_file():
            self.skipTest("train-x3 not on disk")

        with TRAIN.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                asst = next((m.get("content") or "" for m in row.get("messages", []) if m.get("role") == "assistant"), "")
                if asst.strip() == "Not in this book.":
                    user = next((m.get("content") or "" for m in row.get("messages", []) if m.get("role") == "user"), "")
                    distractors = re.findall(r"chunk_id=(\S+)", user)
                    if distractors:
                        strict_chunks = get_source_chunks_strict(row)
                        self.assertEqual(
                            strict_chunks,
                            set(),
                            "get_source_chunks_strict must return empty set for refusal rows to avoid distractor leakage",
                        )
                        return
        self.fail("Could not find a refusal row with passages to verify distractor exclusion")

    def test_training_derived_files_are_not_eval_surfaces(self):
        for name in TRAINING_DERIVED:
            self.assertNotIn(name, (DATASETS / "sealed-2026-10-24.jsonl").name)
            text = (ROOT / "artifacts" / "harnesses" / "sealed-eval.py").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(name, text, f"{name} is training-derived and cannot score the model")


if __name__ == "__main__":
    unittest.main()
