"""Groundedness meter for the answer mode. Artifact, not engine.

Answer mode measures hallucination instead of refusing it. For each question
this runner recomputes the passages the model is shown (the same
answer.retrieval_context the server uses), generates the same free answer,
and reports how much of each answer sentence is a word-for-word run from
those passages: a sentence is supported when at least SUPPORT of its 4-grams
appear in the shown passages. It also counts quotation marks the passages
cannot back — the marks the engine strips — so the raw completion is measured
before the strip.

Run: python artifacts/harnesses/groundedness.py --label answer [--limit N]
     python artifacts/harnesses/groundedness.py --battery        (the battery questions)
Writes artifacts/runs/groundedness/groundedness-<label>.{json,log}.
"""

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.answering import answer as A
from engine.answering.prompt import ANSWER_MODEL, SYSTEM_ANSWER
from engine.retrieval.retrieve import INDEX, load_index

# A sentence whose 4-grams are mostly in the shown passages is supported.
# Majority is the definition of supported here; the number is not tuned to
# any question.
SUPPORT = 0.5
NGRAM = 4


def content_tokens(text):
    """Tag-stripped, punctuation-plain words. [Ch. 2] must not count."""
    plain = A.TAG_PATTERN.sub(" ", text or "")
    return A._punctuation_plain(plain).split()


def grams(tokens, n=NGRAM):
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def answer_sentences(answer):
    """Testable sentences: the model's prose, no Read-as line, 4-gram-able.

    Tags are removed before the sentence split: "Ch." holds a period and
    would otherwise end a sentence inside the tag (the same trap
    answer._sentence_claims masks around).
    """
    lines = [
        line for line in (answer or "").splitlines()
        if not line.strip().startswith("Read as:")
    ]
    text = A.TAG_PATTERN.sub(" ", " ".join(lines)).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if len(content_tokens(part)) >= NGRAM]


def sentence_coverage(sentence, passage_grams):
    found = grams(content_tokens(sentence))
    if not found:
        return None
    return len(found & passage_grams) / len(found)


def fake_quotes(completion, passages):
    """Quotation spans no shown passage contains, measured pre-strip."""
    spans = []
    for match in A.QUOTE_PATTERN.finditer(completion or ""):
        inner = match.group(1)
        if not any(
            A._quote_in_passage(inner, hit.get("text") or "") for hit in passages
        ):
            spans.append(inner)
    return spans


def battery_questions():
    """The battery's own lists, one source of truth."""
    path = ROOT / "artifacts" / "harnesses" / "step2-battery.py"
    spec = importlib.util.spec_from_file_location("step2_battery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return (
        [q for q, _ in module.GOLDEN_PINS]
        + [q for q, _, _ in module.TYPOS]
        + [q for q, _, _ in module.PROBES]
        + [q for q, _, _ in module.COHERENCE]
    )


def load_questions(path):
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    questions = []
    for item in data:
        if isinstance(item, str):
            questions.append(item)
        elif isinstance(item, dict) and item.get("question"):
            questions.append(item["question"])
    return questions


def measure(index, question, generate_fn, timeout, system):
    context = A.retrieval_context(index, question)
    passages = context["passages"]
    if not passages:
        return {"question": question, "refused": True, "empty": True}
    completion = generate_fn(
        system, A.answer_user_message(context["asked"], passages),
        ANSWER_MODEL, timeout,
    )
    body = A.parse_answered(completion, passages, index.get("figures") or [])
    passage_grams = set()
    for hit in passages:
        passage_grams |= grams(content_tokens(hit.get("text") or ""))
    sentences = answer_sentences(body["answer"])
    coverage = []
    for sentence in sentences:
        value = sentence_coverage(sentence, passage_grams)
        coverage.append({
            "sentence": sentence,
            "coverage": round(value, 3) if value is not None else None,
            "supported": value is not None and value >= SUPPORT,
        })
    testable = [item for item in coverage if item["coverage"] is not None]
    supported = [item for item in testable if item["supported"]]
    return {
        "question": question,
        "asked": context["asked"],
        "refused": body["refused"],
        "answer": body["answer"],
        "citations": [item["chunk_id"] for item in body["citations"]],
        "sentences": len(testable),
        "supported": len(supported),
        "mean_coverage": (
            round(sum(item["coverage"] for item in testable) / len(testable), 3)
            if testable else None
        ),
        "fake_quotes": fake_quotes(completion, passages),
        "untraceable": [
            item["sentence"][:160] for item in testable if not item["supported"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Groundedness meter, answer mode.")
    parser.add_argument("--label", default="answer")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--questions", default=str(ROOT / "artifacts" / "datasets" / "qa-questions-overnight.json")
    )
    parser.add_argument("--battery", action="store_true")
    parser.add_argument(
        "--system-text", default="",
        help="compare a draft system prompt without touching prompt.py",
    )
    args = parser.parse_args()

    # Default here is SYSTEM_ANSWER. The live server path is SYSTEM
    # (answer.py respond / ask). Pass --system-text to measure the live prompt.
    system = SYSTEM_ANSWER
    if args.system_text:
        system = Path(args.system_text).read_text(encoding="utf-8").strip()

    questions = battery_questions() if args.battery else load_questions(args.questions)
    if args.limit:
        questions = questions[:args.limit]
    out = ROOT / "artifacts" / "runs" / "groundedness" / f"groundedness-{args.label}.json"
    log = out.with_suffix(".log")

    index = load_index(INDEX)

    def generate(system, user, model, timeout):
        return A.ollama_generate(system, user, model, timeout=timeout)

    rows = []
    for position, question in enumerate(questions, start=1):
        started = time.perf_counter()
        row = measure(index, question, generate, args.timeout, system)
        row["seconds"] = round(time.perf_counter() - started, 2)
        rows.append(row)
        if row.get("empty"):
            line = f"EMPTY {row['question']}"
        elif row["refused"]:
            line = f"refused  0/0  fakeq {len(row['fake_quotes'])}  {row['question']}"
        else:
            line = (
                f"support {row['supported']}/{row['sentences']} "
                f"mean {row['mean_coverage']} "
                f"fakeq {len(row['fake_quotes'])} "
                f"cites {','.join(row['citations']) or '-'}  {row['question']}"
            )
        print(line)
        if position % 25 == 0:
            print(f"  {position}/{len(questions)}")

    answered = [row for row in rows if not row.get("empty") and not row["refused"]]
    testable = sum(row["sentences"] for row in answered)
    supported = sum(row["supported"] for row in answered)
    fake = sum(len(row["fake_quotes"]) for row in answered)
    mean = (
        round(sum(row["mean_coverage"] * row["sentences"] for row in answered)
              / testable, 3)
        if testable else None
    )
    lines = [
        f"# groundedness — {args.label} — {len(rows)} asks — model {ANSWER_MODEL}",
        f"# answered: {len(answered)} | refused: {len(rows) - len(answered)}"
        f" | sentences: {testable} | supported: {supported}"
        f" ({round(100 * supported / testable, 1) if testable else 0}%)"
        f" | mean coverage: {mean} | fake quote spans: {fake}",
        "",
    ]
    for row in answered:
        if row["fake_quotes"] or row["untraceable"]:
            lines.append(f"## {row['question']}")
            for span in row["fake_quotes"]:
                lines.append(f"- unbacked quote: {span[:120]}")
            for sentence in row["untraceable"]:
                lines.append(f"- untraceable: {sentence}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:2]))
    print("wrote", out.name, "and", log.name)


if __name__ == "__main__":
    main()
