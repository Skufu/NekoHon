"""A/B the evidence-quote rule on the plain register: current vs candidate.

Candidate rule: pick the quote sentence by claim token overlap, the same
rule `_best_passage` already uses to pick the passage; a copied span only
breaks a tie. Current rule: the sentence holding the longest copied run
wins outright, however small that run's share of the claim.

Fairness: one draft per question, reused by both variants; same passages;
only the quote chooser differs. The rewrite step (PARAPHRASE_SYSTEM) runs
per variant, so the assembled plain answer is live.

Run: python artifacts/probes/probe-quote-fix.py
Writes artifacts/evidence/probe-quote-fix/probe-quote-fix.{json,log}.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from prompt import ANSWER_MODEL, PARAPHRASE_SYSTEM, SYSTEM_ANSWER
from retrieve import DEFAULT_EMBEDDER, INDEX, cosine, load_index, ollama_embed

QUESTIONS = [
    "explain data engineering in simple words",
    "explain what a watermark is in simple words",
    "explain CRUD in simple words",
    "explain batch and streaming in simple words",
    "explain data ingestion in simple words",
]


def quote_by_overlap(claim, hit):
    """The candidate: highest claim overlap; a copied span only breaks ties."""
    text = hit.get("text") or ""
    span = A.longest_copied_span(claim, text)
    tokens = A._tokens(claim)
    best, best_key = "", (0.0, False)
    for sentence in A._sentences(text):
        sentence_tokens = A._tokens(sentence)
        if not sentence_tokens:
            continue
        overlap = len(tokens & sentence_tokens) / len(tokens) if tokens else 0.0
        holds = bool(span) and A._fold(span) in A._fold(sentence)
        key = (overlap, holds)
        if best == "" or key > best_key:
            best, best_key = sentence, key
    if best:
        return A._without_heading(best, hit)
    if span:
        return A._original_case(span, text)
    return A._without_heading(re.sub(r"\s+", " ", text).strip(), hit)


def sentence_overlap(claim, sentence):
    tokens = A._tokens(claim)
    if not tokens:
        return 0.0
    return len(tokens & A._tokens(sentence)) / len(tokens)


def variance_of(lines):
    if len(lines) < 2:
        return 0.0
    vectors = ollama_embed(lines, DEFAULT_EMBEDDER)
    worst = 0.0
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            worst = max(worst, cosine(vectors[i], vectors[j]))
    return round(worst, 4)


def citations_with(rule, completion, passages, figures):
    original = A._evidence_quote
    A._evidence_quote = rule
    try:
        return A.parse_answered(completion, passages, figures)
    finally:
        A._evidence_quote = original


def assemble(item):
    rewritten = A.ollama_generate(
        PARAPHRASE_SYSTEM, f"Sentence: {item['quote']}", ANSWER_MODEL
    )
    clean = A._clean_rewrite(rewritten)
    return f"{clean} [Ch. {item['chapter']}]" if clean else ""


def plain_lines(body):
    return [line for item in body["citations"][: A.PARAPHRASE_LIMIT]
            if (line := assemble(item))]


def run_question(index, question):
    record = {"question": question}
    ctx = A.retrieval_context(index, question)
    passages = ctx["passages"]
    figures = index.get("figures") or []
    completion = A.ollama_generate(
        SYSTEM_ANSWER, A.answer_user_message(ctx["asked"], passages), ANSWER_MODEL
    )
    record["draft"] = " ".join(completion.split())
    before = citations_with(A._evidence_quote, completion, passages, figures)
    after = citations_with(quote_by_overlap, completion, passages, figures)
    claims = A._sentence_claims(completion)
    record["claims"] = len(claims)
    # Why a quote changed, per claim: the span, the old sentence's overlap,
    # the new sentence's overlap.
    record["diffs"] = []
    for claim, chapters in claims:
        hit = A._best_passage(claim, chapters, passages)
        if hit is None:
            continue
        span = A.longest_copied_span(claim, hit.get("text") or "")
        old_quote = A._evidence_quote(claim, hit)
        new_quote = quote_by_overlap(claim, hit)
        if old_quote != new_quote:
            record["diffs"].append({
                "chunk_id": hit["chunk_id"],
                "claim": " ".join(claim.split()),
                "span": span,
                "old_quote": old_quote,
                "old_overlap": round(sentence_overlap(claim, old_quote), 3),
                "new_quote": new_quote,
                "new_overlap": round(sentence_overlap(claim, new_quote), 3),
            })
    lines_before = plain_lines(before)
    lines_after = plain_lines(after)
    record["before"] = {
        "answer": " ".join(lines_before),
        "quotes": [c["quote"] for c in before["citations"]],
        "redundancy": variance_of(lines_before),
    }
    record["after"] = {
        "answer": " ".join(lines_after),
        "quotes": [c["quote"] for c in after["citations"]],
        "redundancy": variance_of(lines_after),
    }
    return record


def main():
    index = load_index(INDEX)
    records = []
    lines = []
    for question in QUESTIONS:
        record = run_question(index, question)
        records.append(record)
        lines.append(f"== {question}")
        for diff in record["diffs"]:
            lines.append(f"  change in {diff['chunk_id']}:")
            lines.append(f"    span          : {diff['span']!r}")
            lines.append(f"    old ({diff['old_overlap']}): {diff['old_quote']}")
            lines.append(f"    new ({diff['new_overlap']}): {diff['new_quote']}")
        lines.append(f"  BEFORE (redundancy {record['before']['redundancy']}): {record['before']['answer']}")
        lines.append(f"  AFTER  (redundancy {record['after']['redundancy']}): {record['after']['answer']}")
        lines.append("")
    log = "\n".join(lines)
    (ROOT / "artifacts" / "evidence" / "probe-quote-fix" / "probe-quote-fix.log").write_text(log, encoding="utf-8")
    (ROOT / "artifacts" / "evidence" / "probe-quote-fix" / "probe-quote-fix.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
