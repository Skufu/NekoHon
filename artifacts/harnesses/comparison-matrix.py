"""Before/after comparison harness for the comparison-answer work.

Run from the repo root:

    python artifacts/harnesses/comparison-matrix.py --label before
    python artifacts/harnesses/comparison-matrix.py --label after

It calls the live engine in-process (`answer.respond` with the default
Ollama generator), so no server restart and no port is involved. The same
case file and the same flag computation are used for both labels, and the
harness imports only stable engine names so it runs unchanged on old and new
code.

Outputs:
    artifacts/evidence/comparison/compare-<label>-2026-10-29.json
    artifacts/evidence/comparison/compare-<label>-2026-10-29.log
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer  # noqa: E402
import retrieve  # noqa: E402

CASES_PATH = ROOT / "artifacts" / "datasets" / "comparison-cases-2026-10-29.json"
CATALOG_PATH = ROOT / "data" / "books.json"

_INDEX_CACHE = {}

CONTRAST_RE = re.compile(
    r"\b(unlike|difference|differ(?:s|ed|ent)?|whereas|in contrast|compared|"
    r"versus|vs\.?|rather than|limited to|stands? in contrast|separate|"
    r"while|mirror(?:s|ing|ed)?|analog(?:y|ous)|similar|both)\b",
    re.I,
)
TEMPLATE = "connects to this topic"
NOT_MENTIONED_RE = re.compile(r"\b(not mention|does not mention|do not mention|absent|no mention)\b", re.I)


def load_catalog():
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("books", [])


def load_cases():
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("cases", [])


def book_index(key):
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    catalog = load_catalog()
    match = None
    for book in catalog:
        bid = book.get("book_id") or ""
        title = (book.get("title") or "").lower()
        if bid == key or bid.startswith(key) or key.lower() in title:
            match = book
            break
    if match is None:
        raise SystemExit(f"book not found in data/books.json: {key}")
    path = Path(match.get("index_path") or "")
    if not path.is_absolute():
        path = ROOT / path
    index = retrieve.load_index(path)
    index.setdefault("book_id", match.get("book_id"))
    _INDEX_CACHE[key] = index
    return index


def chunk_by_id(index, chunk_id):
    for chunk in index.get("chunks") or []:
        if chunk.get("chunk_id") == chunk_id:
            return chunk
    return None


def heading_core(heading):
    text = (heading or "").strip()
    text = re.sub(r"^Chapter\s+\d+\.?\s*", "", text, flags=re.I)
    return text.strip().rstrip(":").strip()


def side_tokens(side):
    return [
        w.lower()
        for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", side or "")
        if len(w) >= 3
    ]


def side_token_groups(sides):
    """Token groups with shared filler dropped, so 'data lake' vs
    'data warehouse' requires lake and warehouse, not the shared word data."""
    groups = [side_tokens(side) for side in sides]
    if not groups:
        return groups
    common = set(groups[0])
    for group in groups[1:]:
        common &= set(group)
    filtered = [[token for token in group if token not in common] for group in groups]
    return filtered if all(filtered) else groups


def mentions(text, token):
    # Prefix match is deliberate: agents/agent, LLM/LLMs, model/models.
    return bool(re.search(rf"\b{re.escape(token)}", (text or "").lower()))


def split_answer(answer_text):
    """Separate the cited lines from the gloss the reader actually reads."""
    quote_lines = []
    gloss_lines = []
    for line in (answer_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[Ch."):
            quote_lines.append(stripped)
        elif stripped.startswith(("Asked as:", "Read as:")):
            continue
        else:
            gloss_lines.append(stripped)
    return "\n".join(quote_lines), " ".join(gloss_lines)


def heading_lines_for(chunk):
    """The chunk's own leading heading lines, including a subtitle line."""
    lines = [line.strip() for line in ((chunk or {}).get("text") or "").splitlines() if line.strip()]
    heads = []
    for line in lines[:2]:
        core = heading_core(line)
        if core and len(core) >= 8:
            heads.append(core)
        elif len(line) >= 8 and not re.search(r"[.!?]$", line):
            heads.append(line)
    return heads


