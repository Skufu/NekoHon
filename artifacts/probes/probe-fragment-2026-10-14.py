"""Sealed fragment-pattern suite: the user's sloppy-query surface on a fixed
item list, per model, through the shipped answer seam (`answer.respond`).

SEALED — never train on these items. They are the pre-registered swap-gate
suite for `x2c` (artifacts/x2-trial-2026-10-14.md, gate item 2). The ten
trial queries are the visible targets; this list is built from the same five
classes with different items. A startup check aborts the run if any item
(raw or canonical form) near-matches a training file (difflib >= 0.8 or
word-set Jaccard >= 0.6 vs every quote-refuse-2026-10-13.train*.jsonl,
including a future train-x2c.jsonl). If the check fires after x2c lands,
the suite is burned and must be regenerated.

Classes and expectations:
- fragment / bare-topic / order-flip (two pairs) / trailing-letter: in-book,
  must be ANSWERED (not refused) with >= 1 citation.
- greeting: type "either" — no pass/fail; both models get the same judge
  (recorded, per the 2026-10-14 trial taxonomy).
- control: out-of-book, must REFUSE exactly ("Not in this book.").

Each draw is one full in-process ask with num_predict=300 capped on every
generation call (temperature 0). A loop is counted conservatively: any call
in the draw ending with done_reason == "length". One retry per draw on a
client timeout (Ollama is shared with other jobs right now).

Run:  python artifacts/probe-fragment-2026-10-14.py --model smallbook_x2 --draws 10
Writes artifacts/probe-fragment-2026-10-14.model-<model>.{json,log}.
"""

import argparse
import difflib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import answer as A
from canonical import canonical_query
from prompt import REFUSAL
from retrieve import INDEX, load_index

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
CAP = 300            # num_predict on every generation call
CALL_TIMEOUT = 900   # seconds; the loop probe's value
ANSWER_CHARS = 1400  # answer text kept per draw in the JSON

# ---------------------------------------------------------------------------
# SEALED ITEMS — never train on these. Swap-gate suite (x2-trial-2026-10-14.md).
# Notes give the in-book evidence checked on 2026-10-14 before sealing.
# ---------------------------------------------------------------------------
ITEMS = [
    # (class, item, expect, note)
    ("fragment", "how do", "answered",
     "bare wh fragment inside the class's degenerate surface"),
    ("fragment", "what about", "answered", "bare wh fragment"),
    ("fragment", "explain", "answered",
     "bare imperative fragment; 'explain' is a book word (explain plan)"),
    ("fragment", "why does", "answered", "bare wh fragment"),
    ("greeting", "hi there", "either",
     "opener passthrough in canonical.py; same judge both models"),
    ("greeting", "good morning", "either",
     "records what canonical_query does to a non-opener greeting"),
    ("greeting", "howdy", "either",
     "distinct greeting word, not 'hey'/'warrup'"),
    ("bare-topic", "Time Series", "answered", "ch05 heading 'Time series'"),
    ("bare-topic", "File Formats", "answered", "ch07 'Practical Issues with Common File Formats'"),
    ("bare-topic", "Micro-Batch", "answered", "ch08 'Micro-batch versus true streaming'"),
    ("bare-topic", "Streaming", "answered", "ch02 'Streaming' section"),
    ("bare-topic", "Event Streams", "answered", "ch05 'Event-streaming platforms'"),
    ("order-flip", "batch vs streaming", "answered", "pair A, ch02 'Batch versus streaming'"),
    ("order-flip", "streaming vs batch", "answered", "pair A, flipped order"),
    ("order-flip", "column-oriented vs row-oriented", "answered",
     "pair B, ch06 'evolution from rows to columns', app01 glossary"),
    ("order-flip", "row-oriented vs column-oriented", "answered", "pair B, flipped order"),
    ("trailing-letter", "what does etls stand for", "answered",
     "etl+s; ch01 footnote expands ETL"),
    ("trailing-letter", "benefits of data meshs", "answered",
     "mesh+s; ch03-099 'Data Mesh'"),
    ("trailing-letter", "how do data pipeliness work", "answered",
     "pipeliness; ch07 'Data Pipelines'"),
    ("control", "what is the offside rule", "refused",
     "explicit out-of-book control; nothing near it in the train forms"),
    ("control", "how many strings does a violin have", "refused",
     "explicit out-of-book control"),
]

