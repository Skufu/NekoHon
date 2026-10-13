"""Does adding ch01-018 (Figure 1-3's paragraph) to the MAD queue change the
ask-mode quote and gloss? Variant A: the shipped path. Variant B: the shipped
passages plus ch01-018 after the lead. Same model, same prompts.

Run: python artifacts/probe-mad-seed.py
Writes artifacts/probe-mad-seed.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from prompt import ANSWER_MODEL, SYSTEM
from retrieve import INDEX, load_index

QUESTIONS = ["MAD data landscape", "what is MAD data landscape"]
EXTRA_CHUNK = "ch01-018"


def custom_ask(index, question, passages, figures, generate_fn):
    """answer.ask with a supplied passage list (same prompt, same parsing)."""
    completion = generate_fn(
        SYSTEM, A.user_message(question, passages), ANSWER_MODEL
    )
    anchors = A.anchor_words(question, A.postings(index))
    return A.parse_completion(completion, passages, figures, anchors)


def main():
    index = load_index(INDEX)
    chunks = {c["chunk_id"]: c for c in index["chunks"]}
    figures = index.get("figures") or []
    extra = dict(chunks[EXTRA_CHUNK])
    extra["score"] = None

    records = []
    lines = []
    for question in QUESTIONS:
        for variant in ("A", "B"):
            ctx = A.retrieval_context(index, question)
            passages = ctx["passages"]
            if variant == "B":
                present = any(h["chunk_id"] == EXTRA_CHUNK for h in passages)
                if not present:
                    passages = passages[:1] + [extra] + passages[1:]
            completion = A.ollama_generate(
                SYSTEM, A.user_message(ctx["asked"], passages), ANSWER_MODEL
            )
            body = A.parse_completion(completion, passages, figures,
                                      A.anchor_words(ctx["asked"], ctx["word_map"]))
            record = {
                "question": question,
                "variant": variant,
                "pool": [h["chunk_id"] for h in passages],
                "raw": " ".join(completion.split()),
                "answer": body["answer"],
                "citations": [c["chunk_id"] for c in body["citations"]],
                "figures": [f.get("id") for f in body["figures"]],
                "refused": body["refused"],
            }
            records.append(record)
            lines.append(f"== {variant}: {question}")
            lines.append(f"  pool: {record['pool']}")
            lines.append(f"  RAW : {record['raw'][:700]}")
            lines.append(f"  cites: {record['citations']}  figures: {record['figures']}  refused: {record['refused']}")
            lines.append("")

    log = "\n".join(lines)
    (HERE / "probe-mad-seed.log").write_text(log, encoding="utf-8")
    (HERE / "probe-mad-seed.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
