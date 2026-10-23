"""Independent verification of the finetune dataset files.

Reads the JSONL files cold and checks every row against what the app would
see: the shipped SYSTEM prompt; the user message's passage format; the
assistant target (refusal exactness; [Ch. N] line; the quote verbatim
inside the cited chunk's block; the chapter tag matching the index); gloss
presence; meta consistency; split disjointness; question dedup.

Exit 1 on any failure. Run: python artifacts/probes/probe-finetune-verify-2026-10-13.py
Writes artifacts/evidence/probe-finetune-verify/probe-finetune-verify-2026-10-13.{json,log}.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from prompt import SYSTEM
from retrieve import INDEX, load_index
import answer as A

DATASET = ROOT / "data" / "finetune" / "quote-refuse-2026-10-13.{}.jsonl"
BLOCK = re.compile(r"\[Ch\. (\S+)\] chunk_id=([A-Za-z0-9-]+)\n")
QUOTE_LINE = re.compile(r'^\[Ch\. (\d+)\] "(.*)"$')


def check_file(name, chunks):
    path = DATASET.with_name(DATASET.name.format(name))
    failures = []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append((number, json.loads(line)))
        except json.JSONDecodeError as error:
            failures.append(f"line {number}: not JSON ({error})")

    questions = []
    counts = {"answer": 0, "refusal": 0}
    normalized_only = 0
    for number, row in rows:
        where = f"{name}:{number}"
        messages = row.get("messages") or []
        roles = [m.get("role") for m in messages]
        if roles != ["system", "user", "assistant"]:
            failures.append(f"{where}: roles {roles}")
            continue
        meta = row.get("meta") or {}
        if messages[0]["content"] != SYSTEM:
            failures.append(f"{where}: system prompt differs from prompt.SYSTEM")
        user = messages[1]["content"]
        assistant = messages[2]["content"]
        if not user.startswith("Question: ") or "\nPassages:\n" not in user:
            failures.append(f"{where}: user message shape")
        blocks = {}
        for match in BLOCK.finditer(user):
            blocks[match.group(2)] = user[match.end():]
        if not blocks:
            failures.append(f"{where}: no passage blocks parsed")
        if any(chunk_id not in chunks for chunk_id in blocks):
            failures.append(f"{where}: unknown chunk in passage blocks {list(blocks)}")
        if meta.get("split") != name:
            failures.append(f"{where}: meta.split {meta.get('split')!r} != {name}")
        questions.append((meta.get("question"), bool(meta.get("oversampled"))))
        if meta.get("tier") == "refusal":
            counts["refusal"] += 1
            if assistant != "Not in this book.":
                failures.append(f"{where}: refusal target {assistant[:60]!r}")
            continue
        counts["answer"] += 1
        lines = assistant.splitlines()
        if len(lines) != 2 or not lines[1].strip():
            failures.append(f"{where}: target is not quote-line + gloss-line")
            continue
        match = QUOTE_LINE.match(lines[0])
        if not match:
            failures.append(f"{where}: quote line {lines[0][:60]!r}")
            continue
        chapter, quote = match.group(1), match.group(2)
        if lines[1].strip().startswith("[Ch.") or lines[1].strip() == quote:
            failures.append(f"{where}: gloss line suspicious {lines[1][:60]!r}")
        cited = (meta.get("cited") or [None])[0]
        if cited not in blocks:
            failures.append(f"{where}: cited {cited!r} not among shown passages")
        else:
            # The app's own rule: A._quote_in_passage folds typography and
            # strips figure references; a byte-exact mismatch that still
            # passes the rule is app-sanctioned (measured: 13 such rows,
            # all omitted "(Figure X-Y)" runs).
            if not A._quote_in_passage(quote, blocks[cited]):
                failures.append(f"{where}: quote fails the app's quote rule")
            elif quote not in blocks[cited]:
                normalized_only += 1
            index_chapter = str(chunks.get(cited, {}).get("chapter"))
            if chapter != index_chapter:
                failures.append(
                    f"{where}: [Ch. {chapter}] but index says ch{index_chapter}"
                )
    question_counts = Counter(question for question, _ in questions)
    accidental = [
        question for question, count in question_counts.items()
        if count > 1 and not all(
            flag for q, flag in questions if q == question
        )
    ]
    if accidental:
        failures.append(f"{name}: {len(accidental)} accidental duplicate questions")
    return rows, counts, questions, failures, normalized_only


def main():
    index = load_index(INDEX)
    chunks = {c["chunk_id"]: c for c in index["chunks"]}

    report = {}
    lines = []
    train_questions = []
    all_failures = []
    for name in ("train", "bench"):
        rows, counts, questions, failures, normalized_only = check_file(name, chunks)
        report[name] = {"rows": len(rows), **counts, "failures": failures,
                        "normalized_only": normalized_only}
        question_strings = [q for q, _ in questions]
        train_questions = question_strings if name == "train" else train_questions
        if name == "bench":
            overlap = set(train_questions) & set(question_strings)
            if overlap:
                failures.append(f"train/bench question overlap: {sorted(overlap)[:5]}")
            report["train/bench overlap"] = len(overlap)
        lines.append(
            f"{name}: {len(rows)} rows ({counts['answer']} answer / "
            f"{counts['refusal']} refusal), {normalized_only} normalized-only "
            f"quotes (app rule passes), failures: {len(failures)}"
        )
        for failure in failures[:10]:
            lines.append(f"   {failure}")
        all_failures += failures
    lines.append(f"total failures: {len(all_failures)}")
    lines.append(f"verdict: {'PASS' if not all_failures else 'FAIL'}")

    log = "\n".join(lines)
    (ROOT / "artifacts" / "evidence" / "probe-finetune-verify" / "probe-finetune-verify-2026-10-13.log").write_text(log, encoding="utf-8")
    (ROOT / "artifacts" / "evidence" / "probe-finetune-verify" / "probe-finetune-verify-2026-10-13.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(log)
    sys.exit(0 if not all_failures else 1)


if __name__ == "__main__":
    main()
