"""Plain-register A/B: does an explicit "simple words" instruction actually
simplify the answer, and at what cost to grounding? Artifact, not engine.

Both variants see the same shown passages for each question; only the system
prompt differs. Deterministic metrics:

- Flesch-Kincaid grade (naive syllable count), mean sentence length, share of
  words with three or more syllables, answer length;
- the groundedness meter's support ratio (4-gram rule) and unbacked quote
  spans, because plainness that drifts off the book is not a win.

Run: python artifacts/probes/probe-plain.py
Writes artifacts/evidence/probe-plain/probe-plain.{json,log}.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import answer as A
import groundedness as G
from prompt import ANSWER_MODEL, SYSTEM_ANSWER
from retrieve import INDEX, load_index

PLAIN_ADDITION = (
    "The person asked for a simple explanation. Write it for a newcomer: "
    "one idea per sentence, short sentences, common words. Define each "
    "technical term the first time you use it, in the same sentence. When a "
    "passage holds a concrete example, use that example instead of a second "
    "abstract statement. Do not stack nouns into lists."
)
PLAIN_SYSTEM = SYSTEM_ANSWER + "\n" + PLAIN_ADDITION

# Variant 2: book wording first (keeps the 4-gram grounding up), plain words
# after. The shape a definition-first reader already knows from ask mode.
PLAIN2_ADDITION = (
    "The person asked for a simple explanation. Build it in this order: "
    "(1) copy the passage's own definition sentence for the term, exactly, "
    "with its [Ch. N] tag; (2) then explain that sentence for a newcomer in "
    "short sentences and common words, tagging each claim's chapter; "
    "(3) then one concrete example from the passages, if one exists. "
    "One idea per sentence. Do not stack nouns into lists."
)
PLAIN2_SYSTEM = SYSTEM_ANSWER + "\n" + PLAIN2_ADDITION

# Variant 3: the scorecard's findings applied — no imagined scenarios (Muse
# caught "imagine you have..."), and an explicit sentence-length cap because
# v2 shortened without dropping the grade under the bar.
PLAIN3_ADDITION = (
    "The person asked for a simple explanation. Answer only with what the "
    "passages state: no imagined scenarios, no comparisons, no examples the "
    "passages do not contain. Write short sentences, under fifteen words "
    "each, one idea per sentence. Use common words; if a technical term is "
    "needed, define it in the same sentence. When a passage holds a concrete "
    "example, use that example."
)
PLAIN3_SYSTEM = SYSTEM_ANSWER + "\n" + PLAIN3_ADDITION

# The revise pass: draft with PLAIN3, then one local call edits the draft
# against the passages. Draft for content, edit for style and honesty — the
# same verify-and-fix shape as the reading gate and the judge.
REVISE_SYSTEM = """You edit a draft answer about a book for a newcomer. You see the passages from the book and a draft answer. Rewrite the draft:
1. Remove any claim the passages do not state. Do not add facts.
2. Split every sentence longer than fifteen words into shorter sentences.
3. Use common words; keep technical terms that are necessary.
4. Keep the [Ch. N] tags. When a passage holds a concrete example and the draft has none, add that example.
Output only the revised answer, nothing else."""

# The sentence-aligned paraphrase register: the draft answer supplies the
# evidence sentences (passage text by construction); each is rewritten
# one-in-one-out. Invention has nowhere to go — nothing is written freely.
PARAPHRASE_SYSTEM = """Rewrite one sentence from a book in simpler words for a newcomer. Rewrite the whole sentence and keep all of its meaning: do not summarize it, do not drop any part, and do not add any fact, comparison, or example that is not in the sentence. Keep the subject: every sentence must say who or what does the action — never output a fragment. Use short sentences of fifteen words or fewer. Use common words; keep technical terms that are necessary. Output only the rewritten sentence, nothing else."""

QUESTIONS = [
    "explain data engineering in simple words",
    "explain batch and streaming in simple words",
    "explain data ingestion in simple words",
    "explain what a watermark is in simple words",
    "explain transformations in simple words",
]

TAG = re.compile(r"\[Ch\.[^\]]*\]")


def syllables(word):
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1 and not word.endswith(("le", "ee")):
        count -= 1
    return max(1, count)


def stats(text):
    plain = TAG.sub(" ", text)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", plain) if s.strip()]
    words = re.findall(r"[A-Za-z']+", plain)
    n_sent = max(1, len(sentences))
    n_words = max(1, len(words))
    total_syllables = sum(syllables(word) for word in words)
    grade = 0.39 * (n_words / n_sent) + 11.8 * (total_syllables / n_words) - 15.59
    big = sum(1 for word in words if syllables(word) >= 3)
    return {
        "sentences": len(sentences),
        "words": len(words),
        "mean_sentence": round(n_words / n_sent, 1),
        "fk_grade": round(grade, 1),
        "big_word_share": round(big / n_words, 2),
    }


def grounding(answer, passages):
    grams = set()
    for hit in passages:
        grams |= G.grams(G.content_tokens(hit.get("text") or ""))
    sentences = G.answer_sentences(answer)
    covered = []
    for sentence in sentences:
        value = G.sentence_coverage(sentence, grams)
        if value is not None:
            covered.append(value)
    supported = sum(1 for value in covered if value >= G.SUPPORT)
    mean = round(sum(covered) / len(covered), 3) if covered else None
    return {"sentences": len(covered), "supported": supported, "mean_coverage": mean}


def run_variant(index, question, system, passages):
    completion = A.ollama_generate(
        system, A.answer_user_message(question, passages), ANSWER_MODEL
    )
    body = A.parse_answered(completion, passages, index.get("figures") or [])
    return {
        "answer": body["answer"],
        "citations": [c["chunk_id"] for c in body["citations"]],
        "stats": stats(body["answer"]),
        "grounding": grounding(body["answer"], passages),
        "fake_quotes": G.fake_quotes(completion, passages),
    }


def main():
    index = load_index(INDEX)
    rows = []
    for question in QUESTIONS:
        passages = A.retrieval_context(index, question)["passages"]
        current = run_variant(index, question, SYSTEM_ANSWER, passages)
        plain = run_variant(index, question, PLAIN_SYSTEM, passages)
        plain2 = run_variant(index, question, PLAIN2_SYSTEM, passages)
        rows.append({
            "question": question,
            "current": current,
            "plain": plain,
            "plain2": plain2,
        })
        print(question)
        print("  current:", current["stats"], current["grounding"])
        print("  plain:  ", plain["stats"], plain["grounding"])
        print("  plain2: ", plain2["stats"], plain2["grounding"])

    def mean(key, sub):
        values = [row[key]["stats"][sub] for row in rows]
        return round(sum(values) / len(values), 2)

    def mean_ground(key, sub):
        values = [
            row[key]["grounding"][sub] for row in rows
            if row[key]["grounding"][sub] is not None
        ]
        return round(sum(values) / len(values), 3) if values else None

    lines = [
        f"# plain-register A/B — {ANSWER_MODEL} — {len(rows)} questions",
        "# same shown passages per question; only the system prompt differs",
        f"# fk grade: current {mean('current', 'fk_grade')}"
        f" | plain {mean('plain', 'fk_grade')}"
        f" | plain2 {mean('plain2', 'fk_grade')}"
        f" | mean sentence: {mean('current', 'mean_sentence')}"
        f" | plain {mean('plain', 'mean_sentence')}"
        f" | plain2 {mean('plain2', 'mean_sentence')}",
        f"# big-word share: {mean('current', 'big_word_share')}"
        f" | plain {mean('plain', 'big_word_share')}"
        f" | plain2 {mean('plain2', 'big_word_share')}"
        f" | words: {mean('current', 'words')}"
        f" | plain {mean('plain', 'words')} | plain2 {mean('plain2', 'words')}",
        f"# groundedness mean coverage: {mean_ground('current', 'mean_coverage')}"
        f" | plain {mean_ground('plain', 'mean_coverage')}"
        f" | plain2 {mean_ground('plain2', 'mean_coverage')}"
        f" | unbacked quote spans:"
        f" {sum(len(row['current']['fake_quotes']) for row in rows)}"
        f" | plain {sum(len(row['plain']['fake_quotes']) for row in rows)}"
        f" | plain2 {sum(len(row['plain2']['fake_quotes']) for row in rows)}",
        "",
    ]
    for row in rows:
        c = row["current"]
        p = row["plain"]
        lines.append(f"## {row['question']}")
        lines.append(
            f"- current: fk {c['stats']['fk_grade']}"
            f" | mean sentence {c['stats']['mean_sentence']}"
            f" | supported {c['grounding']['supported']}/{c['grounding']['sentences']}"
            f" | {c['answer'].splitlines()[0][:110]}"
        )
        lines.append(
            f"- plain:   fk {p['stats']['fk_grade']}"
            f" | mean sentence {p['stats']['mean_sentence']}"
            f" | supported {p['grounding']['supported']}/{p['grounding']['sentences']}"
            f" | {p['answer'].splitlines()[0][:110]}"
        )
        q = row["plain2"]
        lines.append(
            f"- plain2:  fk {q['stats']['fk_grade']}"
            f" | mean sentence {q['stats']['mean_sentence']}"
            f" | supported {q['grounding']['supported']}/{q['grounding']['sentences']}"
            f" | {q['answer'].splitlines()[0][:110]}"
        )
    out = ROOT / "artifacts" / "runs" / "probe-plain" / "probe-plain.json"
    log = out.with_suffix(".log")
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:5]))
    print("wrote", out.name, "and", log.name)


if __name__ == "__main__":
    main()
