"""Golden held-out highlight eval: smallbook_x2f vs smallbook_x2d.

Runs the 24 held-out highlight rows through `answer.explain` with the real
index and the production generate path (in-process, no server). Scores:
not refused, the pinned chunk cited, a quote verbatim from the pinned chunk,
and that quote contains the marked word.

Usage:
  python artifacts/probes/probe-highlight-2026-10-16.py smallbook_x2d smallbook_x2f
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402

GOLDEN = ROOT / "artifacts" / "datasets" / "highlight-golden-2026-10-16.jsonl"
INDEX = ROOT / "data" / "index.json"
OUT = ROOT / "artifacts" / "evidence" / "highlight-golden"


def fold(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def load_rows():
    rows = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can't",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from",
    "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having",
    "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've",
    "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's",
    "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of",
    "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd",
    "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than",
    "that", "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
}


def extract_gloss(answer_text):
    """Extract the explanatory gloss lines from an answer, stripping [Ch. N] quotes."""
    lines = [line.strip() for line in (answer_text or "").splitlines() if line.strip()]
    gloss_lines = [l for l in lines if not re.match(r"^\[Ch\.\s*[^\]]+\]", l, re.I)]
    return " ".join(gloss_lines).strip()


def check_gloss(gloss, selection, pin_text, min_grounded_ratio=0.5):
    """Opt-in strict check on the generated gloss for highlight explanations.

    Rules:
    1. The generated gloss must be non-empty and non-trivial (not 'x', not empty).
    2. Must not just repeat the selected text.
    3. Must be grounded: its content words mostly appear in the selected passage/chunk.
    """
    gloss = (gloss or "").strip()
    # 1. Non-empty and not single character / trivial
    if not gloss or len(gloss) < 2 or fold(gloss) in ("x",):
        return False, "gloss is empty or trivial", {"non_empty": False, "not_repeated": False, "grounded": False}

    # 2. Must not just repeat the selected text
    def plain(text):
        return re.sub(r"[^\w\s]+", "", (text or "").lower()).strip()

    if plain(gloss) == plain(selection):
        return False, "gloss repeats selected text", {"non_empty": True, "not_repeated": False, "grounded": False}

    # 3. Grounded in passage / chunk content
    def content_words(text):
        cleaned = re.sub(r"[^\w\s]+", " ", (text or "").lower())
        return [w for w in cleaned.split() if len(w) >= 3 and w not in STOPWORDS]

    g_words = content_words(gloss)
    if not g_words:
        return False, "gloss contains no content words", {"non_empty": True, "not_repeated": True, "grounded": False}

    p_words = set(content_words(pin_text))
    p_folded = fold(pin_text)
    matched = [w for w in g_words if w in p_words or w in p_folded]
    ratio = len(matched) / len(g_words) if g_words else 0.0

    is_grounded = ratio >= min_grounded_ratio
    metrics = {
        "non_empty": True,
        "not_repeated": True,
        "grounded": is_grounded,
        "content_words_count": len(g_words),
        "matched_words_count": len(matched),
        "grounded_ratio": round(ratio, 3),
    }
    if not is_grounded:
        return False, f"gloss not grounded in passage ({len(matched)}/{len(g_words)} content words match, ratio {ratio:.3f} < {min_grounded_ratio})", metrics
    return True, "gloss grounded and valid", metrics


def score(body, pin_text, selection, strict=False):
    answer = body.get("answer") or ""
    citations = body.get("citations") or []
    refused = bool(body.get("refused"))
    pin_cited = any(c.get("chunk_id") == body.get("_pin") for c in citations)
    word = re.compile(rf"\b{re.escape(selection.lower())}\b")
    verbatim = False
    word_in_quote = False
    for cite in citations:
        quote = fold(cite.get("quote"))
        if not quote or quote not in fold(pin_text):
            continue
        verbatim = True
        if word.search(quote):
            word_in_quote = True

    res = {
        "refused": refused,
        "pin_cited": pin_cited,
        "quote_verbatim_in_pin": verbatim,
        "word_in_quoted_span": word_in_quote,
        "answer": answer[:400],
    }

    if strict:
        gloss = extract_gloss(answer)
        valid, detail, metrics = check_gloss(gloss, selection, pin_text)
        res["gloss"] = gloss
        res["gloss_valid"] = valid
        res["gloss_detail"] = detail
        res["gloss_non_empty"] = metrics.get("non_empty", False)
        res["gloss_not_repeated"] = metrics.get("not_repeated", False)
        res["gloss_grounded"] = metrics.get("grounded", False)
        res["gloss_grounded_ratio"] = metrics.get("grounded_ratio", 0.0)
        res["passed"] = bool(
            not refused
            and pin_cited
            and verbatim
            and word_in_quote
            and valid
        )
    return res


def score_strict(body, pin_text, selection, min_grounded_ratio=0.5):
    """Opt-in strict scoring function that validates both citation and generated gloss."""
    return score(body, pin_text, selection, strict=True)


def run_model(index, rows, model):
    results = []
    for row in rows:
        meta = row["meta"]
        selection = meta["selection"]
        chunk_id = meta["chunk_id"]
        heading = meta["heading"]
        pin = next(c for c in index["chunks"] if c["chunk_id"] == chunk_id)
        started = time.monotonic()
        try:
            body = A.explain(
                index, selection, model=model, chunk_id=chunk_id, heading=heading,
            )
            body["_pin"] = chunk_id
            scored = score(body, pin.get("text", ""), selection)
            scored["error"] = None
        except Exception as exc:  # noqa: BLE001 - record and keep going
            scored = {
                "refused": None, "pin_cited": None,
                "quote_verbatim_in_pin": None, "word_in_quoted_span": None,
                "answer": "", "error": repr(exc),
            }
        scored["seconds"] = round(time.monotonic() - started, 1)
        scored["id"] = f"{chunk_id}:{selection}"
        scored["asked"] = meta["asked"]
        results.append(scored)
        flags = "".join(
            "Y" if scored.get(key) else "n" if scored.get(key) is False else "-"
            for key in ("refused", "pin_cited", "quote_verbatim_in_pin",
                        "word_in_quoted_span")
        )
        print(f"{scored['id']:<28} {flags} {scored['seconds']:>6}s", flush=True)
    return results


def main():
    models = sys.argv[1:] or ["smallbook_x2d", "smallbook_x2f"]
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = load_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for model in models:
        print(f"--- {model} ---", flush=True)
        results = run_model(index, rows, model)
        good = sum(
            1 for r in results
            if not r["refused"] and r["pin_cited"]
            and r["quote_verbatim_in_pin"] and r["word_in_quoted_span"]
        )
        cited = sum(1 for r in results if not r["refused"] and r["pin_cited"])
        verbatim = sum(
            1 for r in results if not r["refused"] and r["quote_verbatim_in_pin"]
        )
        refused = sum(1 for r in results if r["refused"])
        errors = sum(1 for r in results if r["error"])
        summary[model] = {
            "rows": len(results),
            "full_pass": good,
            "not_refused_and_pin_cited": cited,
            "quote_verbatim_in_pin": verbatim,
            "refused": refused,
            "errors": errors,
        }
        slug = model.replace(":", "-")
        payload = {"model": model, "summary": summary[model], "rows": results}
        (OUT / f"probe-highlight-2026-10-16.model-{slug}.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        lines = [
            f"# highlight golden eval — {model} — {len(results)} held-out rows",
            "# flags: refused / pin cited / quote verbatim in pin / word in quote",
        ]
        for r in results:
            flags = "".join(
                "Y" if r.get(key) else "n" if r.get(key) is False else "-"
                for key in ("refused", "pin_cited", "quote_verbatim_in_pin",
                            "word_in_quoted_span")
            )
            lines.append(f"{r['id']:<28} {flags} {r['seconds']:>6}s {r['asked']}")
        (OUT / f"probe-highlight-2026-10-16.model-{slug}.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8",
        )
    print("--- summary ---")
    for model, counts in summary.items():
        print(model, counts)
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