def flags_for(case, index, body):
    answer_text = body.get("answer") or ""
    quote_text, gloss_text = split_answer(answer_text)
    gloss_low = gloss_text.lower()
    sides = case.get("sides") or []
    token_groups = side_token_groups(sides)
    both_sides = None
    if token_groups:
        both_sides = all(any(mentions(gloss_low, token) for token in group) for group in token_groups)

    citations = body.get("citations") or []
    quote_heads = []
    heading_fragment = False
    quote_is_sentence = True
    for cite in citations:
        quote = (cite.get("quote") or "").strip()
        chunk = chunk_by_id(index, cite.get("chunk_id"))
        for head in heading_lines_for(chunk):
            if quote.lower().startswith(head.lower()):
                heading_fragment = True
                quote_heads.append(head)
        if re.match(r"^Chapter\s+\d+\b", quote, re.I):
            heading_fragment = True
            quote_heads.append(quote[:80])
        if len(quote) < 40 or not re.search(r"[.!?][\"'”’]?$", quote):
            quote_is_sentence = False

    return {
        "both_sides": both_sides,
        "contrast_marker": bool(CONTRAST_RE.search(gloss_text)),
        "template": TEMPLATE in gloss_low,
        "heading_fragment": heading_fragment,
        "quote_heads": quote_heads,
        "quote_is_sentence": quote_is_sentence,
        "not_mentioned": bool(NOT_MENTIONED_RE.search(gloss_text)),
        "refused": bool(body.get("refused")),
        "answer_chars": len(answer_text),
        "gloss": gloss_text[:400],
        "citations": [
            {
                "chunk_id": cite.get("chunk_id"),
                "chapter": cite.get("chapter"),
                "quote": (cite.get("quote") or "")[:180],
            }
            for cite in citations
        ],
    }


def run_case(case, model=None):
    index = book_index(case["book"])
    history = list(case.get("history") or [])
    pin = case.get("pin_chunk")
    heading = case.get("heading") or ""
    seed_result = None

    seed = case.get("seed")
    if seed:
        t0 = time.perf_counter()
        seeded = answer.respond(
            index,
            seed["question"],
            pin_chunk=seed.get("pin_chunk"),
            heading=seed.get("heading") or "",
            model=model or answer.ANSWER_MODEL,
        )
        seed_ms = (time.perf_counter() - t0) * 1000.0
        seed_result = {
            "question": seed["question"],
            "answer": seeded.get("answer"),
            "citations": seeded.get("citations") or [],
            "ms": round(seed_ms, 1),
        }
        history = [{"question": seed["question"], "answer": seeded.get("answer") or ""}]
        first = (seeded.get("citations") or [{}])[0]
        pin = first.get("chunk_id") or pin
        seeded_chunk = chunk_by_id(index, pin)
        heading = (seeded_chunk or {}).get("heading") or heading

    t0 = time.perf_counter()
    body = answer.respond(
        index,
        case["question"],
        history=history or None,
        pin_chunk=pin,
        heading=heading,
        model=model or answer.ANSWER_MODEL,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "id": case["id"],
        "book": case["book"],
        "question": case["question"],
        "expect": case.get("expect"),
        "history_turns": len(history),
        "pin_chunk": pin,
        "heading": heading,
        "seed": seed_result,
        "ms": round(elapsed_ms, 1),
        "answer": body.get("answer") or "",
        "followups": body.get("followups") or [],
        "flags": flags_for(case, index, body),
    }


