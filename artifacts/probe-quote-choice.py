"""Replay the citation-quote selection for one captured draft, offline.

Reads the draft from probe-plain-diagnose.json (the cue record, first
generation call), rebuilds the same shown passages, and prints per claim:
the passage `_best_passage` picks, its overlap rationale, and the quote
`_evidence_quote` returns (with the copied span, when one exists). Also
prints the full text of every shown passage, so a misselection is visible.

Run: python artifacts/probe-quote-choice.py
Writes artifacts/probe-quote-choice.log
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from retrieve import INDEX, load_index

QUESTION = "explain data engineering in simple words"


def main():
    index = load_index(INDEX)
    records = json.loads((HERE / "probe-plain-diagnose.json").read_text(encoding="utf-8"))
    cue = next(r for r in records if r["label"] == "cue")
    draft = next(c["out"] for c in cue["calls"] if c["tag"] == "draft")

    passages = A.retrieval_context(index, QUESTION)["passages"]
    lines = []
    lines.append("== full shown passages")
    for hit in passages:
        lines.append(f"--- {hit['chunk_id']} ch{hit['chapter']} score={hit.get('score')}")
        lines.append(" ".join((hit["text"] or "").split()))
        lines.append("")

    lines.append("== per-claim citation replay")
    for claim, chapters in A._sentence_claims(draft):
        lines.append(f"CLAIM {chapters}: {claim}")
        tokens = A._tokens(claim)
        scored = []
        for hit in passages:
            overlap = len(tokens & A._tokens(hit.get("text") or "")) / len(tokens)
            scored.append((overlap, hit["chunk_id"], str(hit["chapter"])))
        scored.sort(reverse=True)
        for overlap, chunk_id, chapter in scored[:3]:
            lines.append(f"   overlap {overlap:.3f}  {chunk_id} ch{chapter}")
        hit = A._best_passage(claim, chapters, passages)
        if hit is None:
            lines.append("   -> NO CITATION (zero overlap)")
            lines.append("")
            continue
        span = A.longest_copied_span(claim, hit.get("text") or "")
        quote = A._evidence_quote(claim, hit)
        lines.append(f"   -> picked {hit['chunk_id']} ch{hit['chapter']}")
        lines.append(f"   -> copied span: {span!r}")
        lines.append(f"   -> quote: {quote}")
        lines.append("")

    log = "\n".join(lines)
    (HERE / "probe-quote-choice.log").write_text(log, encoding="utf-8")
    print(log)


if __name__ == "__main__":
    main()
