"""LLM spell-enhancement probe. Artifact, not engine.

Compares the current self-proving reading (`readings.second_reading`) with an
LLM corrector built on the article's prompt (adapted: "book search query",
query injected at the end). Both are judged by the same gate the engine
already trusts: a correction is kept only when the enhanced query's best
dense score strictly beats the literal one. Trap cases are included on
purpose — correct queries that must not change, and an acronym that must not
be expanded.

The visible line, if wired, stays `Read as: "..."` (already in the answer,
no contract change). This probe measures before any wiring.

Run: python artifacts/probes/probe-llm-spell.py
Writes artifacts/evidence/probe-llm-spell/probe-llm-spell.{json,log}.
"""

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

import answer as A
from keywords import postings
from prompt import ANSWER_MODEL
from readings import second_reading
from retrieve import INDEX, load_index, search

SPELL_SYSTEM = """Fix any spelling errors in the user-provided book search query below.
Correct only clear, high-confidence typos. Do not rewrite, add, remove, or reorder words.
Preserve punctuation and capitalization unless a change is required for a typo fix.
If there are no spelling errors, or if you're unsure, output the original query unchanged.
Output only the final query text, nothing else."""

CASES = [
    {"query": "what is a atermark?", "target": "ch08-039", "class": "single-typo"},
    {"query": "wa termark", "target": "ch08-039", "class": "split-word"},
    {"query": "what is watermrak", "target": "ch08-039", "class": "swap"},
    {"query": "What does CRU stand for?", "target": "ch05-019", "class": "acronym"},
    {"query": "what is normilazation", "target": "ch08-051", "class": "single-typo"},
    {"query": "what is data ingestoin", "target": "ch07-002", "class": "single-typo"},
    {"query": "dark matter data", "target": None, "class": "trap-term"},
    {"query": "what is data mesh", "target": None, "class": "trap-clean"},
    {"query": "What is the capital of France?", "target": None, "class": "trap-clean"},
    {"query": "what does iops mean", "target": None, "class": "trap-acronym"},
]


def clean(text):
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip()


def top10(index, question):
    hits = search(index, question, k=10)
    return hits, (hits[0]["score"] if hits else 0.0)


def rank_of(hits, target):
    for position, hit in enumerate(hits, start=1):
        if hit["chunk_id"] == target:
            return position
    return None


def main():
    index = load_index(INDEX)
    word_map = postings(index)
    rows = []
    for case in CASES:
        question = case["query"]
        target = case["target"]
        literal_hits, literal_top = top10(index, question)

        reading = second_reading(index, question, literal_top, word_map=word_map)
        reading_row = {"kept": False}
        if reading:
            reading_hits, _ = top10(index, reading["reading"])
            reading_row = {
                "kept": True,
                "reading": reading["reading"],
                "top_chunk": reading["chunk"]["chunk_id"],
                "target_rank": rank_of(reading_hits, target) if target else None,
            }

        started = time.perf_counter()
        llm_raw = A.ollama_generate(
            SPELL_SYSTEM, f'User query: "{question}"', ANSWER_MODEL
        )
        llm_seconds = round(time.perf_counter() - started, 2)
        enhanced = clean(llm_raw)
        changed = enhanced.strip().lower() != question.strip().lower()
        llm_row = {"seconds": llm_seconds, "raw": llm_raw[:200], "enhanced": enhanced,
                   "changed": changed, "kept": False}
        if changed:
            enhanced_hits, enhanced_top = top10(index, enhanced)
            llm_row["enhanced_top"] = round(enhanced_top, 3)
            llm_row["target_rank"] = rank_of(enhanced_hits, target) if target else None
            llm_row["kept"] = enhanced_top > literal_top
        rows.append({
            "class": case["class"],
            "query": question,
            "target": target,
            "literal_top": round(literal_top, 3),
            "literal_target_rank": rank_of(literal_hits, target) if target else None,
            "reading": reading_row,
            "llm": llm_row,
        })

    fixed = [r for r in rows if r["class"] != "trap-term" and not r["class"].startswith("trap")]
    reading_kept = [r for r in fixed if r["reading"]["kept"]]
    llm_changed = [r for r in fixed if r["llm"]["changed"]]
    llm_kept = [r for r in fixed if r["llm"]["kept"]]
    traps = [r for r in rows if r["class"].startswith("trap")]
    traps_safe = [
        r for r in traps if (not r["llm"]["changed"]) or (not r["llm"]["kept"])
    ]
    reading_hits_target = [
        r for r in reading_kept if r["reading"]["target_rank"] is not None
    ]
    llm_hits_target = [r for r in llm_kept if r["llm"]["target_rank"] is not None]

    lines = [
        f"# llm spell probe — {ANSWER_MODEL} — {len(rows)} cases"
        f" ({len(fixed)} typo, {len(traps)} trap)",
        f"# reading kept {len(reading_kept)}/{len(fixed)}"
        f" (target in top-10: {len(reading_hits_target)}"
        f" of {len([r for r in reading_kept if r['target']])})",
        f"# llm changed {len(llm_changed)}/{len(fixed)}"
        f" | llm kept by the gate {len(llm_kept)}/{len(fixed)}"
        f" (target in top-10: {len(llm_hits_target)}"
        f" of {len([r for r in llm_kept if r['target']])})",
        f"# traps safe (unchanged or gate-discarded): {len(traps_safe)}/{len(traps)}",
        "",
    ]
    for row in rows:
        reading = row["reading"]
        llm = row["llm"]
        reading_note = (
            f'reading kept -> "{reading["reading"]}" ({reading["top_chunk"]})'
            if reading["kept"] else "reading none"
        )
        llm_note = (
            f'changed -> "{llm["enhanced"]}" kept={llm["kept"]}'
            if llm["changed"] else "unchanged"
        )
        lines.append(
            f'- [{row["class"]}] "{row["query"]}" | {reading_note} | llm: {llm_note}'
            f' ({llm["seconds"]}s)'
        )

    out = ROOT / "artifacts" / "evidence" / "probe-llm-spell" / "probe-llm-spell.json"
    log = out.with_suffix(".log")
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:5]))
    print("wrote", out.name, "and", log.name)


if __name__ == "__main__":
    main()
