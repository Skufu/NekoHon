"""Validate the 40 pilot answers and emit trainable rows.

Every check here exists because a previous corpus failed it:

- quote must appear verbatim in the passages shown for the final turn, not just
  somewhere in the book (round 4 assembled targets answered the wrong passage);
- the quote must come from the target section, so the row teaches the follow-up
  and not the history (audit: 10/13 coreference rows answered the wrong subject);
- a refusal row is kept only when the answer is exactly `Not in this book.`;
  any other refusal is a miss, not a target;
- no row may duplicate the 844-row corpus once the history is stripped.

Reads  data/finetune/pilot-seeds-2026-10-24.jsonl
       data/finetune/pilot-answers-2026-10-24.jsonl
Writes data/finetune/pilot-rows-2026-10-24.jsonl (kept only)
       artifacts/evidence/pilot/assemble-summary.json
"""

import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data" / "finetune"

def _path(env_name, default):
    path = Path(os.environ.get(env_name, default))
    return path if path.is_absolute() else ROOT / path


SEEDS = _path("PILOT_SEEDS", FIN / "pilot-seeds-2026-10-24.jsonl")
ANSWERS = _path("PILOT_ANSWERS", FIN / "pilot-answers-2026-10-24.jsonl")
CORPUS = FIN / "quote-refuse-2026-10-17.train-x3.jsonl"
OUT = _path("PILOT_ROWS_OUT", FIN / "pilot-rows-2026-10-24.jsonl")
EVIDENCE = _path("PILOT_EVIDENCE_OUT",
                 ROOT / "artifacts" / "evidence" / "pilot" / "assemble-summary.json")
REFUSAL = "Not in this book."
QUOTE_RE = re.compile(r'^\[Ch\.\s*([^\]]+)\]\s*["“](.+?)["”]\s*$', re.M)
CHUNK_RE = re.compile(
    r"\[Ch\. ([^\]]+)\] chunk_id=([a-z0-9-]+)\n(.*?)(?=\n\n\[Ch\. |\n\nCopy one sentence)", re.S)


def fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def jsonl(path):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def digest(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def passages_of(user):
    return {chunk: text.strip() for _, chunk, text in CHUNK_RE.findall(user)}


def main():
    seeds = {row["id"]: row for row in jsonl(SEEDS)}
    answers = {row["id"]: row for row in jsonl(ANSWERS)}
    x3 = {digest(row["messages"]) for row in jsonl(CORPUS)}

    kept, drops, detail = [], Counter(), []
    for row_id, seed in seeds.items():
        answer = (answers.get(row_id) or {}).get("answer", "").strip()
        row_class = seed["class"]
        meta = seed["meta"]
        passages = passages_of(seed["user"])
        target = meta.get("target_chunk", "")
        reason = ""

        if not answer:
            reason = "empty"
        elif answers[row_id].get("finish") != "stop":
            reason = "unfinished"

        if not reason and row_class == "premise_trap":
            if answer != REFUSAL:
                reason = "trap_answered"
        elif not reason:
            match = QUOTE_RE.search(answer)
            if not match:
                reason = "no_quote"
            else:
                quote = match.group(2)
                folded_quote = fold(quote)
                if len(folded_quote) < 20:
                    reason = "quote_too_short"
                elif (row_class == "entity_relation" and target in passages
                      and folded_quote not in fold(passages[target])):
                    reason = "quote_not_in_target"
                elif not any(folded_quote in fold(text) for text in passages.values()):
                    reason = "quote_not_in_any_passage"
                else:
                    history_text = fold(json.dumps(seed.get("meta", {}), ensure_ascii=False))
                    gloss = answer[match.end():].strip()
                    if not gloss:
                        reason = "no_gloss"
                    elif folded_quote and folded_quote in history_text:
                        reason = "quote_from_history"

        if not reason:
            messages = [
                {"role": "system", "content": seed["system"]},
                {"role": "user", "content": seed["user"]},
                {"role": "assistant", "content": answer},
            ]
            if digest(messages) in x3:
                reason = "dup_x3"
            else:
                kept.append({"messages": messages})
                detail.append({"id": row_id, "class": row_class, "question": seed["meta"].get("anchor_question"),
                               "answer_head": answer[:160]})
        if reason:
            drops[reason] += 1
            detail.append({"id": row_id, "class": row_class, "dropped": reason})

    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept),
                   encoding="utf-8")
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "seeds": len(seeds), "answers": len(answers), "kept": len(kept),
        "drops": dict(drops),
        "by_class": dict(Counter(row["class"] for row in seeds.values())),
        "kept_by_class": dict(Counter(
            seed["class"] for row_id, seed in seeds.items()
            if any(d["id"] == row_id and "dropped" not in d for d in detail))),
        "detail": detail,
    }
    EVIDENCE.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"kept {len(kept)}/{len(seeds)} -> {OUT.relative_to(ROOT)}")
    print("drops:", dict(drops))
    print("kept by class:", summary["kept_by_class"])
    if drops:
        for item in detail:
            if "dropped" in item:
                print("  DROP", item["id"], item["class"], item["dropped"])
    return 0 if kept else 1


if __name__ == "__main__":
    sys.exit(main())
