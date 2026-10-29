"""Strict evaluation runner and scorer for fair-2026-10-27 benchmark.

Rules enforced:
1. 'answer' items:
   - not a refusal
   - >=1 [Ch. N]-style citation that resolves to a gold chunk's chapter AND the
     cited quote is verbatim from a retrieved/gold passage
   - EVERY key_fact regex matches the answer text
   - answer does not merely echo the question
2. 'refuse' items:
   - answer must be exactly 'Not in this book.' and refused=True
3. Multi-turn items score the last turn with history.
4. Locked split runs append to artifacts/datasets/fair-2026-10-27.peek-ledger.jsonl.
5. --dummy-baselines mode evaluates trivial baselines without LLM generation.

Stdlib only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import answer as A
import observe
from prompt import ANSWER_MODEL, REFUSAL
from retrieve import load_index, search
from fair_cite import fold
from trace_inspect import diagnose_eval_item, format_eval_report, summarize_eval_diagnostics

DATASET = ROOT / "artifacts" / "datasets" / "fair-2026-10-27.jsonl"
FAIR_SHA256 = "6255b361c7b7511d5047e82d0fa3e93210a537a7fad92e040ee93f4d944697d8"
PEEK_LEDGER = ROOT / "artifacts" / "datasets" / "fair-2026-10-27.peek-ledger.jsonl"
RUNS_DIR = ROOT / "artifacts" / "runs"

INDEX_PATHS = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}

_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]+")


def dataset_sha256(path=DATASET):
    # Normalize CRLF to LF for consistent hashing across platforms
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_items(path=DATASET, split=None):
    items = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            item = json.loads(line)
            if split and split != "all" and item.get("split") != split:
                continue
            items.append(item)
    return items


def quote_in_passage(quote, text):
    if not quote or not text:
        return False
    # Collapse whitespace and compare case-insensitively
    norm_q = _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", quote.lower())).strip()
    norm_t = _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", text.lower())).strip()
    return norm_q in norm_t


def split_sentences(text):
    clean = _WS_RE.sub(" ", text or "").strip()
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean) if s.strip()]
    return sents if sents else [clean]


def is_question_echo(answer_text, question):
    fold_a = fold(answer_text)
    fold_q = fold(question)
    if not fold_a or not fold_q:
        return False
    if fold_a == fold_q:
        return True
    # If the answer is substantially identical to the question
    if fold_q in fold_a and len(fold_a) <= len(fold_q) + 10:
        return True
    return False


def parse_citations(answer_text):
    """Parses [Ch. N] citations and extracts remaining gloss from answer_text.
    Handles inner double quotes within citations cleanly.

    Returns:
        citations: list of dicts [{'chapter': str, 'quote': str}]
        gloss: str (the answer text with citations stripped)
    """
    if not answer_text:
        return [], ""

    citations = []
    gloss_parts = []

    for line in answer_text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            gloss_parts.append("")
            continue

        if "[Ch." in trimmed:
            ch_matches = list(re.finditer(r'\[Ch\.\s*([^\]]+)\]\s*"', trimmed))
            if ch_matches:
                line_gloss = []
                last_idx = 0
                for idx, m in enumerate(ch_matches):
                    pre = trimmed[last_idx:m.start()].strip()
                    if pre and not pre.startswith(('[Ch.', '—', '–', '--', '-')):
                        line_gloss.append(pre)

                    chap = m.group(1).strip()
                    q_start = m.end()

                    if idx + 1 < len(ch_matches):
                        next_ch_start = ch_matches[idx + 1].start()
                        segment = trimmed[q_start:next_ch_start]
                        last_quote_idx = segment.rfind('"')
                        if last_quote_idx != -1:
                            quote = segment[:last_quote_idx]
                            last_idx = q_start + last_quote_idx + 1
                        else:
                            quote = segment.strip()
                            last_idx = next_ch_start
                    else:
                        segment = trimmed[q_start:]
                        sep_match = re.search(r'"\s*(?:—|–|--)\s*(.*)$', segment)
                        if sep_match:
                            quote = segment[:sep_match.start()]
                            post_gloss = sep_match.group(1).strip()
                            if post_gloss:
                                line_gloss.append(post_gloss)
                            last_idx = len(trimmed)
                        else:
                            last_quote_idx = segment.rfind('"')
                            if last_quote_idx != -1:
                                quote = segment[:last_quote_idx]
                                post_gloss = segment[last_quote_idx + 1:].strip()
                                post_gloss = re.sub(r'^(?:—|–|--|-)\s*', '', post_gloss).strip()
                                if post_gloss:
                                    line_gloss.append(post_gloss)
                                last_idx = len(trimmed)
                            else:
                                quote = segment
                                last_idx = len(trimmed)

                    citations.append({"chapter": chap, "quote": quote})

                if line_gloss:
                    gloss_parts.append(" ".join(line_gloss))
            else:
                gloss_parts.append(line)
        else:
            gloss_parts.append(line)

    gloss = "\n".join(gloss_parts).strip()
    return citations, gloss


def is_chunk_dump(answer_text, chunk_table):
    """Fails if answer verbatim-copies >= 75% of tokens of a chunk >= 55 words,
    or has zero synthesis/selection beyond dumping a long chunk."""
    citations, gloss = parse_citations(answer_text)
    quotes = [c["quote"] for c in citations]
    fold_gloss = fold(gloss)
    gloss_words = fold_gloss.split()

    # 1. Zero synthesis check: gloss is empty/near-empty and quote is a long chunk (>= 55 words)
    if len(gloss_words) < 5:
        for q in quotes:
            q_words = fold(q).split()
            if len(q_words) >= 55:
                return True, "answer dumps long chunk (>= 55 words) with zero synthesis/gloss"

    # 2. Whole chunk copy-paste in gloss or answer body:
    # Check if >= 75% consecutive tokens of any chunk >= 55 words are verbatim copied into gloss
    for c in (chunk_table or {}).values():
        txt = c.get("text", "")
        c_words = fold(txt).split()
        if len(c_words) < 55:
            continue
        k = int(0.75 * len(c_words))
        if len(gloss_words) < k:
            continue
        for i in range(len(c_words) - k + 1):
            slice_text = " ".join(c_words[i:i+k])
            if slice_text in fold_gloss:
                return True, f"answer gloss verbatim-copies >= 75% of chunk {c.get('chunk_id')} ({len(c_words)} words)"

    return False, ""


def get_git_head():
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def grade_fair(item, result, index=None, chunk_table=None):
    reasons = []
    chunk_table = chunk_table or {}
    refused = bool(result.get("refused"))
    answer_text = (result.get("answer") or "").strip()
    citations = result.get("citations") or []
    gold_chunks = item.get("gold_chunks") or []

    if item["expect"] == "refuse":
        if not refused:
            reasons.append("expected refusal but answered")
        if answer_text != REFUSAL:
            reasons.append(f"answer is not exactly '{REFUSAL}'")
    else:
        # Expected answer
        if refused:
            reasons.append("expected answer but refused")
        if answer_text == REFUSAL:
            reasons.append(f"answer is refusal '{REFUSAL}'")

        if is_question_echo(answer_text, item["question"]):
            reasons.append("answer echoes the question")

        is_dump, dump_reason = is_chunk_dump(answer_text, chunk_table)
        if is_dump:
            reasons.append(dump_reason)

        # 1. Key facts check: EVERY regex must match answer_text
        key_facts = item.get("key_facts") or []
        for kf in key_facts:
            if not re.search(kf, answer_text, re.IGNORECASE):
                reasons.append(f"answer misses key_fact /{kf}/")

        # 2. Citation check: >=1 [Ch. N] citation resolving to gold chunk's chapter
        # and verbatim quote from retrieved/gold passage
        gold_chapters = set()
        for gc_id in gold_chunks:
            gc = chunk_table.get(gc_id)
            if gc:
                gold_chapters.add(str(gc.get("chapter", "")).strip())

        # If citations list is empty, attempt to parse [Ch. N] "quote" from text
        cites_to_check = list(citations)
        if not cites_to_check:
            parsed_cites, _ = parse_citations(answer_text)
            cites_to_check = parsed_cites

        valid_citation = False
        if not cites_to_check:
            reasons.append("no citations present")
        else:
            for cite in cites_to_check:
                chap = str(cite.get("chapter", "")).strip()
                quote = (cite.get("quote") or "").strip()
                cid = cite.get("chunk_id")

                # Chapter must match a gold chunk's chapter
                chap_ok = bool(gold_chapters and chap in gold_chapters)

                # Quote must be verbatim from cited chunk or any gold chunk
                quote_ok = False
                if quote:
                    if cid:
                        source = chunk_table.get(cid)
                        quote_ok = bool(source and
                            str(source.get("chapter", "")).strip() == chap and
                            quote_in_passage(quote, source.get("text", "")))
                    else:
                        # A text-only chapter citation has no chunk id; resolve
                        # only within that chapter, never borrow across sources.
                        quote_ok = any(
                            str(chunk_table.get(gc_id, {}).get("chapter", "")).strip() == chap
                            and quote_in_passage(quote, chunk_table.get(gc_id, {}).get("text", ""))
                            for gc_id in gold_chunks
                        )

                if not quote_ok:
                    reasons.append(f"citation quote is not verbatim in its cited source: {cid or chap}")
                if chap_ok and quote_ok:
                    valid_citation = True

            if not valid_citation:
                reasons.append("no citation matches a gold chapter with a verbatim passage quote")

    return {
        "passed": len(reasons) == 0,
        "refused": refused,
        "answer": answer_text,
        "citations": citations,
        "reasons": reasons,
    }


score_item = grade_fair


def evaluate_model(item, index, chunk_table, model):
    started = time.perf_counter()
    with observe.trace(
        source="fair-eval",
        mode="ask",
        book_id=item["book_id"],
        model=model,
        embedder=index.get("embedder") or "",
        write_log=os.environ.get("OBSERVE_EVAL_LOG") == "1",
    ) as tr:
        result = A.ask(
            index,
            item["question"],
            model=model,
            history=item.get("history") or None,
        )
    elapsed = round(time.perf_counter() - started, 3)
    trace_dict = tr.to_dict()
    grade = grade_fair(item, result, index, chunk_table)
    row = {
        "id": item["id"],
        "split": item.get("split"),
        "category": item["category"],
        "book_id": item["book_id"],
        "question": item["question"],
        "expect": item["expect"],
        "passed": grade["passed"],
        "refused": grade["refused"],
        "answer": grade["answer"],
        "citations": grade["citations"],
        "reasons": grade["reasons"],
        "latency_sec": elapsed,
        "trace": trace_dict,
    }
    row["diagnostics"] = diagnose_eval_item(item, row, trace_dict=trace_dict)
    return row


def run_dummy_baselines(items, indexes, chunk_tables):
    print("Evaluating dummy baselines across dataset...")
    baselines = [
        "always_refuse",
        "question_echo",
        "top1_sent1_echo",
        "top1_full_echo",
        "gold_chunk_upper_bound",
    ]
    scores = {b: {"passed": 0, "ans_passed": 0, "ref_passed": 0, "total": len(items)} for b in baselines}
    total_answers = sum(1 for it in items if it["expect"] == "answer")
    total_refusals = sum(1 for it in items if it["expect"] == "refuse")

    for item in items:
        book = item["book_id"]
        idx = indexes[book]
        ct = chunk_tables[book]
        exp = item["expect"]

        # 1. Always Refuse
        res_refuse = {"refused": True, "answer": REFUSAL, "citations": []}
        gr_refuse = grade_fair(item, res_refuse, idx, ct)
        if gr_refuse["passed"]:
            scores["always_refuse"]["passed"] += 1
            if exp == "answer": scores["always_refuse"]["ans_passed"] += 1
            else: scores["always_refuse"]["ref_passed"] += 1

        # 2. Question Echo
        res_echo = {"refused": False, "answer": item["question"], "citations": []}
        gr_echo = grade_fair(item, res_echo, idx, ct)
        if gr_echo["passed"]:
            scores["question_echo"]["passed"] += 1
            if exp == "answer": scores["question_echo"]["ans_passed"] += 1
            else: scores["question_echo"]["ref_passed"] += 1

        # 3. Top-1 Sent1 Echo (pure retrieval, zero gold injected)
        hits = search(idx, item["question"], k=1)
        if hits:
            top = hits[0]
            chap = str(top.get("chapter", "1"))
            sents = split_sentences(top.get("text", ""))
            quote = sents[0] if sents else ""
            ans_text = f'[Ch. {chap}] "{quote}"\n{quote}'
            cites = [{"chunk_id": top["chunk_id"], "chapter": chap, "quote": quote}]
            res_sent1 = {"refused": False, "answer": ans_text, "citations": cites}
        else:
            res_sent1 = {"refused": True, "answer": REFUSAL, "citations": []}
        gr_sent1 = grade_fair(item, res_sent1, idx, ct)
        if gr_sent1["passed"]:
            scores["top1_sent1_echo"]["passed"] += 1
            if exp == "answer": scores["top1_sent1_echo"]["ans_passed"] += 1
            else: scores["top1_sent1_echo"]["ref_passed"] += 1

        # 4. Top-1 Full Echo (pure retrieval, whole chunk dump in body)
        if hits:
            top = hits[0]
            chap = str(top.get("chapter", "1"))
            txt = top.get("text", "")
            sents = split_sentences(txt)
            quote = sents[0] if sents else txt
            ans_text = f'[Ch. {chap}] "{quote}"\n{txt}'
            cites = [{"chunk_id": top["chunk_id"], "chapter": chap, "quote": quote}]
            res_full = {"refused": False, "answer": ans_text, "citations": cites}
        else:
            res_full = {"refused": True, "answer": REFUSAL, "citations": []}
        gr_full = grade_fair(item, res_full, idx, ct)
        if gr_full["passed"]:
            scores["top1_full_echo"]["passed"] += 1
            if exp == "answer": scores["top1_full_echo"]["ans_passed"] += 1
            else: scores["top1_full_echo"]["ref_passed"] += 1

        # 5. Gold Chunk Upper Bound
        if exp == "refuse":
            res_gold = {"refused": True, "answer": REFUSAL, "citations": []}
        else:
            golds = item.get("gold_chunks") or []
            cites = []
            first_chap = "1"
            first_quote = ""
            chosen_sents = []
            for gid in golds:
                gc = ct.get(gid)
                if gc:
                    chap = str(gc.get("chapter", "1"))
                    txt = gc.get("text", "")
                    sents = split_sentences(txt)
                    chosen = sents[0] if sents else txt
                    for s in sents:
                        for kf in item.get("key_facts", []):
                            if re.search(kf, s, re.I):
                                if s not in chosen_sents:
                                    chosen_sents.append(s)
                    if not first_quote:
                        first_chap = chap
                        first_quote = chosen_sents[0] if chosen_sents else chosen
                    cites.append({"chunk_id": gid, "chapter": chap, "quote": chosen})
            remaining = [s for s in chosen_sents if s != first_quote]
            if remaining:
                gloss_text = " ".join(remaining)
            else:
                gloss_text = "Specifically, " + " and ".join(item.get("key_facts", [])) + "."
            full_ans = f'[Ch. {first_chap}] "{first_quote}"\n{gloss_text}'
            res_gold = {"refused": False, "answer": full_ans, "citations": cites}
        gr_gold = grade_fair(item, res_gold, idx, ct)
        if gr_gold["passed"]:
            scores["gold_chunk_upper_bound"]["passed"] += 1
            if exp == "answer": scores["gold_chunk_upper_bound"]["ans_passed"] += 1
            else: scores["gold_chunk_upper_bound"]["ref_passed"] += 1

    print("\n" + "=" * 80)
    print("DUMMY BASELINES BENCHMARK RESULTS")
    print("=" * 80)
    print(f"{'Baseline':25} {'Total Passed':15} {'Ans Pass Rate (<=15%)':22} {'Ref Pass Rate':15}")
    print("-" * 80)
    for b in baselines:
        tot = scores[b]["passed"]
        ans_p = scores[b]["ans_passed"]
        ref_p = scores[b]["ref_passed"]
        ans_rate = (ans_p / total_answers) * 100 if total_answers else 0.0
        ref_rate = (ref_p / total_refusals) * 100 if total_refusals else 0.0
        print(f"{b:25} {tot:2d}/{len(items)} ({tot/len(items)*100:5.1f}%)    "
              f"{ans_p:2d}/{total_answers} ({ans_rate:5.1f}%)         "
              f"{ref_p:2d}/{total_refusals} ({ref_rate:5.1f}%)")
    print("=" * 80)
    return scores


def main():
    parser = argparse.ArgumentParser(description="Strict fair evaluation runner.")
    parser.add_argument("model", nargs="?", default=None, help="Model tag to run.")
    parser.add_argument("--model", dest="flag_model", default=None, help="Model tag flag.")
    parser.add_argument("--split", choices=["dev", "locked", "all"], default="dev", help="Development split by default; locked/all require explicit selection.")
    parser.add_argument("--dummy-baselines", action="store_true", help="Run dumb baselines without LLM generation.")
    args = parser.parse_args()

    model = args.flag_model or args.model or os.environ.get("ANSWER_MODEL") or ANSWER_MODEL
    split = args.split

    # Verify dataset hash
    actual_sha = dataset_sha256()
    if actual_sha != FAIR_SHA256:
        print(f"ERROR: Dataset hash mismatch: {actual_sha} != {FAIR_SHA256}", file=sys.stderr)
        sys.exit(2)

    items = load_items(split=split)
    indexes = {b: load_index(p) for b, p in INDEX_PATHS.items()}
    chunk_tables = {b: {c["chunk_id"]: c for c in idx["chunks"]} for b, idx in indexes.items()}

    if args.dummy_baselines:
        scores = run_dummy_baselines(items, indexes, chunk_tables)
        # Check constraints
        ans_tot = sum(1 for it in items if it["expect"] == "answer")
        for b in ["always_refuse", "question_echo", "top1_sent1_echo", "top1_full_echo"]:
            ans_rate = scores[b]["ans_passed"] / ans_tot
            if ans_rate > 0.15:
                print(f"WARNING: Baseline {b} passed {ans_rate:.1%} of answer items (>15% ceiling!)", file=sys.stderr)
        return

    print(f"Running Fair Eval — model: {model} — split: {split} ({len(items)} items)")
    results = []
    for idx_num, item in enumerate(items, 1):
        book = item["book_id"]
        res = evaluate_model(item, indexes[book], chunk_tables[book], model)
        results.append(res)
        mark = "PASS" if res["passed"] else "FAIL"
        q_display = "[LOCKED QUESTION HIDDEN]" if item.get("split") == "locked" else item['question'][:50]
        print(f"[{idx_num:3d}/{len(items)}] {mark} {res['latency_sec']:5.2f}s  "
              f"{res['id']:16} {q_display}", flush=True)
        for r in res["reasons"]:
            print(f"          reason: {r}", flush=True)

    passed = sum(1 for r in results if r["passed"])
    mean_latency = sum(r["latency_sec"] for r in results) / len(results) if results else 0.0
    items_by_id = {it["id"]: it for it in items}
    diag_summary, diag_enriched = summarize_eval_diagnostics(items_by_id, results)

    print("\n" + format_eval_report(diag_summary, diag_enriched))
    print(f"Mean latency: {mean_latency:.2f}s — Model: {model} — Split: {split}")

    # If locked split is run, append to audit ledger
    if split in ("locked", "all"):
        locked_results = [r for r in results if r["split"] == "locked"]
        if locked_results:
            locked_passed = sum(1 for r in locked_results if r["passed"])
            ledger_entry = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "model": model,
                "git_head": get_git_head(),
                "split": split,
                "locked_passed": locked_passed,
                "locked_total": len(locked_results),
            }
            with PEEK_LEDGER.open("a", encoding="utf-8") as lf:
                lf.write(json.dumps(ledger_entry) + "\n")
            print(f"Recorded locked split run in {PEEK_LEDGER.relative_to(ROOT)}")

    # Write evidence
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    slug = model.replace("/", "_").replace(":", "_")
    out_file = RUNS_DIR / f"fair-eval-{datetime.date.today().isoformat()}-model-{slug}-split-{split}.json"
    payload = {
        "date": datetime.date.today().isoformat(),
        "model": model,
        "split": split,
        "dataset": DATASET.name,
        "dataset_sha256": actual_sha,
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4) if results else 0,
        "mean_latency_sec": round(mean_latency, 3),
        "summary_metrics": diag_summary,
        "results": results,
    }
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Evidence written to: {out_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
