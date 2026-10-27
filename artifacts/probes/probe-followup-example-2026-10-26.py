"""Repro: "what is an api" -> pill "What example do the authors give?" -> outage quote.

Both quoted sentences live in DDIA chunk text00006-016 ("Human Errors"). This
probe runs the two pure stages with no model and no server:

1. follow-up generation (`intent.compute_dynamic_followups`), and
2. cited-quote advancing (`answer._advance_followup_quote`).

Run from the repo root: python artifacts/probes/probe-followup-example-2026-10-26.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from answer import _advance_followup_quote  # noqa: E402
from intent import compute_dynamic_followups  # noqa: E402

INDEX = ROOT / "data" / "index.ddia.json"
CHUNK_ID = "text00006-016"
QUESTION = "what is an api"
API_QUOTE = (
    "For example, well-designed abstractions, APIs, and admin interfaces make it "
    "easy to do \u201cthe right thing\u201d and discourage \u201cthe wrong thing.\u201d"
)
OUTAGE_QUOTE = (
    "For example, one study of large internet services found that configuration "
    "errors by operators were the leading cause of outages"
)
PILL = "What example do the authors give?"


def main():
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    chunk = next(c for c in index["chunks"] if c["chunk_id"] == CHUNK_ID)
    text = chunk["text"]
    print(f"chunk: {chunk['chunk_id']}  chapter={chunk['chapter']}  heading={chunk.get('heading')!r}")
    print(f"chunk contains the API quote:    {API_QUOTE in text}")
    print(f"chunk contains the outage quote: {OUTAGE_QUOTE in text}")
    print()

    answer_text = f'[Ch. {chunk["chapter"]}] "{API_QUOTE}"'
    followups = compute_dynamic_followups(
        chunk, neighbors=[], question=QUESTION, answer_text=answer_text, mode="ask"
    )
    print(f"compute_dynamic_followups(question={QUESTION!r}) ->")
    for i, f in enumerate(followups, 1):
        print(f"  {i}. {f}")
    print()

    print(f"'for example' occurrences in cited sentence: {API_QUOTE.lower().count('for example')}")
    print(f"'for example' occurrences in whole chunk:    {text.lower().count('for example')}")
    print()

    advanced = _advance_followup_quote(
        chunk, neighbors=[], prior_quote=API_QUOTE, followup_question=PILL
    )
    print(f"_advance_followup_quote(prior=API quote, followup={PILL!r}) ->")
    print(f"  {advanced!r}")
    print()
    print(f"returned quote is the outage sentence: {bool(advanced and advanced.startswith(OUTAGE_QUOTE[:60]))}")
    print(f"returned quote is the API sentence:    {advanced == API_QUOTE}")


if __name__ == "__main__":
    main()
