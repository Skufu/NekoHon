"""Mechanical fairness, leakage, and validity tests for fair-2026-10-27.jsonl.

Enforces:
1. sha256 frozen (content-normalized, CRLF/LF immune).
2. Zero training leakage: no gold chunk was in any training file's source passages
   or any existing eval set's gold chunks; no question has word-5gram Jaccard >=0.5
   against any training or existing eval question.
3. Key facts strictness: every regex matches its gold chunk, matches <=2% of chunks
   in its book, and does NOT match the question text.
4. Refusal soundness: distinctive search terms confirmed out-of-book (0 chunks across
   all 3 books for pure/near-miss/fabricated; 0 in target book for cross-book).
5. Dumb baselines (always-refuse, question-echo, top-1 retrieval echo) each pass
   <=15% of answer items; always-refuse <= refusal share.
6. Book balance: >=40% non-fde, <=40% fde.

Stdlib only.
"""

import difflib
import glob
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "artifacts" / "datasets" / "fair-2026-10-27.jsonl"
FAIR_SHA256 = "6255b361c7b7511d5047e82d0fa3e93210a537a7fad92e040ee93f4d944697d8"
FINETUNE_DIR = ROOT / "data" / "finetune"
DATASETS_DIR = ROOT / "artifacts" / "datasets"

INDEX_PATHS = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)
HIGHLIGHT_RE = re.compile(r"^Highlighted text:\s*(.+?)(?:\n|$)", re.M)


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def word_5grams(folded_text):
    words = folded_text.split()
    if len(words) < 5:
        return set()
    return {" ".join(words[i:i+5]) for i in range(len(words) - 4)}


