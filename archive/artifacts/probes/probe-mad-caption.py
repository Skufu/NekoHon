"""If the attached figure's caption were quotable passage text, would ask
mode use it for "MAD data landscape"? Variant C: caption after the lead.
Variant D: caption first. Same model, same prompt.

Run: python artifacts/probes/probe-mad-caption.py
Writes artifacts/evidence/probe-mad-caption/probe-mad-caption.{json,log}.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

EVIDENCE = ROOT / "artifacts" / "evidence" / "probe-mad-caption"

import answer as A
from prompt import ANSWER_MODEL, SYSTEM
from retrieve import INDEX, load_index

QUESTIONS = ["MAD data landscape", "what is MAD data landscape"]
CAPTION_ID = "figure-4-1"
CAPTION_TEXT = "Matt Turck's 2021 MAD data landscape"


def main():
    index = load_index(INDEX)
    figures = index.get("figures") or []
    caption_hit = {
        "chunk_id": CAPTION_ID,
        "chapter": "4",
        "text": CAPTION_TEXT,
        "score": None,
    }

    records = []
    lines = []
    for question in QUESTIONS:
        for variant in ("A", "C", "D"):
            ctx = A.retrieval_context(index, question)
            passages = ctx["passages"]
            if variant == "C":
                passages = passages[:1] + [caption_hit] + passages[1:]
            elif variant == "D":
                passages = [caption_hit] + passages
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
    (EVIDENCE / "probe-mad-caption.log").write_text(log, encoding="utf-8")
    (EVIDENCE / "probe-mad-caption.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)


if __name__ == "__main__":
    main()
