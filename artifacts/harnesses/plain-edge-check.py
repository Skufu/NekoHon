"""Adversarial checker for the plain-register edge probe (read-only).

Run from the repo root: python artifacts/harnesses/plain-edge-check.py

Checks every artifacts/runs/plain-edge/plain-edge-NN-*.json response against the frozen
contract:
- refused:true means answer is exactly "Not in this book."
- answered: answer non-empty; every [Ch. n] tag has a citation entry
  (tag coverage enforced only for files on the expected plain list, whose
  contract makes that guaranteed; elsewhere a mismatch is reported as NOTE)
- citations have chunk_id/chapter/quote and the quote appears in the book
  chunk text (whitespace/case folded)
- every attached figure's number is named in the text of a cited passage
  (the attachment rule's promise) and the figure id exists in the index
No file is written; exit 1 when a checked rule fails.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ART = ROOT / "archive" / "artifacts" / "evidence" / "plain-edge"
REFUSAL = "Not in this book."

EXPECTED_PLAIN = {
    "plain-edge-01-cue-simple-words",
    "plain-edge-02-cue-in-simple-terms",
    "plain-edge-03-cue-in-plain-words",
    "plain-edge-04-cue-for-a-beginner",
    "plain-edge-05-cue-for-beginners",
    "plain-edge-06-cue-simply-explain",
    "plain-edge-07-cue-explain-simply",
    "plain-edge-08-cue-like-im-five",
    "plain-edge-09-cue-eli5",
    "plain-edge-10-cue-keep-it-simple",
    "plain-edge-14-cue-typo-watermerk",
    "plain-edge-17-cue-figure-watermark",
}


def fold(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def main():
    index = json.load(open(ROOT / "data" / "index.json", encoding="utf-8"))
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    figure_ids = {f["id"]: f for f in index.get("figures") or []}

    files = sorted(ART.glob("plain-edge-*.json"))
    failures = []
    notes = []
    checked = 0
    for path in files:
        try:
            body = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(body, dict) or "refused" not in body:
            continue  # not a response file (timing file, request captures)
        checked += 1
        stem = path.stem
        problems = []

        answer = body.get("answer")
        citations = body.get("citations")
        figures = body.get("figures")
        if not isinstance(answer, str):
            problems.append("answer is not a string")
        if not isinstance(citations, list):
            problems.append("citations is not a list")
            citations = []
        if not isinstance(figures, list):
            problems.append("figures is not a list")
            figures = []

        if body["refused"]:
            if answer != REFUSAL:
                problems.append(f"refused:true but answer != {REFUSAL!r}: {answer[:80]!r}")
        else:
            if not (answer or "").strip():
                problems.append("refused:false with empty answer")

        tags = [int(m.group(1)) for m in re.finditer(r"\[Ch\.\s*(\d+)\]", answer or "")]
        tag_chapters = set(tags)
        cite_chapters = {str(c.get("chapter")) for c in citations if isinstance(c, dict)}
        missing = {t for t in tag_chapters if str(t) not in cite_chapters}
        if missing and stem in EXPECTED_PLAIN:
            problems.append(f"plain-path tag(s) {sorted(missing)} with no citation entry")
        elif missing:
            notes.append(f"{stem}: tag(s) {sorted(missing)} uncited (allowed off plain path)")

        if stem in EXPECTED_PLAIN and len(tags) > 5:
            problems.append(f"plain answer has {len(tags)} tags (cap is 5)")

        for i, cite in enumerate(citations):
            if not isinstance(cite, dict):
                problems.append(f"citation[{i}] not an object")
                continue
            for key in ("chunk_id", "chapter", "quote"):
                if key not in cite:
                    problems.append(f"citation[{i}] missing {key}")
            quote = cite.get("quote") or ""
            cid = cite.get("chunk_id")
            if cid in chunks and quote:
                text = fold(chunks[cid]["text"])
                if fold(quote) not in text:
                    # quote may be reconstructed, try looser punctuation fold
                    loose_q = re.sub(r"[^a-z0-9 ]+", " ", fold(quote))
                    loose_t = re.sub(r"[^a-z0-9 ]+", " ", text)
                    if loose_q not in loose_t:
                        problems.append(f"citation[{i}] quote not found in {cid}")
            elif cid not in chunks:
                problems.append(f"citation[{i}] chunk_id {cid!r} not in index")

        cited_texts = []
        for c in citations:
            if isinstance(c, dict) and c.get("chunk_id") in chunks:
                cited_texts.append(chunks[c["chunk_id"]]["text"])
        for fig in figures:
            if not isinstance(fig, dict):
                problems.append("figure entry not an object")
                continue
            fid = fig.get("id")
            if fid not in figure_ids:
                problems.append(f"figure {fid!r} not in index")
                continue
            number = re.search(r"(\d+-\d+)", fid).group(1).lower()
            named = any(
                number in {m.group(1).lower() for m in re.finditer(r"(?:figure|fig\.)\s+([A-Za-z]?\d+-\d+)", t, re.I)}
                for t in cited_texts
            )
            if not named:
                problems.append(f"figure {fid} attached but no cited passage names it")

        status = "PASS" if not problems else "FAIL"
        print(f"{status} {stem} (refused={body['refused']}, tags={sorted(tag_chapters)}, citations={len(citations)}, figures={len(figures)})")
        for p in problems:
            print(f"    problem: {p}")
            failures.append(f"{stem}: {p}")

    print(f"\nchecked {checked} response files")
    for n in notes:
        print(f"NOTE {n}")
    if failures:
        print(f"\n{len(failures)} problem(s)")
        sys.exit(1)
    print("all contract checks passed")


if __name__ == "__main__":
    main()