def verdict(case, row, error):
    if error:
        return "ERROR"
    flags = row["flags"]
    expect = case.get("expect")
    if expect == "comparison":
        if (flags["both_sides"] and flags["contrast_marker"] and flags["quote_is_sentence"]
                and not flags["template"] and not flags["heading_fragment"]):
            return "PASS"
        return "FAIL"
    if expect == "relation":
        if (flags["both_sides"] and flags["quote_is_sentence"]
                and not flags["template"] and not flags["heading_fragment"]):
            return "PASS"
        return "FAIL"
    if expect == "half_covered":
        if (flags["not_mentioned"] or flags["refused"]) and not flags["template"] and not flags["heading_fragment"]:
            return "PASS"
        return "FAIL"
    if expect == "no_comparison":
        if (flags["not_mentioned"] or flags["refused"]) and not flags["template"]:
            return "PASS"
        return "FAIL"
    if expect == "generic_followup":
        if not flags["template"] and not flags["heading_fragment"]:
            return "PASS"
        return "FAIL"
    if expect == "normal":
        if not flags["template"] and not flags["heading_fragment"]:
            return "PASS"
        return "FAIL"
    return "PASS" if not flags["template"] and not flags["heading_fragment"] else "FAIL"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="before or after")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--cases", default="", help="case JSON path (default: comparison-cases-2026-10-29.json)")
    parser.add_argument("--model", default="", help="override ANSWER_MODEL for this run")
    args = parser.parse_args()

    global CASES_PATH
    if args.cases:
        CASES_PATH = Path(args.cases)
        if not CASES_PATH.is_absolute():
            CASES_PATH = ROOT / CASES_PATH
    cases = load_cases()
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if case["id"] in wanted]
    if not cases:
        raise SystemExit("no cases selected")

    model = args.model or answer.ANSWER_MODEL
    results = []
    print(f"label={args.label} model={model} cases={len(cases)}")
    for index, case in enumerate(cases, start=1):
        t0 = time.perf_counter()
        error = None
        try:
            row = run_case(case, model=model)
        except Exception as exc:  # keep the matrix going
            row = {
                "id": case["id"],
                "book": case["book"],
                "question": case["question"],
                "expect": case.get("expect"),
                "answer": "",
                "flags": {},
                "ms": round((time.perf_counter() - t0) * 1000.0, 1),
            }
            error = f"{type(exc).__name__}: {exc}"
        row["error"] = error
        row["verdict"] = verdict(case, row, error)
        results.append(row)
        flags = row.get("flags") or {}
        print(
            f"[{index:02d}/{len(cases)}] {row['verdict']:<5} {row['id']:<30} "
            f"both={flags.get('both_sides')} contrast={flags.get('contrast_marker')} "
            f"template={flags.get('template')} headfrag={flags.get('heading_fragment')} "
            f"sentence={flags.get('quote_is_sentence')} ms={row['ms']}"
        )
        if error:
            print(f"    error: {error}")

    out_json = ROOT / "artifacts" / "evidence" / "comparison" / f"compare-{args.label}-2026-10-29.json"
    out_log = ROOT / "artifacts" / "evidence" / "comparison" / f"compare-{args.label}-2026-10-29.log"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [f"label={args.label} model={model} cases={len(results)}"]
    for row in results:
        flags = row.get("flags") or {}
        lines.append(
            f"{row['verdict']:<5} {row['id']:<30} both={flags.get('both_sides')} "
            f"contrast={flags.get('contrast_marker')} template={flags.get('template')} "
            f"headfrag={flags.get('heading_fragment')} sentence={flags.get('quote_is_sentence')} "
            f"refused={flags.get('refused')} not_mentioned={flags.get('not_mentioned')} ms={row['ms']}"
        )
        lines.append(f"  Q: {row['question']}")
        lines.append(f"  G: {flags.get('gloss','')}")
        lines.append(f"  A: {row.get('answer','').replace(chr(10), ' | ')}")
        lines.append(f"  C: {json.dumps((flags.get('citations') or []), ensure_ascii=False)}")
        if row.get("seed"):
            lines.append(f"  SEED: {row['seed'].get('question')} -> {json.dumps(row['seed'].get('citations') or [], ensure_ascii=False)}")
        if row.get("error"):
            lines.append(f"  ERROR: {row['error']}")
    out_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    passed = sum(1 for row in results if row["verdict"] == "PASS")
    print(f"wrote {out_json}")
    print(f"wrote {out_log}")
    print(f"pass {passed}/{len(results)}")


if __name__ == "__main__":
    main()