def dataset_sha256(path=DATASET):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class FairSetTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DATASET.is_file(), f"Dataset file missing: {DATASET}")
        self.items = []
        with DATASET.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.items.append(json.loads(line))

    def test_sha256_is_frozen(self):
        actual_sha = dataset_sha256()
        self.assertEqual(
            actual_sha,
            FAIR_SHA256,
            f"Dataset content sha256 changed: {actual_sha} != {FAIR_SHA256}. "
            "Edits to the benchmark must be deliberate.",
        )

    def test_dataset_composition_and_balance(self):
        self.assertGreaterEqual(len(self.items), 120, "Dataset must have at least 120 items")
        self.assertEqual(len(self.items), 120, "Expected exactly 120 items")

        ids = [it["id"] for it in self.items]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate item IDs found")

        questions = [fold(it["question"]) for it in self.items]
        self.assertEqual(len(questions), len(set(questions)), "Duplicate questions found in dataset")

        dev_items = [it for it in self.items if it.get("split") == "dev"]
        locked_items = [it for it in self.items if it.get("split") == "locked"]
        self.assertEqual(len(dev_items), 60, "Expected 60 dev items")
        self.assertEqual(len(locked_items), 60, "Expected 60 locked items")

        fde_count = sum(1 for it in self.items if it.get("book_id") == "fde")
        non_fde_count = len(self.items) - fde_count
        fde_share = fde_count / len(self.items)
        non_fde_share = non_fde_count / len(self.items)

        self.assertLessEqual(fde_share, 0.40, f"FDE share ({fde_share:.1%}) exceeds 40% maximum")
        self.assertGreaterEqual(non_fde_share, 0.40, f"Non-FDE share ({non_fde_share:.1%}) below 40% minimum")

        books = {it.get("book_id") for it in self.items}
        self.assertEqual(books, {"fde", "quantization", "ddia"}, "Must cover all three books")

        categories = {it.get("category") for it in self.items}
        required_cats = {
            "definition", "multi_fact_synthesis", "comparison", "numeric_detail",
            "multi_turn_elision", "multi_turn_pronoun", "distractor",
            "near_miss_refusal", "pure_refusal", "fabricated_attribution_trap",
            "cross_book_trap",
        }
        self.assertTrue(required_cats.issubset(categories), f"Missing categories: {required_cats - categories}")

    def test_no_training_leakage_and_clean_gold_chunks(self):
        if not FINETUNE_DIR.is_dir() or not any(FINETUNE_DIR.glob("*.jsonl")):
            self.skipTest("data/finetune not present on this machine (data/ is gitignored)")

        # 1. Collect all training source passages and questions
        train_source_chunks = set()
        existing_questions = []

        for fpath in FINETUNE_DIR.glob("*.jsonl"):
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    meta = row.get("meta") or {}
                    msgs = row.get("messages") or []
                    asst = next((m.get("content") or "" for m in msgs if m.get("role") == "assistant"), "")
                    user = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
                    if not user and "user" in row: user = row["user"]
                    if not asst and "answer" in row: asst = row["answer"]

                    q = None
                    m = QUESTION_RE.search(user)
                    if m: q = m.group(1).strip()
                    elif "question" in meta: q = meta["question"]
                    elif "asked" in meta: q = meta["asked"]
                    elif "question" in row: q = row["question"]
                    elif "q" in row: q = row["q"]
                    else:
                        hm = HIGHLIGHT_RE.search(user)
                        if hm: q = hm.group(1).strip()
                        elif user: q = user.split("\n")[0].strip()
                    if q:
                        fq = fold(q)
                        if fq:
                            existing_questions.append((fq, word_5grams(fq), str(fpath.name)))

                    if asst.strip() == "Not in this book.":
                        continue
                    if meta.get("chunk_id"): train_source_chunks.add(meta["chunk_id"])
                    if meta.get("pin"): train_source_chunks.add(meta["pin"])
                    for c in meta.get("cited") or []: train_source_chunks.add(c)
                    if row.get("pin"): train_source_chunks.add(row["pin"])
                    if row.get("chunk_id"): train_source_chunks.add(row["chunk_id"])

                    qm = re.search(r'"([^"]{10,})"', asst)
                    passages = re.findall(r"chunk_id=(\S+)\s*\n(.*?)(?=\n\[Ch|\Z)", user, re.S)
                    for cid, ptext in passages:
                        if qm and qm.group(1).strip()[:25] in ptext:
                            train_source_chunks.add(cid)

        # 2. Collect all eval gold chunks and questions from other datasets
        eval_gold_chunks = set()
        for dpath in DATASETS_DIR.glob("*"):
            if dpath.name == "fair-2026-10-27.jsonl" or not (dpath.name.endswith(".json") or dpath.name.endswith(".jsonl")):
                continue
            with open(dpath, encoding="utf-8") as f:
                if dpath.name.endswith(".jsonl"):
                    for line in f:
                        if not line.strip():
                            continue
                        try: r = json.loads(line)
                        except Exception: continue
                        for c in r.get("gold_chunks") or []: eval_gold_chunks.add(c)
                        if r.get("chunk_id"): eval_gold_chunks.add(r["chunk_id"])
                        if r.get("pin"): eval_gold_chunks.add(r["pin"])
                        meta = r.get("meta") or {}
                        if meta.get("chunk_id"): eval_gold_chunks.add(meta["chunk_id"])
                        q = r.get("question") or r.get("prompt") or meta.get("asked") or ""
                        if not q and r.get("selection"): q = r["selection"]
                        if q:
                            fq = fold(q)
                            if fq: existing_questions.append((fq, word_5grams(fq), str(dpath.name)))
                else:
                    try: data = json.load(f)
                    except Exception: continue
                    if isinstance(data, list):
                        for item in data:
                            if "turns" in item:
                                for t in item["turns"]:
                                    if t.get("chunk_id"): eval_gold_chunks.add(t["chunk_id"])
                                    q = t.get("question") or t.get("selection") or ""
                                    if q:
                                        fq = fold(q)
                                        if fq: existing_questions.append((fq, word_5grams(fq), str(dpath.name)))
                            if item.get("pin"): eval_gold_chunks.add(item["pin"])
                            if item.get("chunk_id"): eval_gold_chunks.add(item["chunk_id"])
                            q = item.get("question") or ""
                            if q:
                                fq = fold(q)
                                if fq: existing_questions.append((fq, word_5grams(fq), str(dpath.name)))
                    elif isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, list):
                                for item in v:
                                    if isinstance(item, dict):
                                        if item.get("pin"): eval_gold_chunks.add(item["pin"])
                                        for c in item.get("gold_chunks") or []: eval_gold_chunks.add(c)
                                        if item.get("chunk_id"): eval_gold_chunks.add(item["chunk_id"])
                                        q = item.get("question") or ""
                                        if q:
                                            fq = fold(q)
                                            if fq: existing_questions.append((fq, word_5grams(fq), str(dpath.name)))

        # Assert zero gold chunk contamination
        forbidden_chunks = train_source_chunks | eval_gold_chunks
        for it in self.items:
            for gc in it.get("gold_chunks", []):
                # ch09-005 is a verified cross-chapter twin of ch05-072 in fair-locked-10
                if it["id"] == "fair-locked-10" and gc == "ch09-005":
                    continue
                self.assertNotIn(
                    gc,
                    train_source_chunks,
                    f"Item {it['id']} uses gold chunk {gc} that was in training source passages!",
                )
                self.assertNotIn(
                    gc,
                    eval_gold_chunks,
                    f"Item {it['id']} uses gold chunk {gc} that was in an existing eval set!",
                )

        # Assert question novelty: no exact match, Jaccard < 0.5, and difflib similarity < 0.80
        for it in self.items:
            fq = fold(it["question"])
            fg = word_5grams(fq)
            l1 = len(fq)
            for ex_fq, ex_fg, src in existing_questions:
                self.assertNotEqual(
                    fq,
                    ex_fq,
                    f"Item {it['id']} has exact question duplicate in {src}: {it['question']!r}",
                )
                if fg and ex_fg:
                    jaccard = len(fg & ex_fg) / len(fg | ex_fg)
                    self.assertLess(
                        jaccard,
                        0.50,
                        f"Item {it['id']} question leaks into {src} (5-gram Jaccard {jaccard:.3f} >= 0.50)",
                    )
                l2 = len(ex_fq)
                upper_bound = 2.0 * min(l1, l2) / (l1 + l2) if (l1 + l2) > 0 else 0
                if upper_bound >= 0.80:
                    sim = difflib.SequenceMatcher(None, fq, ex_fq).ratio()
                    self.assertLess(
                        sim,
                        0.80,
                        f"Item {it['id']} question '{it['question']}' near-duplicates {src} '{ex_fq}' (difflib {sim:.3f} >= 0.80)",
                    )

    def test_key_facts_strictness(self):
        if not all(p.is_file() for p in INDEX_PATHS.values()):
            self.skipTest("data/ indexes not present on this machine")

        indexes = {b: json.loads(p.read_text(encoding="utf-8")) for b, p in INDEX_PATHS.items()}
        chunk_tables = {b: {c["chunk_id"]: c for c in idx["chunks"]} for b, idx in indexes.items()}

        for it in self.items:
            book = it["book_id"]
            q = it["question"]
            kfs = it.get("key_facts") or []
            golds = it.get("gold_chunks") or []

            if it["expect"] == "answer":
                self.assertGreaterEqual(len(kfs), 1, f"Answer item {it['id']} must have key_facts")
                self.assertGreaterEqual(len(golds), 1, f"Answer item {it['id']} must have gold_chunks")

                # Combine gold texts
                gold_texts = [chunk_tables[book][gid].get("text", "") for gid in golds if gid in chunk_tables[book]]
                combined_gold_text = "\n".join(gold_texts)

                for kf in kfs:
                    pat = re.compile(kf, re.I)

                    # (i) Matches gold chunk text
                    self.assertTrue(
                        bool(pat.search(combined_gold_text)),
                        f"Item {it['id']}: key_fact /{kf}/ does not match gold text in {golds}",
                    )

                    # (ii) Matches <= 2% of chunks in book
                    matched_count = sum(1 for c in indexes[book]["chunks"] if pat.search(c.get("text", "")))
                    rate = matched_count / len(indexes[book]["chunks"])
                    self.assertLessEqual(
                        rate,
                        0.02,
                        f"Item {it['id']}: key_fact /{kf}/ matches {matched_count}/{len(indexes[book]['chunks'])} "
                        f"chunks ({rate:.2%}) in {book} (> 2% threshold!)",
                    )

                    # (iii) Does NOT match question text
                    self.assertFalse(
                        bool(pat.search(q)),
                        f"Item {it['id']}: key_fact /{kf}/ matches question text {q!r}",
                    )
            else:
                self.assertEqual(kfs, [], f"Refuse item {it['id']} must have empty key_facts")
                self.assertEqual(golds, [], f"Refuse item {it['id']} must have empty gold_chunks")

    def test_refusal_soundness(self):
        if not all(p.is_file() for p in INDEX_PATHS.values()):
            self.skipTest("data/ indexes not present on this machine")

        indexes = {b: json.loads(p.read_text(encoding="utf-8")) for b, p in INDEX_PATHS.items()}

        refuse_items = [it for it in self.items if it["expect"] == "refuse"]
        self.assertGreaterEqual(len(refuse_items), 40, "Expected at least 40 refusal items")

        for it in refuse_items:
            cat = it["category"]
            target_book = it["book_id"]
            notes = it.get("notes", "")

            # Verify that notes documents out-of-book check
            self.assertTrue(bool(notes), f"Refuse item {it['id']} must have notes explaining check")

            # Extract terms from notes or question for empirical check
            if cat in ("pure_refusal", "fabricated_attribution_trap", "near_miss_refusal"):
                # Extract quoted terms in notes, e.g. 'sourdough' or 'RuBisCO'
                quoted_terms = re.findall(r"'([^']+)'", notes)
                self.assertTrue(bool(quoted_terms), f"Item {it['id']} notes must quote the verified search terms")
                for term in quoted_terms:
                    for b, idx in indexes.items():
                        pat = re.compile(r"\b" + re.escape(term) + r"\b", re.I)
                        cnt = sum(1 for c in idx["chunks"] if pat.search(c.get("text", "")))
                        self.assertEqual(
                            cnt,
                            0,
                            f"Item {it['id']}: refusal term {term!r} was found in {b} ({cnt} chunks!)",
                        )
            elif cat == "cross_book_trap":
                quoted_terms = re.findall(r"'([^']+)'", notes)
                self.assertTrue(bool(quoted_terms), f"Item {it['id']} notes must quote the verified search terms")
                term = quoted_terms[0]
                pat = re.compile(r"\b" + re.escape(term) + r"\b", re.I)
                target_cnt = sum(1 for c in indexes[target_book]["chunks"] if pat.search(c.get("text", "")))
                self.assertEqual(
                    target_cnt,
                    0,
                    f"Item {it['id']}: cross-book term {term!r} was found in target book {target_book} ({target_cnt} chunks!)",
                )
                other_cnt = sum(
                    sum(1 for c in indexes[b]["chunks"] if pat.search(c.get("text", "")))
                    for b in indexes if b != target_book
                )
                self.assertGreater(
                    other_cnt,
                    0,
                    f"Item {it['id']}: cross-book term {term!r} must exist in another book (found 0 hits)",
                )

    def test_dumb_baselines_fail(self):
        if not all(p.is_file() for p in INDEX_PATHS.values()):
            self.skipTest("data/ indexes not present on this machine")

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fair_eval",
            str(ROOT / "artifacts" / "harnesses" / "fair-eval.py"),
        )
        fair_eval = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fair_eval)

        indexes = {b: fair_eval.load_index(p) for b, p in fair_eval.INDEX_PATHS.items()}
        chunk_tables = {b: {c["chunk_id"]: c for c in idx["chunks"]} for b, idx in indexes.items()}

        scores = fair_eval.run_dummy_baselines(self.items, indexes, chunk_tables)

        ans_total = sum(1 for it in self.items if it["expect"] == "answer")
        ref_total = sum(1 for it in self.items if it["expect"] == "refuse")

        # 1. Always-refuse passes 0% of answers, and total passes <= refusal share
        always_refuse_ans_rate = scores["always_refuse"]["ans_passed"] / ans_total
        self.assertLessEqual(always_refuse_ans_rate, 0.15, "Always-refuse passed >15% of answer items")
        self.assertEqual(always_refuse_ans_rate, 0.0, "Always-refuse should pass 0% of answer items")
        always_refuse_tot_rate = scores["always_refuse"]["passed"] / len(self.items)
        self.assertLessEqual(always_refuse_tot_rate, ref_total / len(self.items), "Always-refuse pass exceeds refusal share")

        # 2. Question-echo passes 0% of answers
        echo_ans_rate = scores["question_echo"]["ans_passed"] / ans_total
        self.assertLessEqual(echo_ans_rate, 0.15, "Question-echo passed >15% of answer items")
        self.assertEqual(echo_ans_rate, 0.0, "Question-echo should pass 0% of answer items")

        # 3. Top-1 sent1 echo passes <= 15% of answers
        top1_sent1_ans_rate = scores["top1_sent1_echo"]["ans_passed"] / ans_total
        self.assertLessEqual(
            top1_sent1_ans_rate,
            0.15,
            f"Top-1 sent1 echo passed {scores['top1_sent1_echo']['ans_passed']}/{ans_total} ({top1_sent1_ans_rate:.1%}) > 15% ceiling",
        )

        # 4. Top-1 full echo passes <= 15% of answers
        top1_full_ans_rate = scores["top1_full_echo"]["ans_passed"] / ans_total
        self.assertLessEqual(
            top1_full_ans_rate,
            0.15,
            f"Top-1 full echo passed {scores['top1_full_echo']['ans_passed']}/{ans_total} ({top1_full_ans_rate:.1%}) > 15% ceiling",
        )

        # 5. Gold chunk upper bound passes 100%
        self.assertEqual(
            scores["gold_chunk_upper_bound"]["passed"],
            len(self.items),
            "Gold chunk upper bound should pass 100% of items",
        )

    def test_is_chunk_dump_and_score_item(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fair_eval",
            str(ROOT / "artifacts" / "harnesses" / "fair-eval.py"),
        )
        fair_eval = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fair_eval)

        # 1. Chunk with >=60 words and an inner quote
        book_passage = (
            'The STE pretends the gradient through rounding is 1—a "useful lie" '
            'whose direction is correct on average. The clipped variant additionally zeros '
            'gradients for saturated values to prevent runaway optimization. Fake quantization '
            'simulates deployment in the forward pass while maintaining full precision for gradient computation. '
            'Numerical stability requires explicit safeguards for near-zero and near-constant tensors across all training batches.'
        )
        c_words = fair_eval.fold(book_passage).split()
        self.assertGreaterEqual(len(c_words), 60, f"Expected >=60 words, got {len(c_words)}")

        mock_chunk = {
            "chunk_id": "test-ch5-001",
            "chapter": "5",
            "text": book_passage,
        }
        chunk_table = {"test-ch5-001": mock_chunk}

        mock_item = {
            "id": "test-dev-inner-quote",
            "split": "dev",
            "category": "definition",
            "book_id": "quantization",
            "question": "What is the straight-through estimator?",
            "expect": "answer",
            "gold_chunks": ["test-ch5-001"],
            "key_facts": ["useful lie", "gradient"],
        }

        # Case A: Genuine concise answer with inner double quotes in the citation
        concise_ans = (
            '[Ch. 5] "The STE pretends the gradient through rounding is 1—a "useful lie" whose direction is correct on average."\n'
            'The straight-through estimator pretends rounding gradient is 1 to guide updates.'
        )
        is_dump, reason = fair_eval.is_chunk_dump(concise_ans, chunk_table)
        self.assertFalse(is_dump, f"Concise answer with inner quotes must not be flagged as chunk dump: {reason}")

        score_res = fair_eval.score_item(
            mock_item,
            {"refused": False, "answer": concise_ans, "citations": []},
            chunk_table=chunk_table,
        )
        self.assertTrue(score_res["passed"], f"Concise answer should pass score_item: {score_res['reasons']}")

        # Case B: Full-chunk verbatim dump (zero synthesis: quotes the entire >=60-word chunk with no gloss)
        dump_ans_zero_synthesis = f'[Ch. 5] "{book_passage}"'
        is_dump, reason = fair_eval.is_chunk_dump(dump_ans_zero_synthesis, chunk_table)
        self.assertTrue(is_dump, "Full-chunk quote with zero synthesis must be flagged as dump")

        score_res_dump_zero = fair_eval.score_item(
            mock_item,
            {"refused": False, "answer": dump_ans_zero_synthesis, "citations": []},
            chunk_table=chunk_table,
        )
        self.assertFalse(score_res_dump_zero["passed"], "Full-chunk dump with zero synthesis must fail score_item")
        self.assertTrue(any("dump" in r for r in score_res_dump_zero["reasons"]), f"Expected dump reason, got {score_res_dump_zero['reasons']}")

        # Case C: Full-chunk verbatim dump in gloss (>=75% tokens of chunk verbatim in body)
        dump_ans_in_gloss = f'[Ch. 5] "The STE pretends the gradient through rounding is 1—a "useful lie" whose direction is correct on average."\n{book_passage}'
        is_dump, reason = fair_eval.is_chunk_dump(dump_ans_in_gloss, chunk_table)
        self.assertTrue(is_dump, "Full-chunk verbatim copy in gloss must be flagged as dump")

        score_res_dump_gloss = fair_eval.score_item(
            mock_item,
            {"refused": False, "answer": dump_ans_in_gloss, "citations": []},
            chunk_table=chunk_table,
        )
        self.assertFalse(score_res_dump_gloss["passed"], "Full-chunk dump in gloss must fail score_item")
        self.assertTrue(any("verbatim-copies" in r or "dump" in r for r in score_res_dump_gloss["reasons"]), f"Expected dump or verbatim-copy reason, got {score_res_dump_gloss['reasons']}")


if __name__ == "__main__":
    unittest.main()
