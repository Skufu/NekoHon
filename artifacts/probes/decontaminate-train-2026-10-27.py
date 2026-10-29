"""Corpus decontamination probe: filter eval leakage and ungrounded rows.

Date: 2026-10-27
Purpose: Produce a clean, decontaminated training corpus from train-x3 by stripping:
1. Exact-match or near-duplicate questions (difflib >= 0.85 or 5-gram Jaccard >= 0.60)
   across all eval sets (sealed, hard-bench, hard-mt, adrian, crossbook, highlight-golden,
   battery-pins, eval-set, eval-set-plain, fair-2026-10-27).
2. Assistant text sharing >= 15-word verbatim runs with eval prompts (e.g. explain_* highlights).
3. Any in-book passage quote that fails verbatim grounding against the indexed books.

Input:  data/finetune/quote-refuse-2026-10-17.train-x3.jsonl (unmodified)
Output: data/finetune/quote-refuse-2026-10-27.train-x3-clean.jsonl
"""

import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import load_index

TRAIN_PATH = ROOT / "data" / "finetune" / "quote-refuse-2026-10-17.train-x3.jsonl"
OUT_PATH = ROOT / "data" / "finetune" / "quote-refuse-2026-10-27.train-x3-clean.jsonl"
DATASETS_DIR = ROOT / "artifacts" / "datasets"

INDEXES = [
    ROOT / "data" / "index.json",
    ROOT / "data" / "index.quantization.json",
    ROOT / "data" / "index.ddia.json",
]
IN_BOOK = re.compile(r"^(ch\d|app\d|text\d|chapter-)")
QUOTE = re.compile(r'\[Ch\.\s*[^\]]+\]\s*["“](.+?)["”]', re.S)
REFUSAL = "Not in this book."

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
HIGHLIGHT_RE = re.compile(r"^Highlighted text:\s*(.+?)(?:\n|$)", re.M)

EVAL_SETS = [
    "sealed-2026-10-24.jsonl",
    "hard-bench-2026-10-17.jsonl",
    "hard-mt-2026-10-24.jsonl",
    "adrian-realworld-eval-2026-10-17.json",
    "crossbook-evil-eval-2026-10-18.json",
    "highlight-golden-2026-10-16.jsonl",
    "battery-pins.json",
    "eval-set.json",
    "eval-set-plain.json",
    "fair-2026-10-27.jsonl",
]


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def word_5grams(folded_text):
    words = folded_text.split()
    if len(words) < 5:
        return set()
    return {" ".join(words[i : i + 5]) for i in range(len(words) - 4)}


def word_15grams(folded_text):
    words = folded_text.split()
    if len(words) < 15:
        return set()
    return {" ".join(words[i : i + 15]) for i in range(len(words) - 14)}


def jaccard_5g(s1, s2):
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def load_book_grounding():
    texts = []
    for p in INDEXES:
        if p.is_file():
            idx = load_index(p)
            for chunk in idx.get("chunks", []):
                texts.append(chunk.get("text") or "")
            for figure in idx.get("figures", []):
                texts.append(
                    (figure.get("caption") or "")
                    + " "
                    + (figure.get("referencing_paragraph") or "")
                )

    folded_b, punct_b = [], []
    for text in texts:
        stripped = A._strip_figure_refs(text)
        folded_b.append(re.sub(r"\s+", " ", stripped).lower())
        punct_b.append(A._punctuation_plain(stripped))

    def is_quote_in_book(quote):
        stripped = A._strip_figure_refs(quote)
        if any(re.sub(r"\s+", " ", stripped).lower() in t for t in folded_b):
            return True
        pp = A._punctuation_plain(stripped)
        return any(pp in t for t in punct_b)

    return is_quote_in_book


def load_eval_references():
    eval_questions = []
    eval_prompts_15g = []

    for es_name in EVAL_SETS:
        p = DATASETS_DIR / es_name
        if not p.is_file():
            print(f"Warning: {p} not found!", file=sys.stderr)
            continue
        if p.name.endswith(".jsonl"):
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    for k in ["question", "prompt", "selection"]:
                        v = r.get(k)
                        if v and v != "None":
                            fq = fold(v)
                            if fq:
                                eval_questions.append((fq, word_5grams(fq), es_name, r.get("id", "")))
                                fg15 = word_15grams(fq)
                                if fg15:
                                    eval_prompts_15g.append((fg15, es_name, r.get("id", "")))
        else:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            items_to_check = []
            if isinstance(data, list):
                items_to_check = data
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        items_to_check.extend(v)
            for it in items_to_check:
                if isinstance(it, dict):
                    if "turns" in it:
                        for t in it["turns"]:
                            for k in ["question", "selection"]:
                                v = t.get(k)
                                if v and v != "None":
                                    fq = fold(v)
                                    if fq:
                                        eval_questions.append((fq, word_5grams(fq), es_name, it.get("id", "")))
                                        fg15 = word_15grams(fq)
                                        if fg15:
                                            eval_prompts_15g.append((fg15, es_name, it.get("id", "")))
                    for k in ["question", "selection"]:
                        v = it.get(k)
                        if v and v != "None":
                            fq = fold(v)
                            if fq:
                                eval_questions.append((fq, word_5grams(fq), es_name, it.get("id", "")))
                                fg15 = word_15grams(fq)
                                if fg15:
                                    eval_prompts_15g.append((fg15, es_name, it.get("id", "")))

    return eval_questions, eval_prompts_15g