# The ten visible targets (probe-trial-queries-2026-10-14.log). Not reused;
# kept here for the report-only similarity check.
VISIBLE_TEN = [
    "what is", "hey", "warrup", "Location", "Our Advice", "DE Lifecycle",
    "DDR5 vs ddr4", "ddr4 vs ddr5", "speed of ddr5", "speed of ddr5s",
]

TOKEN_RE = re.compile(r"[a-z0-9]+")
TRAIN_GLOB = "quote-refuse-2026-10-13.train*.jsonl"


def tokens(text):
    return set(TOKEN_RE.findall(text.lower()))


def normalized(text):
    return " ".join(TOKEN_RE.findall(text.lower()))


def similarity(text_a, text_b):
    ratio = difflib.SequenceMatcher(None, normalized(text_a), normalized(text_b)).ratio()
    set_a, set_b = tokens(text_a), tokens(text_b)
    union = set_a | set_b
    jaccard = len(set_a & set_b) / len(union) if union else 0.0
    return ratio, jaccard


def load_train_forms():
    """{question form: sources} from every train file on disk.

    The files carry the asked (canonical) form; for 'What is X?' rows the
    inner X is added too, as a proxy for the raw question it was built from.
    """
    forms = {}
    files = sorted((ROOT / "data" / "finetune").glob(TRAIN_GLOB))
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for message in row["messages"]:
                if message["role"] != "user":
                    continue
                block = message["content"]
                if not block.startswith("Question: "):
                    continue
                asked = block.split("\n", 1)[0][len("Question: "):]
                forms.setdefault(asked, set()).add(path.name)
                inner = re.match(r"^what is (.+)\?$", asked, re.I)
                if inner:
                    forms.setdefault(inner.group(1), set()).add(path.name + ":raw")
    return forms, [path.name for path in files]


def check_sealed(forms):
    """Abort unless every item is clear of the train forms. Returns per-item
    max similarity for the log header."""
    violations = []
    max_sims = {}
    for _cls, item, _expect, _note in ITEMS:
        worst = (0.0, 0.0, None)
        for form in {item, canonical_query(item)}:
            for other, sources in forms.items():
                ratio, jaccard = similarity(form, other)
                if ratio > worst[0] or (ratio == worst[0] and jaccard > worst[1]):
                    worst = (ratio, jaccard, other)
                if normalized(form) == normalized(other) or ratio >= 0.8 or jaccard >= 0.6:
                    violations.append((item, form, other, sources, ratio, jaccard))
        max_sims[item] = worst
    return violations, max_sims


def visible_report():
    """Similarity against the visible ten; returns (max ratio, pair, violations).

    Jaccard uses the raw form on both sides: canonicalizing prefixes 'What is '
    onto everything, and the two-token visible fragment 'what is' then
    saturates Jaccard at 0.67 for any possible item — a metric artifact, not a
    near-match (measured 2026-10-14). difflib checks the canonical form too.
    """
    worst = (0.0, "")
    violations = []
    for _cls, item, _expect, _note in ITEMS:
        for visible in VISIBLE_TEN:
            if normalized(item) == normalized(visible):
                violations.append((item, item, visible, {"VISIBLE"}, 1.0, 1.0))
                continue
            for form in {item, canonical_query(item)}:
                ratio, _ = similarity(form, visible)
                if ratio > worst[0]:
                    worst = (ratio, f"{form!r} vs {visible!r}")
                if ratio >= 0.8:
                    violations.append((item, form, visible, {"VISIBLE"}, ratio, 0.0))
            _ratio, jaccard = similarity(item, visible)
            if jaccard >= 0.6:
                violations.append((item, item, visible, {"VISIBLE"}, 0.0, jaccard))
    return worst[0], worst[1], violations


