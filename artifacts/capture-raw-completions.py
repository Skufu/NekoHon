"""One-off: capture raw qwen completions for the four known-failing asks.

Post-v1 plan step 1 (artifacts/post-v1-plan.md). No pipeline code changes.
Run: python artifacts/capture-raw-completions.py
"""

import difflib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from answer import (  # noqa: E402
    PASSAGE_LIMIT,
    _matching_passage,
    _strip_quotes,
    ollama_generate,
    parse_completion,
    user_message,
)
from prompt import ANSWER_MODEL, REFUSAL, SYSTEM  # noqa: E402
from retrieve import load_index, search  # noqa: E402

OUT_JSON = Path(__file__).resolve().parent / "raw-completions-2026-10-12.json"
OUT_MD = Path(__file__).resolve().parent / "raw-completions-2026-10-12.md"

CASES = [
    {
        "id": "golden-05",
        "kind": "golden refusal",
        "question": "Where does storage sit in the data engineering lifecycle?",
    },
    {
        "id": "golden-10",
        "kind": "golden refusal",
        "question": "What do transformations do in the data engineering lifecycle?",
    },
    {
        "id": "typo-cru",
        "kind": "typo",
        "question": "What does CRU stand for?",
    },
    {
        "id": "typo-et",
        "kind": "typo",
        "question": "What happens to data after it is extracted in ET?",
    },
]

MIN_SPAN = 40


def _fold(text):
    return re.sub(r"\s+", " ", text).lower()


def fragment_hits(completion, passages):
    """Whole passage sentences or 80-char windows that appear verbatim.

    The plan's strict rule: a whole sentence in the raw text means the
    parser, not the model, is at fault. Windows bridge odd punctuation.
    """
    folded = _fold(completion)
    found = []
    for hit in passages:
        text = re.sub(r"\s+", " ", hit["text"]).strip()
        candidates = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text)]
        candidates += [text[i:i + 80] for i in range(0, len(text), 40)]
        best = ""
        for candidate in candidates:
            if len(candidate) >= MIN_SPAN and candidate.lower() in folded:
                if len(candidate) > len(best):
                    best = candidate
        if best:
            found.append({
                "chunk_id": hit["chunk_id"],
                "chapter": str(hit["chapter"]),
                "span": best,
                "span_chars": len(best),
            })
    found.sort(key=lambda item: item["span_chars"], reverse=True)
    return found


def longest_run(completion, passages):
    """Longest verbatim run between each passage and the raw completion.

    difflib, because a 40-char window stride can step over a real copy that
    straddles an edit (seen 2026-10-12: the model dropped `(Figure 6-1)`).
    """
    folded = _fold(completion)
    best = {"chunk_id": None, "chapter": None, "chars": 0, "text": ""}
    for hit in passages:
        text = _fold(hit["text"])
        matcher = difflib.SequenceMatcher(None, text, folded, autojunk=False)
        match = matcher.find_longest_match(0, len(text), 0, len(folded))
        if match.size > best["chars"]:
            best = {
                "chunk_id": hit["chunk_id"],
                "chapter": str(hit["chapter"]),
                "chars": match.size,
                "text": text[match.a:match.a + match.size],
            }
    return best


def line_checks(completion, passages):
    """What parse_completion does per [Ch.] line: quote extraction + match."""
    checks = []
    for line in completion.splitlines():
        stripped = line.strip()
        match = re.match(r"\[Ch\.\s*([^\]]+)\]\s*(.*)", stripped)
        if not match:
            continue
        chapter = match.group(1).strip().rstrip(".")
        quoted = re.search(r"[\"\u201c](.+?)[\"\u201d]", match.group(2))
        quote = _strip_quotes(quoted.group(1) if quoted else match.group(2))
        hit = _matching_passage(chapter, quote, passages)
        checks.append({
            "chapter_tag": chapter,
            "quote": quote,
            "matched_chunk_id": hit["chunk_id"] if hit else None,
        })
    return checks


def classify(completion, refused, fragments, longest):
    if not refused:
        return "answered; not failing in this capture"
    if fragments:
        return "PARSER (raw text contains a whole passage sentence; parse still refused)"
    if longest["chars"] >= MIN_SPAN:
        return (
            "MODEL (near-verbatim copy: longest run "
            f"{longest['chars']} chars from {longest['chunk_id']}; the model "
            "edited the copy, so the exact-substring check refused)"
        )
    text = completion.strip()
    if text == REFUSAL or text.startswith(REFUSAL):
        return "MODEL (bare refusal in raw text)"
    return "MODEL (raw text is prose/paraphrase; no passage run >= 40 chars)"


