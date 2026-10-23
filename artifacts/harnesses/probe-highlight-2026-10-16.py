"""Golden held-out highlight eval: smallbook_x2f vs smallbook_x2d.

Runs the 24 held-out highlight rows through `answer.explain` with the real
index and the production generate path (in-process, no server). Scores:
not refused, the pinned chunk cited, a quote verbatim from the pinned chunk,
and that quote contains the marked word.

Usage:
  python artifacts/probes/probe-highlight-2026-10-16.py smallbook_x2d smallbook_x2f
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402

GOLDEN = ROOT / "artifacts" / "datasets" / "highlight-golden-2026-10-16.jsonl"
INDEX = ROOT / "data" / "index.json"
OUT = ROOT / "artifacts" / "runs" / "highlight-golden"


def fold(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def load_rows():
    rows = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def score(body, pin_text, selection):
    answer = body.get("answer") or ""
    citations = body.get("citations") or []
    refused = bool(body.get("refused"))
    pin_cited = any(c.get("chunk_id") == body.get("_pin") for c in citations)
    word = re.compile(rf"\b{re.escape(selection.lower())}\b")
    verbatim = False
    word_in_quote = False
    for cite in citations:
        quote = fold(cite.get("quote"))
        if not quote or quote not in fold(pin_text):
            continue
        verbatim = True
        if word.search(quote):
            word_in_quote = True
    return {
        "refused": refused,
        "pin_cited": pin_cited,
        "quote_verbatim_in_pin": verbatim,
        "word_in_quoted_span": word_in_quote,
        "answer": answer[:400],
    }


def run_model(index, rows, model):
    results = []
    for row in rows:
        meta = row["meta"]
        selection = meta["selection"]
        chunk_id = meta["chunk_id"]
        heading = meta["heading"]
        pin = next(c for c in index["chunks"] if c["chunk_id"] == chunk_id)
        started = time.monotonic()
        try:
            body = A.explain(
                index, selection, model=model, chunk_id=chunk_id, heading=heading,
            )
            body["_pin"] = chunk_id
            scored = score(body, pin.get("text", ""), selection)
            scored["error"] = None
        except Exception as exc:  # noqa: BLE001 - record and keep going
            scored = {
                "refused": None, "pin_cited": None,
                "quote_verbatim_in_pin": None, "word_in_quoted_span": None,
                "answer": "", "error": repr(exc),
            }
        scored["seconds"] = round(time.monotonic() - started, 1)
        scored["id"] = f"{chunk_id}:{selection}"
        scored["asked"] = meta["asked"]
        results.append(scored)
        flags = "".join(
            "Y" if scored.get(key) else "n" if scored.get(key) is False else "-"
            for key in ("refused", "pin_cited", "quote_verbatim_in_pin",
                        "word_in_quoted_span")
        )
        print(f"{scored['id']:<28} {flags} {scored['seconds']:>6}s", flush=True)
    return results


def main():
    models = sys.argv[1:] or ["smallbook_x2d", "smallbook_x2f"]
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = load_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for model in models:
        print(f"--- {model} ---", flush=True)
        results = run_model(index, rows, model)
        good = sum(
            1 for r in results
            if not r["refused"] and r["pin_cited"]
            and r["quote_verbatim_in_pin"] and r["word_in_quoted_span"]
        )
        cited = sum(1 for r in results if not r["refused"] and r["pin_cited"])
        verbatim = sum(
            1 for r in results if not r["refused"] and r["quote_verbatim_in_pin"]
        )
        refused = sum(1 for r in results if r["refused"])
        errors = sum(1 for r in results if r["error"])
        summary[model] = {
            "rows": len(results),
            "full_pass": good,
            "not_refused_and_pin_cited": cited,
            "quote_verbatim_in_pin": verbatim,
            "refused": refused,
            "errors": errors,
        }
        slug = model.replace(":", "-")
        payload = {"model": model, "summary": summary[model], "rows": results}
        (OUT / f"probe-highlight-2026-10-16.model-{slug}.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        lines = [
            f"# highlight golden eval — {model} — {len(results)} held-out rows",
            "# flags: refused / pin cited / quote verbatim in pin / word in quote",
        ]
        for r in results:
            flags = "".join(
                "Y" if r.get(key) else "n" if r.get(key) is False else "-"
                for key in ("refused", "pin_cited", "quote_verbatim_in_pin",
                            "word_in_quoted_span")
            )
            lines.append(f"{r['id']:<28} {flags} {r['seconds']:>6}s {r['asked']}")
        (OUT / f"probe-highlight-2026-10-16.model-{slug}.log").write_text(
            "\n".join(lines) + "\n", encoding="utf-8",
        )
    print("--- summary ---")
    for model, counts in summary.items():
        print(model, counts)
    print("wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
