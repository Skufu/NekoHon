"""Build the audit prompt for the 40 pilot rows (DeepSeek reads it, not us).

The mechanical checks in `assemble-pilot-rows-2026-10-24.py` prove the quote
exists in the passage. They cannot prove the passage answers the question, or
that the history was needed. This prompt asks a second model for exactly those
two judgements, one line per row, with a fixed vocabulary so the answer can be
counted instead of read.
"""

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"

def _path(env_name, default):
    path = Path(os.environ.get(env_name, default))
    return path if path.is_absolute() else ROOT / path


SEEDS = _path("PILOT_SEEDS", FIN / "pilot-seeds-2026-10-24.jsonl")
ANSWERS = _path("PILOT_ANSWERS", FIN / "pilot-answers-2026-10-24.jsonl")
AUDIT_PREFIX = os.environ.get("PILOT_AUDIT_PREFIX", "audit-prompt-2026-10-24")
OUT = ROOT / "artifacts" / "evidence" / "pilot" / f"{AUDIT_PREFIX}.md"
BATCH = 10
CHUNK_RE = re.compile(
    r"\[Ch\. ([^\]]+)\] chunk_id=([a-z0-9-]+)\n(.*?)(?=\n\n\[Ch\. |\n\nCopy one sentence)", re.S)
HISTORY_RE = re.compile(r"Earlier in this conversation.*?:\n(.*?)\n\nQuestion:", re.S)

HEADER = """Audit 40 candidate finetune rows for a local book-answering model.

Each row is one Socratic exchange. The model must answer the FINAL question by
copying one sentence from the passages, then add one plain line of gloss. For
`premise_trap` rows the correct answer is exactly `Not in this book.`

For each row decide KEEP or DROP, and give a code.

DROP when any of these holds:
- wrong_subject: the answer addresses the history question or some other topic, not the final question
- unsupported: the cited sentence, read plainly, does not support the gloss
- history_not_needed: class is entity_relation or simplify, and the answer would be equally correct with the history removed
- trap_answered: class is premise_trap, but the passages do contain the thing asked about
- refusal_missing: class is not premise_trap, but the answer is a refusal
- wrong_relation: class is entity_relation, and the answer does not connect the named entity to the section topic

Do not check quote spelling; that is verified separately.

Reply with one line per row, no preamble, no code fences:
<id> <KEEP|DROP> <code|ok> | <short reason>
"""


def main():
    seeds = {line["id"]: line for line in map(json.loads, Path(SEEDS).read_text(encoding="utf-8").splitlines()) if line}
    answers = {line["id"]: line for line in map(json.loads, Path(ANSWERS).read_text(encoding="utf-8").splitlines()) if line}

    parts = [HEADER]
    blocks = []
    for row_id, seed in seeds.items():
        block = []
        meta = seed["meta"]
        passages = CHUNK_RE.findall(seed["user"])
        history = HISTORY_RE.search(seed["user"])
        final_q = re.search(r"Question: (.+?)\n\n", seed["user"], re.S).group(1).strip()
        block.append(f"\n## {row_id}  class={seed['class']}  book={meta.get('book')}  section={meta.get('heading')!r}")
        if history:
            block.append("history:\n" + history.group(1).strip()[:900])
        block.append("final question: " + final_q)
        for _, chunk_id, text in passages[:3]:
            marker = " <-- target section" if chunk_id == meta.get("target_chunk") else ""
            block.append(f"passage {chunk_id}{marker}:\n{text.strip()[:1100]}")
        block.append("answer: " + answers[row_id]["answer"].strip())
        if seed["class"] == "premise_trap":
            block.append("expected: Not in this book.")
        blocks.append("\n".join(block))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    written = []
    # The free relay returns an empty completion above ~10 rows; batch to fit.
    for index in range(0, len(blocks), BATCH):
        path = OUT.with_name(f"{AUDIT_PREFIX}-{index // BATCH + 1}.md")
        path.write_text("\n".join(parts) + "\n" + "\n".join(blocks[index:index + BATCH]) + "\n",
                        encoding="utf-8")
        written.append((path, len(blocks[index:index + BATCH])))
    for path, count in written:
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size} bytes, {count} rows)")


if __name__ == "__main__":
    main()
