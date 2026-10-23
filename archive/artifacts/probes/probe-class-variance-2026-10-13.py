"""Canonicalization Stage 0 fixture: per-surface-variant behavior baseline.

For each question, five surface variants, both modes, one draw. Records
(refused, cited chunks, figure ids) and the R1 trigger's verdict per
variant, so the collapse projection is visible: every variant the trigger
fires on will behave as `What is {q}?` after Stage 1.

Run: python artifacts/probes/probe-class-variance-2026-10-13.py
Writes artifacts/evidence/probe-class-variance/probe-class-variance-2026-10-13.{json,log}.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-class-variance"

import answer as A
from retrieve import INDEX, load_index

QUESTIONS = ["MAD data landscape", "data mesh", "watermark", "data ingestion"]

WH = re.compile(r"\b(what|which|when|where|who|whose|why|how)\b")
AUX = {"is", "are", "was", "were", "do", "does", "did", "can", "could",
       "should", "would", "will", "has", "have", "had"}
OPENERS = {"hey", "hi", "hello", "please", "pls", "tell", "show", "give",
           "explain", "describe", "define", "compare", "contrast", "list",
           "types", "kinds", "examples", "difference"}
PRONOUNS = {"i", "me", "my", "mine", "you", "your", "we", "our", "us"}


def r1_fires(question):
    """The Stage 0 spec: structural guards only."""
    text = (question or "").strip()
    folded = text.lower()
    words = folded.split()
    if not words:
        return False
    if "?" in folded or text.endswith((".", "!")):
        return False
    if WH.search(folded):
        return False
    if words[0] in AUX or words[0] in OPENERS:
        return False
    return not any(word in PRONOUNS for word in words)


def variants(question):
    return [
        question,
        f"What is {question}",
        f"What is {question}?",
        f"hey can you tell me about {question}",
        f"explain {question}",
    ]


def behavior(body):
    return {
        "refused": body["refused"],
        "cites": [c["chunk_id"] for c in body["citations"]],
        "figs": [f.get("id") for f in body["figures"]],
        "head": " ".join(body["answer"].split())[:110],
    }


def main():
    index = load_index(INDEX)
    records = []
    lines = []
    for question in QUESTIONS:
        canonical = f"What is {question}?"
        for mode in ("ask", "answer"):
            run = A.ask if mode == "ask" else A.respond
            lines.append(f"== {question} | {mode}")
            by_variant = {}
            for variant in variants(question):
                body = run(index, variant)
                key = behavior(body)
                by_variant[variant] = key
                record = {
                    "question": question,
                    "mode": mode,
                    "variant": variant,
                    "r1_fires": r1_fires(variant),
                    "canonical": canonical,
                    **key,
                }
                records.append(record)
                lines.append(
                    f"  r1={'Y' if record['r1_fires'] else 'n'} "
                    f"refused={key['refused']!s:5} "
                    f"figs={len(key['figs'])} cites={key['cites'][:4]}"
                )
                lines.append(f"    {variant!r} -> {key['head'][:90]}")
            canon_key = by_variant.get(canonical)
            behaving = {
                v: (k["refused"], tuple(k["cites"]), tuple(k["figs"]))
                for v, k in by_variant.items()
            }
            target = (canon_key["refused"], tuple(canon_key["cites"]),
                      tuple(canon_key["figs"]))
            distinct = len({v for v in behaving.values()})
            collapse = [
                v for v, k in behaving.items() if r1_fires(v) and k != target
            ]
            lines.append(
                f"  distinct behaviors: {distinct}; R1 variants that would "
                f"change behavior: {len(collapse)} {collapse}"
            )
            lines.append("")
    log = "\n".join(lines)
    (EVIDENCE / "probe-class-variance-2026-10-13.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-class-variance-2026-10-13.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
