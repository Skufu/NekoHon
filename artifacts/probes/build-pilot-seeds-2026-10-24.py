"""Build the 40-row history pilot: prompts only, no teacher call.

Why this file exists: rounds 3 and 4 both lost on multi-turn. Round 4 assembled
history prefixes around answers the teacher wrote for *standalone* questions, so
the targets taught "ignore the history". This builder asks the teacher a new
question in the second turn so the target is written while the history is in
view.

Three fixes, each tied to a measured failure in
`artifacts/reports/seed-audit-*-deepseek.md`:

a) history turn comes from the same section, and the final question shares two
   content words with it, not one (10/13 coreference rows resolved to the wrong
   subject with a single shared word);
b) the final question is new, so the teacher writes a fresh target instead of
   copying a standalone answer (220/400 rows were duplicates once history was
   stripped);
c) class mix is 18 entity-relation / 10 premise-trap / 6 simplify / 6 highlight.

Reads the 844-row x3 corpus for turn-1 anchors. Writes
`data/finetune/pilot-seeds-2026-10-24.jsonl` with the exact serving bytes from
`answer.user_message`, plus `artifacts/evidence/pilot/seeds-summary.json`.

Read-only on every existing file. Nothing is trained from this output until the
teacher answers and the assembler validates it.
"""

import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}
CORPUS = FIN / "quote-refuse-2026-10-17.train-x3.jsonl"
VAL = FIN / "val-questions-2026-10-24.txt"
DATASETS = ROOT / "artifacts" / "datasets"
OUT = Path(os.environ.get("PILOT_OUT", FIN / "pilot-seeds-2026-10-24.jsonl"))
if not OUT.is_absolute():
    OUT = ROOT / OUT
EVIDENCE = Path(os.environ.get(
    "PILOT_EVIDENCE",
    ROOT / "artifacts" / "evidence" / "pilot" / "seeds-summary.json"))
if not EVIDENCE.is_absolute():
    EVIDENCE = ROOT / EVIDENCE

MIX = {"entity_relation": 18, "premise_trap": 10, "simplify": 6, "highlight": 6}
ONLY = [name for name in os.environ.get("PILOT_CLASSES", "").split(",") if name]
if ONLY:
    MIX = {name: (count if name in ONLY else 0) for name, count in MIX.items()}
ER_TEMPLATE = os.environ.get("PILOT_ER_TEMPLATE", "name_both")
SEED = 3407
REFUSAL = "Not in this book."
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
CHUNK_RE = re.compile(
    r"\[Ch\. ([^\]]+)\] chunk_id=([a-z0-9-]+)\n(.*?)(?=\n\n\[Ch\. |\n\nCopy one sentence)", re.S)
PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
CAPS_RE = re.compile(r"\b([A-Z][A-Za-z0-9-]+(?:[ \t]+[A-Z][A-Za-z0-9-]+){0,2})\b")
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can", "i",
    "you", "we", "they", "from", "at", "as", "or", "if", "not", "but", "so",
    "use", "used", "using", "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "many", "most", "some", "any", "all",
    "into", "over", "than", "then", "there", "their", "when", "where", "who",
}
FURNITURE = {"figure", "fig", "table", "chapter", "section", "note", "example",
             "box", "source"}
GENERIC = {"data", "system", "systems", "storage", "user", "users", "value", "time"}
NAMES = ["Dr. Helena Voss", "Marcus Feld", "Priya Raman", "Tomas Lindgren"]
YEARS = ["1998", "2001", "2007", "2012"]


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(text):
    return {w for w in fold(text).split() if w not in STOPWORDS and len(w) > 2}


def jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def key(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def book_of(chunk_id):
    if chunk_id.startswith("text"):
        return "ddia"
    if chunk_id.startswith("chapter-"):
        return "quantization"
    return "fde"


def load_indexes():
    chunks, by_id, sections = [], {}, {}
    for book, path in INDEXES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        for chunk in data["chunks"]:
            record = {
                "book": book,
                "chunk_id": chunk["chunk_id"],
                "chapter": chunk.get("chapter", ""),
                "heading": (chunk.get("heading") or "").strip(),
                "text": chunk.get("text", ""),
            }
            chunks.append(record)
            by_id[record["chunk_id"]] = record
            if record["heading"]:
                sections.setdefault((book, record["heading"]), []).append(record["chunk_id"])
    return chunks, by_id, sections


def parse_row(record):
    messages = record["messages"]
    system = next(m["content"] for m in messages if m["role"] == "system")
    user = next(m["content"] for m in messages if m["role"] == "user")
    answer = next(m["content"] for m in messages if m["role"] == "assistant")
    match = QUESTION_RE.search(user)
    question = match.group(1).strip() if match else ""
    passages = [
        {"chapter": chapter, "chunk_id": chunk_id, "text": text.strip()}
        for chapter, chunk_id, text in CHUNK_RE.findall(user)
    ]
    return system, user, answer, question, passages


def eval_questions():
    out = []
    for name in ("hard-bench-2026-10-17.jsonl", "wide-net-2026-10-23.jsonl",
                 "sealed-2026-10-24.jsonl"):
        for record in jsonl(DATASETS / name):
            q = record.get("question") or ("[selection] " + (record.get("selection") or ""))
            if q:
                out.append((name, q))
    for scenario in json.loads(
            (DATASETS / "adrian-realworld-eval-2026-10-17.json").read_text(encoding="utf-8")):
        for turn in scenario.get("turns") or []:
            if turn.get("question"):
                out.append(("adrian", turn["question"]))
    return out


def leaks(question, corpus):
    folded = fold(question)
    words = content(question)
    if not words:
        return None
    for name, other in corpus:
        other_folded = fold(other)
        if folded == other_folded:
            return name, other, "exact"
        other_words = content(other)
        if not other_words:
            continue
        if len(words & other_words) / len(words | other_words) < 0.7:
            continue
        import difflib
        if difflib.SequenceMatcher(None, folded, other_folded).ratio() >= 0.85:
            return name, other, "near"
    return None


def entity_in(text, exclude):
    """A named thing the follow-up can ask about. Prefer multiword capitals.

    Mid-sentence only: a capital at the start of a sentence is grammar, not a
    name. Without this, "Figure", "Note" and "While" become entities, and a
    question like "How does Figure relate to X?" teaches nothing.
    """
    best = ""
    for match in CAPS_RE.finditer(text):
        before = text[:match.start()].rstrip()
        if not before or before[-1] in ".!?:\n":
            continue
        candidate = SPACE_RE.sub(" ", match.group(1)).strip()
        if len(candidate) < 3 or len(candidate) > 40 or candidate.lower() in STOPWORDS:
            continue
        if candidate.split()[0].lower() in FURNITURE | {"what", "how", "why", "when", "where", "who"}:
            continue
        if candidate.lower() in exclude:
            continue
        if len(candidate.split()) == 1 and candidate.lower() in GENERIC:
            continue
        if len(candidate.split()) > len(best.split()):
            best = candidate
    return best


def topic_of(heading):
    """The thing a trap question names: the section's subject, not its title."""
    text = SPACE_RE.sub(" ", heading).strip(" “”\"'.:;,?")
    text = re.sub(r"^(what (is|are)|chapter\s+\d+\.?)\s*", "", text, flags=re.I)
    text = re.split(r"\s+(?:versus|vs\.?|and)\s+|:", text, maxsplit=1, flags=re.I)[0].strip()
    words = [w for w in text.split() if w.lower() not in {"defined", "introduction", "overview"}]
    while words and (words[0].lower() in {"the", "a", "an"} or words[-1].lower() in STOPWORDS):
        words = words[1:] if words[0].lower() in {"the", "a", "an"} else words[:-1]
    return " ".join(words[:5])


def interleave(groups):
    """Round-robin so 18 rows do not all come from chapter 1 of one book."""
    out, index = [], 0
    while any(index < len(group) for group in groups):
        for group in groups:
            if index < len(group):
                out.append(group[index])
        index += 1
    return out



def main():
    sys.path.insert(0, str(ROOT))
    import answer  # noqa: E402  (needs ROOT on the path)
    import prompt  # noqa: E402
    from retrieve import search  # noqa: E402

    chunks, by_id, sections = load_indexes()
    corpus_eval = eval_questions()
    with VAL.open(encoding="utf-8") as fh:
        val_keys = {" ".join(line.lower().split()) for line in fh if line.strip()}

    rows, seen_questions = [], set()
    stats = Counter()

    def add(row_class, question, passages, history, meta):
        digest = key([{"role": "system", "content": prompt.SYSTEM},
                      {"role": "user", "content": answer.user_message(question, passages, history)},
                      {"role": "assistant", "content": REFUSAL}])
        if digest in seen_questions:
            stats["dup"] += 1
            return False
        hit = leaks(question, corpus_eval)
        if hit:
            stats["leak"] += 1
            return False
        user = answer.user_message(question, passages, history)
        seen_questions.add(digest)
        rows.append({
            "id": f"{row_class}-{len(rows) + 1:02d}",
            "class": row_class,
            "system": prompt.SYSTEM,
            "user": user,
            "messages": [{"role": "system", "content": prompt.SYSTEM},
                         {"role": "user", "content": user}],
            "meta": meta,
        })
        stats[row_class] += 1
        return True

    # ---------- anchors from the 844-row corpus ----------
    anchors = []
    for record in jsonl(CORPUS):
        system, user, answer_text, question, passages = parse_row(record)
        if not question or not passages:
            continue
        if " ".join(question.lower().split()) in val_keys:
            continue
        if not answer_text.startswith("[Ch. "):
            continue
        chunk_id = passages[0]["chunk_id"]
        chunk = by_id.get(chunk_id)
        if not chunk:
            continue
        anchors.append({"question": question, "answer": answer_text, "passages": passages,
                        "chunk": chunk, "book": chunk["book"]})

    by_book = {book: [a for a in anchors if a["book"] == book]
               for book in ("fde", "quantization", "ddia")}
    anchors = interleave(list(by_book.values()))
    print("anchors by book:", {book: len(group) for book, group in by_book.items()})

    # ---------- entity relation ----------
    for anchor in anchors:
        if stats["entity_relation"] >= MIX["entity_relation"]:
            break
        chunk = anchor["chunk"]
        siblings = [by_id[cid] for cid in sections.get((chunk["book"], chunk["heading"]), [])
                    if cid != chunk["chunk_id"]]
        if not siblings:
            stats["er_no_sibling"] += 1
            continue
        q1_words = content(anchor["question"])
        heading = SPACE_RE.sub(" ", chunk["heading"]).strip(" “”\"'.:;,?")
        anchor_term = re.sub(r"^(chapter\s+\d+\.?\s*)", "", heading, flags=re.I)
        anchor_term = " ".join(anchor_term.split()[:8])
        if not anchor_term:
            stats["er_no_heading"] += 1
            continue
        sibling = max(siblings, key=lambda s: len(q1_words & content(s["text"])))
        if fold(anchor_term) not in fold(sibling["text"]):
            stats["er_term_absent"] += 1
            continue
        bridges = sorted((q1_words & content(sibling["text"])) - content(anchor_term),
                         key=len, reverse=True)
        # Search the body, not the heading line: an entity that only appears in
        # the heading is the section itself, and "A relate to A" teaches nothing.
        body = sibling["text"].split("\n", 1)[1] if "\n" in sibling["text"] else sibling["text"]
        entity = entity_in(body, exclude=content(anchor_term))
        if not entity or set(content(entity)) <= content(anchor_term):
            stats["er_no_entity"] += 1
            continue
        if ER_TEMPLATE == "answer_ref":
            # The follow-up must reach back to the prior answer, not restate the
            # section. The audit rejected the name-both shape 5 times for being
            # answerable without the history.
            question = f"How does {entity} connect to the sentence you quoted?"
        else:
            question = f"How does {entity} relate to {anchor_term}?"
            if len(content(question) & q1_words) < 2 and bridges:
                question = f"How does {entity} relate to {anchor_term} in {bridges[0]}?"
            if len(content(question) & q1_words) < 2:
                stats["er_thin_overlap"] += 1
                continue
        history = [{"question": anchor["question"], "answer": anchor["answer"]}]
        passages = [{"chapter": sibling["chapter"], "chunk_id": sibling["chunk_id"],
                      "text": sibling["text"]}]
        if add("entity_relation", question, passages, history, {
                "book": chunk["book"], "heading": chunk["heading"],
                "anchor_chunk": chunk["chunk_id"], "target_chunk": sibling["chunk_id"],
                "anchor_question": anchor["question"], "entity": entity,
                "bridge": bridges[0] if bridges else ""}):
            continue

    # ---------- premise trap ----------
    # One shape: a person who is not in the passages, saying a thing in a year
    # that is not in them. The 2026-10-24 audit found "four stages" rows that
    # were answerable, and a count cannot be verified absent from prose. A name
    # and a year can.
    for index, anchor in enumerate(anchors):
        if stats["premise_trap"] >= MIX["premise_trap"]:
            break
        chunk = anchor["chunk"]
        folded_passages = fold(" ".join(p["text"] for p in anchor["passages"]))
        passage_words = set(folded_passages.split())
        term = topic_of(chunk["heading"])
        if len(term) < 4:
            stats["pt_no_term"] += 1
            continue
        name = NAMES[index % len(NAMES)]
        if any(word in passage_words for word in fold(name).split()):
            stats["pt_name_present"] += 1
            continue
        year = YEARS[index % len(YEARS)]
        if year in folded_passages:
            stats["pt_year_present"] += 1
            continue
        question = f"What did {name} say about {term} in {year}?"
        history = [{"question": anchor["question"], "answer": anchor["answer"]}]
        add("premise_trap", question, anchor["passages"], history, {
            "book": chunk["book"], "heading": chunk["heading"],
            "target_chunk": chunk["chunk_id"], "anchor_question": anchor["question"],
            "trap": "absent_attribution", "expect": REFUSAL})

    # ---------- simplify ----------
    for anchor in anchors:
        if stats["simplify"] >= MIX["simplify"]:
            break
        question = "Explain that in simple words."
        history = [{"question": anchor["question"], "answer": anchor["answer"]}]
        add("simplify", question, anchor["passages"], history, {
            "book": anchor["book"], "heading": anchor["chunk"]["heading"],
            "target_chunk": anchor["chunk"]["chunk_id"],
            "anchor_question": anchor["question"]})

    # ---------- highlight ----------
    word_counts = Counter()
    for chunk in chunks:
        word_counts.update(content(chunk["text"]))
    for chunk in chunks:
        if stats["highlight"] >= MIX["highlight"]:
            break
        if not chunk["heading"] or len(chunk["text"]) < 200:
            continue
        heading_words = [w for w in fold(chunk["heading"]).split()
                         if 5 <= len(w) <= 14 and w not in STOPWORDS
                         and w.isalpha() and not w.endswith(("ed", "ing"))
                         and 3 <= word_counts[w] <= 40]
        if not heading_words:
            stats["hl_no_term"] += 1
            continue
        term = sorted(set(heading_words), key=lambda w: (word_counts[w], -len(w)))[0]
        question = f"What is {term} in {chunk['heading']}?"
        try:
            hits = search(_load_index(chunk["book"]), question, k=5)
        except Exception as exc:  # embedder down -> no highlight rows, say why
            print("search failed:", type(exc).__name__, exc)
            stats["hl_search_failed"] += 1
            break
        if chunk["chunk_id"] not in {h["chunk_id"] for h in hits}:
            stats["hl_miss"] += 1
            continue
        passages = [{"chapter": h["chapter"], "chunk_id": h["chunk_id"], "text": h["text"]}
                    for h in hits]
        add("highlight", question, passages, [], {
            "book": chunk["book"], "heading": chunk["heading"],
            "target_chunk": chunk["chunk_id"], "selection": term})

    missing = {cls: MIX[cls] - stats[cls] for cls in MIX if stats[cls] < MIX[cls]}
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "rows": len(rows), "mix": MIX, "built": dict(stats),
        "missing": missing, "out": str(OUT.relative_to(ROOT)),
    }, indent=1) + "\n", encoding="utf-8")

    print(f"seeds: {len(rows)} -> {OUT.relative_to(ROOT)}")
    print("classes:", {cls: stats[cls] for cls in MIX})
    print("drops:", {k: v for k, v in stats.items() if k not in MIX})
    if missing:
        print("INCOMPLETE:", missing)
        sys.exit(1)


_INDEX_CACHE = {}


def _load_index(book):
    if book not in _INDEX_CACHE:
        _INDEX_CACHE[book] = json.loads(INDEXES[book].read_text(encoding="utf-8"))
    return _INDEX_CACHE[book]


if __name__ == "__main__":
    main()