def make_generate(model, calls):
    """generate_fn for answer.respond: capped Ollama chat, records every call.

    The reading-repair step sends 'User query: \"...\"'; anything else is the
    main answer call. Records survive a raised error (the call still happened).
    """
    def generate(system, user, model_override=None, **_ignored):
        kind = "spell" if user.startswith('User query: "') else "main"
        payload = {
            "model": model_override or model,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": CAP},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request = urllib.request.Request(
            OLLAMA_CHAT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=CALL_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            calls.append({"call": kind, "error": type(exc).__name__,
                          "s": round(time.monotonic() - started, 1)})
            raise
        content = (body.get("message") or {}).get("content")
        calls.append({
            "call": kind,
            "done": body.get("done_reason"),
            "chars": len(content) if isinstance(content, str) else 0,
            "s": round(time.monotonic() - started, 1),
        })
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("empty completion")
        return content.strip()
    return generate


def run_draw(index, item, model):
    calls = []
    started = time.monotonic()
    body = A.respond(index, item, generate_fn=make_generate(model, calls), model=model)
    seconds = time.monotonic() - started
    answer = body.get("answer") or ""
    citations = body.get("citations") or []
    asked_as = re.search(r'^Asked as: "(.*)"$', answer, re.M)
    read_as = re.search(r'^Read as: "(.*)"$', answer, re.M)
    return {
        "refused": bool(body["refused"]),
        "n_cited": len(citations),
        "cited": [c["chunk_id"] for c in citations][:5],
        "loop": any(call.get("done") == "length" for call in calls),
        "main_done": next(
            (call.get("done") for call in calls if call["call"] == "main"), None
        ),
        "calls": calls,
        "asked_as": asked_as.group(1) if asked_as else None,
        "read_as": read_as.group(1) if read_as else None,
        "answer": answer[:ANSWER_CHARS],
        "seconds": round(seconds, 2),
    }


def verdict(expect, record):
    if expect == "answered":
        return (not record["refused"]) and record["n_cited"] >= 1
    if expect == "refused":
        return record["refused"] and record["answer"].strip() == REFUSAL
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="smallbook_x2")
    parser.add_argument("--draws", type=int, default=1)
    args = parser.parse_args()
    if args.draws < 1:
        parser.error("--draws must be >= 1")

    index = load_index(INDEX)
    forms, files = load_train_forms()
    violations, max_sims = check_sealed(forms)
    visible_ratio, visible_pair, visible_violations = visible_report()
    violations.extend(visible_violations)

    lines = []

    def emit(line):
        print(line, flush=True)
        lines.append(line)

    emit("probe-fragment-2026-10-14 — SEALED fragment-pattern suite (never train on these)")
    emit(f"model={args.model} mode=answer cap={CAP} draws={args.draws} "
         f"temperature=0 in-process answer.respond")
    emit(f"sealed-check: {len(violations)} violations vs {len(forms)} forms from "
         f"{', '.join(files) if files else 'NO TRAIN FILES'}")
    emit(f"visible-ten check: {len(visible_violations)} violations; max difflib vs "
         f"the ten raw queries = {visible_ratio:.3f} ({visible_pair})")
    if violations:
        for item, form, other, sources, ratio, jaccard in violations:
            emit(f"SEALED VIOLATION: {item!r} form={form!r} vs {other!r} "
                 f"r={ratio:.3f} j={jaccard:.3f} in {sorted(sources)}")
        emit("ABORT: the suite is burned; regenerate items before running.")
        sys.exit(1)

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    items_out = []
    for number, (cls, item, expect, note) in enumerate(ITEMS, 1):
        ratio, jaccard, closest = max_sims[item]
        emit(f"\n[{number}/{len(ITEMS)}] {cls} {item!r} expect={expect} "
             f"(max train sim r={ratio:.2f} j={jaccard:.2f} vs {closest!r})")
        draws_out = []
        for draw in range(1, args.draws + 1):
            record = None
            for attempt in (1, 2):
                attempt_started = time.monotonic()
                try:
                    record = run_draw(index, item, args.model)
                    record["draw"] = draw
                    record["retried"] = attempt == 2
                    break
                except Exception as exc:  # timeout or connection error
                    text = f"{type(exc).__name__}: {exc}"
                    if attempt == 1:
                        emit(f"  draw {draw}: ERROR {text[:110]} — retrying once")
                    else:
                        record = {
                            "draw": draw, "error": text, "retried": True,
                            "seconds": round(time.monotonic() - attempt_started, 2),
                        }
            if "error" in record:
                draws_out.append(record)
                emit(f"  draw {draw}: ERROR {record['error'][:130]}")
                continue
            sample = " ".join(record["answer"].split())[:120]
            flag = "" if verdict(expect, record) in (True, None) else "  <-- MISS"
            emit(f"  draw {draw}: refused={int(record['refused'])} "
                 f"cited={record['n_cited']} loop={int(record['loop'])} "
                 f"main={record['main_done']} retried={int(record['retried'])} "
                 f"{record['seconds']:5.1f}s | {sample}{flag}")
            draws_out.append(record)

        ok_draws = [d for d in draws_out if "error" not in d]
        refused = sum(d["refused"] for d in ok_draws)
        answered = sum((not d["refused"]) and d["n_cited"] >= 1 for d in ok_draws)
        pass_draws = sum(verdict(expect, d) is True for d in ok_draws)
        loops = sum(d["loop"] for d in ok_draws)
        errors = len(draws_out) - len(ok_draws)
        if errors:
            item_verdict = f"ERROR({errors})"
        elif expect == "either":
            item_verdict = "RECORD"
        elif pass_draws == len(draws_out):
            item_verdict = "PASS"
        else:
            item_verdict = "FAIL"
        if expect == "refused":
            aggs = (f"refuses-exact {pass_draws}/{len(draws_out)}, "
                    f"loops {loops}/{len(draws_out)}")
        elif expect == "either":
            aggs = (f"answered {answered}/{len(draws_out)}, "
                    f"refused {refused}/{len(draws_out)}, loops {loops}/{len(draws_out)}")
        else:
            aggs = (f"refuses {refused}/{len(draws_out)}, "
                    f"answered+cited {answered}/{len(draws_out)}, "
                    f"loops {loops}/{len(draws_out)}")
        emit(f"  => {aggs} -> {item_verdict}")
        items_out.append({
            "class": cls, "item": item, "expect": expect, "note": note,
            "canonical": canonical_query(item),
            "max_train_sim": {"ratio": round(ratio, 3), "jaccard": round(jaccard, 3),
                              "closest": closest},
            "agg": {
                "draws": len(draws_out), "refuses": refused,
                "answered_cited": answered, "pass_draws": pass_draws,
                "loops": loops, "errors": errors, "verdict": item_verdict,
            },
            "draws": draws_out,
        })

    by_class = {}
    for row in items_out:
        bucket = by_class.setdefault(row["class"], {
            "items": 0, "draws": 0, "pass_draws": 0, "expected_draws": 0,
            "answered": 0, "refuses_exact": 0, "loops": 0, "errors": 0,
            "verdicts": [],
        })
        bucket["items"] += 1
        agg = row["agg"]
        bucket["draws"] += agg["draws"]
        bucket["loops"] += agg["loops"]
        bucket["errors"] += agg["errors"]
        bucket["verdicts"].append(agg["verdict"])
        if row["expect"] == "either":
            bucket["answered"] += agg["answered_cited"]
        else:
            bucket["expected_draws"] += agg["draws"]
            bucket["pass_draws"] += agg["pass_draws"]
        if row["expect"] == "refused":
            bucket["refuses_exact"] += agg["pass_draws"]

    emit("\n== summary ==")
    emit(f"{'class':15} {'items':>5} {'draws':>5} {'pass/draws':>11} "
         f"{'loops':>5} {'errors':>6}  verdicts")
    for cls, bucket in by_class.items():
        if cls == "greeting":
            pass_col = f"{bucket['answered']}/{bucket['draws']} answ"
        else:
            pass_col = f"{bucket['pass_draws']}/{bucket['expected_draws']}"
        verdicts = ",".join(bucket["verdicts"])
        emit(f"{cls:15} {bucket['items']:>5} {bucket['draws']:>5} {pass_col:>11} "
             f"{bucket['loops']:>5} {bucket['errors']:>6}  {verdicts}")

    label = args.model.replace(":", "-").replace("/", "-")
    stem = f"probe-fragment-2026-10-14.model-{label}"
    payload = {
        "probe": "probe-fragment-2026-10-14",
        "sealed": True,
        "warning": "SEALED — never train on these items; swap-gate suite "
                   "(x2-trial-2026-10-14.md)",
        "model": args.model,
        "mode": "answer",
        "cap": CAP,
        "draws": args.draws,
        "generated": started_at,
        "train_files": files,
        "visible_ten_report": {"violations": len(visible_violations),
                               "max_ratio": round(visible_ratio, 3),
                               "pair": visible_pair},
        "items": items_out,
        "by_class": by_class,
    }
    (HERE / f"{stem}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (HERE / f"{stem}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    emit(f"\nwrote artifacts/{stem}.{{json,log}}")


if __name__ == "__main__":
    main()