def decontaminate():
    print(f"Loading book text indexes for quote verification...")
    is_quote_in_book = load_book_grounding()

    print(f"Loading reference eval sets...")
    eval_questions, eval_prompts_15g = load_eval_references()
    print(f"Collected {len(eval_questions)} eval questions and {len(eval_prompts_15g)} 15-gram eval prompts.")

    if not TRAIN_PATH.is_file():
        print(f"Error: Training file not found: {TRAIN_PATH}", file=sys.stderr)
        sys.exit(1)

    train_rows = []
    with open(TRAIN_PATH, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                train_rows.append(json.loads(line))
    print(f"Loaded {len(train_rows)} rows from {TRAIN_PATH.name}")

    stripped_reasons = []
    kept_rows = []

    for idx, row in enumerate(train_rows):
        msgs = row.get("messages") or []
        user = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
        asst = next((m.get("content") or "" for m in msgs if m.get("role") == "assistant"), "").strip()
        meta = row.get("meta") or {}

        # Extract question
        q = None
        m = QUESTION_RE.search(user)
        if m:
            q = m.group(1).strip()
        elif "question" in meta:
            q = meta["question"]
        elif "asked" in meta:
            q = meta["asked"]
        elif "question" in row:
            q = row["question"]
        else:
            hm = HIGHLIGHT_RE.search(user)
            if hm:
                q = hm.group(1).strip()
            elif user:
                q = user.split("\n")[0].strip()

        fq = fold(q)
        fg5 = word_5grams(fq)
        l1 = len(fq)

        # Check 1: Eval question exact match or near duplicate (difflib >= 0.85 or 5-gram Jaccard >= 0.60)
        leak = None
        for eq, efg5, esrc, eid in eval_questions:
            if fq == eq:
                leak = f"exact question match with {esrc}:{eid} ({q!r})"
                break
            if fg5 and efg5:
                j = jaccard_5g(fg5, efg5)
                if j >= 0.60:
                    leak = f"5-gram Jaccard {j:.3f} >= 0.60 with {esrc}:{eid} ({q!r} vs {eq[:50]!r})"
                    break
            l2 = len(eq)
            up = 2.0 * min(l1, l2) / (l1 + l2) if (l1 + l2) > 0 else 0
            if up >= 0.85:
                r = difflib.SequenceMatcher(None, fq, eq).ratio()
                if r >= 0.85:
                    leak = f"difflib {r:.3f} >= 0.85 with {esrc}:{eid} ({q!r} vs {eq[:50]!r})"
                    break

        if leak:
            stripped_reasons.append((idx, "eval_leak", leak))
            continue

        # Check 2: Assistant text shares >=15-word verbatim run with eval prompt
        asst_fold = fold(asst)
        asst_15g = word_15grams(asst_fold)
        run_leak = None
        if asst_15g:
            for p15g, esrc, eid in eval_prompts_15g:
                overlap = asst_15g & p15g
                if overlap:
                    run_leak = f">=15-word run overlap with {esrc}:{eid}: {next(iter(overlap))!r}"
                    break
        if run_leak:
            stripped_reasons.append((idx, "verbatim_15word_eval_prompt_overlap", run_leak))
            continue

        # Check 3: In-book quote verbatim grounding
        if asst != REFUSAL:
            chunk_m = re.search(r"chunk_id=([a-z0-9-]+)", user)
            if chunk_m and IN_BOOK.match(chunk_m.group(1)):
                qm = QUOTE.match(asst)
                if not qm:
                    stripped_reasons.append((idx, "no_quote_in_target", f"chunk={chunk_m.group(1)}"))
                    continue
                quote_str = qm.group(1)
                if not is_quote_in_book(quote_str):
                    stripped_reasons.append((idx, "ungrounded_quote", f"{quote_str[:60]!r}"))
                    continue

        kept_rows.append(row)

    # Write output
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for r in kept_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("\n" + "=" * 80)
    print("CORPUS DECONTAMINATION REPORT")
    print("=" * 80)
    print(f"Source file:   {TRAIN_PATH}")
    print(f"Target file:   {OUT_PATH}")
    print(f"Initial rows:  {len(train_rows)}")
    print(f"Kept rows:     {len(kept_rows)} ({len(kept_rows)/len(train_rows)*100:.1f}%)")
    print(f"Stripped rows: {len(stripped_reasons)} ({len(stripped_reasons)/len(train_rows)*100:.1f}%)")

    reasons_count = {}
    for _, cat, _ in stripped_reasons:
        reasons_count[cat] = reasons_count.get(cat, 0) + 1

    print("\nStripped rows breakdown by category:")
    for cat, cnt in sorted(reasons_count.items()):
        print(f"  - {cat:35} : {cnt:3d} rows")
    print("=" * 80)


if __name__ == "__main__":
    decontaminate()
