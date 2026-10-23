"""The prefix rule, measured. Bare topical phrases (no "?", no wh-word):
does "MAD data landscape" behave like "What is MAD data landscape?" when the
prefix reaches the prompt (V1) or the prompt and the retrieval query (V2)?

Controls: the two battery questions the structural rule would touch
(MAD probe, multicloud probe), both modes; a bare out-of-book phrase must
still refuse.

Run: python artifacts/probes/probe-prefix-rule.py
Writes artifacts/evidence/probe-prefix-rule/probe-prefix-rule.{json,log}.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-prefix-rule"

import answer as A
from prompt import ANSWER_MODEL, SYSTEM, SYSTEM_ANSWER
from retrieve import INDEX, load_index

QUESTIONS = [
    ("MAD data landscape", "ch04-020"),
    ("multicloud methodology disadvantages", "ch04-037"),
]
BARE_REFUSAL = "capital of France"
WH = re.compile(r"\b(what|which|when|where|who|whose|why|how)\b")
AUX_START = {
    "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "has", "have", "had",
}


def is_bare(question):
    folded = (question or "").lower().strip()
    words = folded.split()
    if not words or "?" in folded:
        return False
    if WH.search(folded):
        return False
    return words[0] not in AUX_START


def prefixed(question):
    return f"What is {question}?"


def respond_v1(index, retrieval_q, prompt_q):
    """Retrieval on one question, prompt on another; the shipped parse."""
    ctx = A.retrieval_context(index, retrieval_q)
    passages = ctx["passages"]
    if not passages:
        return A._refusal([])
    completion = A.ollama_generate(
        SYSTEM_ANSWER, A.answer_user_message(prompt_q, passages), ANSWER_MODEL
    )
    return A.parse_answered(completion, passages, index.get("figures") or [])


def ask_v1(index, retrieval_q, prompt_q):
    ctx = A.retrieval_context(index, retrieval_q)
    passages = ctx["passages"]
    if not passages:
        return A._refusal([])
    completion = A.ollama_generate(
        SYSTEM, A.user_message(prompt_q, passages), ANSWER_MODEL
    )
    anchors = A.anchor_words(retrieval_q, ctx["word_map"])
    return A.parse_completion(completion, passages, index.get("figures") or [], anchors)


def row_of(body):
    first = body["citations"][0] if body["citations"] else {}
    return {
        "refused": body["refused"],
        "answer": " ".join(body["answer"].split())[:300],
        "cites": [c["chunk_id"] for c in body["citations"]][:6],
        "figs": [f.get("id") for f in body["figures"]],
        "chunk": first.get("chunk_id"),
        "quote": " ".join((first.get("quote") or "").split())[:120],
    }


def main():
    index = load_index(INDEX)
    records = []
    lines = []

    bare = "benign"
    if is_bare(BARE_REFUSAL):
        body = A.respond(index, prefixed(BARE_REFUSAL))
        out = row_of(body)
        bare = "refused" if out["refused"] else "ANSWERED (BAD)"
        records.append({"case": BARE_REFUSAL, "mode": "answer", "variant": "V2",
                        **out})
        lines.append(f"bare refusal {BARE_REFUSAL!r}: {bare}")
        lines.append("")

    for question, pin in QUESTIONS:
        assert is_bare(question), question
        lines.append(f"== {question}  (bare={is_bare(question)}, pin {pin})")
        for draw in (1, 2):
            for variant in ("V0", "V1", "V2"):
                if variant == "V0":
                    body = A.respond(index, question)
                elif variant == "V1":
                    body = respond_v1(index, question, prefixed(question))
                else:
                    body = A.respond(index, prefixed(question))
                out = row_of(body)
                records.append({"case": question, "mode": "answer",
                                "variant": variant, "draw": draw, **out})
                lines.append(
                    f"  [{variant} d{draw}] cites={out['cites']} figs={out['figs']}"
                )
                lines.append(f"      {out['answer'][:220]}")
        for variant in ("V0", "V1", "V2"):
            if variant == "V0":
                body = A.ask(index, question)
            elif variant == "V1":
                body = ask_v1(index, question, prefixed(question))
            else:
                body = A.ask(index, prefixed(question))
            out = row_of(body)
            ok = out["chunk"] == pin and not out["refused"]
            records.append({"case": question, "mode": "ask", "variant": variant,
                            "pin_ok": ok, **out})
            lines.append(
                f"  ask [{variant}] {'ok ' if ok else 'KO '}chunk={out['chunk']} "
                f"(pin {pin}) refused={out['refused']}"
            )
            lines.append(f"      quote: {out['quote']}")
        lines.append("")

    log = "\n".join(lines)
    (EVIDENCE / "probe-prefix-rule.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-prefix-rule.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