def run_case(index, case):
    started = time.perf_counter()
    passages = search(index, case["question"], k=PASSAGE_LIMIT)
    search_s = time.perf_counter() - started
    user = user_message(case["question"], passages)
    started = time.perf_counter()
    completion = ollama_generate(SYSTEM, user, ANSWER_MODEL)
    generate_s = time.perf_counter() - started
    result = parse_completion(completion, passages, index.get("figures") or [])
    fragments = fragment_hits(completion, passages)
    longest = longest_run(completion, passages)
    verdict = classify(completion, result["refused"], fragments, longest)
    return {
        "id": case["id"],
        "kind": case["kind"],
        "question": case["question"],
        "model": ANSWER_MODEL,
        "search_seconds": round(search_s, 2),
        "generate_seconds": round(generate_s, 2),
        "retrieved": [
            {
                "rank": rank,
                "score": round(hit["score"], 4),
                "chunk_id": hit["chunk_id"],
                "chapter": str(hit["chapter"]),
                "heading": hit["heading"],
                "text": hit["text"],
            }
            for rank, hit in enumerate(passages, start=1)
        ],
        "system": SYSTEM,
        "user": user,
        "raw_completion": completion,
        "parse_result": result,
        "fragment_hits": fragments,
        "longest_run": longest,
        "line_checks": line_checks(completion, passages),
        "verdict": verdict,
    }


def write_md(records, index):
    lines = [
        "# Raw completions — four failing asks (post-v1 step 1)",
        "",
        "Captured 2026-10-12, before any code change. Model tag "
        f"`{ANSWER_MODEL}` via Ollama on 127.0.0.1:11434; index "
        f"`data/index.json` (embedder `{index.get('embedder')}`, "
        f"{index.get('embedding_dims')} dims, {len(index.get('chunks', []))} chunks).",
        "Prompts came from the real modules (`answer.user_message`, `prompt.SYSTEM`).",
        "Fragment rule: a whole passage sentence (or 80-char window) of at least",
        "40 chars inside the raw completion. Longest run: difflib over folded text.",
        "Full passages and prompts: `artifacts/raw-completions-2026-10-12.json`.",
        "",
        "| id | question | verdict |",
        "| --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            f"| {record['id']} | {record['question']} | {record['verdict']} |"
        )
    for record in records:
        lines += [
            "",
            f"## {record['id']} — {record['question']}",
            "",
            f"- kind: {record['kind']}",
            "- retrieval (top 5):",
        ]
        for hit in record["retrieved"]:
            lines.append(
                f"  - rank {hit['rank']} score {hit['score']} "
                f"{hit['chunk_id']} ch{hit['chapter']} \"{hit['heading']}\""
            )
        lines += [
            f"- seconds: search {record['search_seconds']}, "
            f"generate {record['generate_seconds']}",
            "",
            "Raw completion:",
            "",
            "```text",
            record["raw_completion"],
            "```",
            "",
            f"- parse_completion: refused={record['parse_result']['refused']}",
            "- [Ch.] line checks (quote vs retrieved passages):",
        ]
        if record["line_checks"]:
            for check in record["line_checks"]:
                matched = check["matched_chunk_id"] or "NO MATCH"
                quote = check["quote"]
                if len(quote) > 100:
                    quote = quote[:100] + "..."
                lines.append(
                    f"  - tag ch{check['chapter_tag']} -> {matched}: \"{quote}\""
                )
        else:
            lines.append("  - none (no line starts with [Ch.])")
        lines.append("- whole-sentence fragments found in raw completion:")
        if record["fragment_hits"]:
            for span in record["fragment_hits"][:3]:
                shown = span["span"]
                if len(shown) > 140:
                    shown = shown[:140] + "..."
                lines.append(
                    f"  - {span['chunk_id']} ({span['span_chars']} chars): "
                    f"\"{shown}\""
                )
        else:
            lines.append("  - none")
        longest = record["longest_run"]
        shown = longest["text"]
        if len(shown) > 160:
            shown = shown[:160] + "..."
        lines.append(
            f"- longest verbatim run: {longest['chars']} chars "
            f"({longest['chunk_id']}): \"{shown}\""
        )
        lines.append(f"- verdict: {record['verdict']}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    index = load_index(ROOT / "data" / "index.json")
    records = [run_case(index, case) for case in CASES]
    OUT_JSON.write_text(json.dumps(records, indent=2), encoding="utf-8")
    write_md(records, index)
    for record in records:
        print(f"{record['id']}: {record['verdict']}")
        print(f"  search {record['search_seconds']}s "
              f"generate {record['generate_seconds']}s")
        print(f"  longest run {record['longest_run']['chars']} chars")
    print(f"wrote {OUT_JSON.name} and {OUT_MD.name}")


if __name__ == "__main__":
    main()
