# Specialized history seed audit — independent pass

File: `data/finetune/quote-refuse-2026-10-24.history-specialized.jsonl` (15 rows, 39,005 bytes)
SHA-256: `bf2be39c3c7b603b31a586d03a2b0f7225f67b2a53e4dd441145b760aabbbf10`

Rows are numbered 1–15 in file order. Scope is read-only; only this report was written.
No model was called and no training was run. Improvement is **not measured**.

## Verdict

**No — these are not good seeds for teacher expansion as-is.**

Only row 13 is usable without repair. Eight rows need a rebuilt history, quote, or gloss. Six rows must be dropped because the supplied passage does not support the target and the gloss answers from the invented history instead of the passage. That is the product failure the data is meant to fix, encoded as a correct answer.

The class mix is also wrong: **15/15 rows are definition-plus-register commands** (simplify, shorter, ELI5, plain English, analogy, takeaway). There are zero entity-relation follow-ups and zero premise traps, the two known failure classes. Expanding this file would clone the “define X, then simplify” template and teach the model that a quote need not match the question.

A second, larger defect: **10/15 history answers contain a quote that is not in the book**. Only rows 1, 4, 5, 6, and 7 have a history quote that is verbatim anywhere in the indexes or the raw EPUBs. Those 10 histories could not have passed the current quote gate unchanged, so the “15 real conversations” provenance does not hold.

## Mechanical checks

Method: parsed each JSONL row; compared system to `prompt.SYSTEM` exactly; split the user turn at `\n\nQuestion:` and `\n\nPassages:`; compared the user suffix to `answer.FORMAT_REMINDER` exactly; matched the assistant with `^\[Ch\. N\] "(.*)"\n(.*)$`; validated the quote with `answer._quote_in_passage` against the served `data/index.json`, with an any-index cross-check. Passage parsing stopped before the format reminder, so the reminder's example never counted as evidence.

| Check | Passing rows / 15 |
| --- | ---: |
| Valid JSON, three messages, roles system/user/assistant | 15 |
| System content equals `prompt.SYSTEM` exactly | 15 |
| User contains “Earlier in this conversation” | 15 |
| Exactly one `Question:` line | 15 |
| `Passages:` block with a parsed `chunk_id=` | 15 |
| User ends with the exact `FORMAT_REMINDER` | 15 |
| One passage per row; block shape `[Ch. N] chunk_id=…\n<text>` | 15 |
| Chunk ID exists in `data/index.json`; chapter label matches | 15 |
| Target quote verbatim in that chunk under `data/index.json` (`_quote_in_passage`) | 15 |
| History `Book:` answer starts with `[Ch.` | 15 |
| Target gloss is one line, no `[Ch.` tag, no quotation marks | 15 |
| Target quote is a single line | **8** |
| Target’s quoted sentence equals the history sentence | **5** (rows 1, 4, 5, 6, 7; three add a heading) |
| History quote verbatim anywhere in the corpus | **5** (rows 1, 4, 5, 6, 7) |

Seven target quotes are multiline because they include a heading: rows 4, 6, 7, 8, 9, 11, 12. Row 6 also includes the author line “It bears repeating:”. Verbatim matching passes, but these are not sentence-only targets.

The 10 history quotes that fail are rows 2, 3, 8, 9, 10, 11, 12, 13, 14, 15. Their best sentence match in `data/index.json` scores 0.43–0.60 with `difflib`; they are teacher rewrites, not copies. Measured examples: row 10’s history says “CRUD stands for … and describes the basic operations performed on database records” while the book says “CRUD, which stands for …, is a transactional pattern …”; row 13’s history says “moving data from where it is generated into storage systems” while the book says “moving data from one place to another.”

Index caveat: every target quote validates against the served `data/index.json` and `index.pre-metadata.json`. A naive merged map that keeps the last index per `chunk_id` validates only 8/15, because `index.pre-sentence.json` and `index.embeddinggemma-2.json` are alternate chunkings of the same book and do not contain the same text for those chunks. Validate against the served index, not a merged map.

## Question overlap

Tiers: exact = folded string equality after lowercasing and punctuation folding. Near = content-token Jaccard ≥ 0.70 **and** `difflib` ratio ≥ 0.85. Content tokens use `preprocess.STOPWORDS` and stemming.

| Dataset | Question strings | Exact rows | Near rows (new) |
| --- | ---: | ---: | ---: |
| `hard-bench-2026-10-17.jsonl` | 61 | 0 | 0 |
| `wide-net-2026-10-23.jsonl` | 57 | 0 | 0 |
| `sealed-2026-10-24.jsonl` | 33 | 0 | 0 |
| `adrian-realworld-eval-2026-10-17.json` | 67 | 12 | 0 |

Exact Adrian rows: 1–6, 8–9, 11–14. All are generic commands (`Explain more simply`, `shorter`, `in plain english`, `eli5`, `main takeaway`). Five rows also clear the near threshold against a variant phrasing (`explain it more simply` vs `Explain more simply`), but those rows are already exact matches, so the near tier adds no row.

Three rows use `give an analogy` (7, 10, 15), which is not in the Adrian set. Treat all 15 as generic/canned; the string check is not the useful exclusion test here.

Two history-level findings:

- Row 8’s history question, “What is change data capture?”, is exact-equal to `adrian-18/t1`.
- Row 3’s history question, “What is a watermark in streaming?”, is close to hard-bench `multi_turn_03`’s history, “What is a watermark in stream processing?” (`difflib` 0.889), but its content-token Jaccard is 0.667, below the required 0.70. Report it as **adjacent, not near**.

Conversation-family reuse is the real exclusion problem. Twelve rows reuse an Adrian eval family even when the follow-up string is generic:

| Kind | Rows | Adrian families |
| --- | --- | --- |
| Subject-level replay | 1, 2, 4, 8 | `adrian-01`, `adrian-02`, `adrian-34`, `adrian-14` / `adrian-18` |
| Template-level reuse | 3, 5, 6, 9, 11, 12, 13, 14 | `adrian-01/02/03/14/29/30/33` follow-up commands |
| Not in Adrian | 7, 10, 15 | `give an analogy` |

Rows 1, 2, 4, and 8 reproduce the subject and intent of the held-out Adrian scenarios almost directly. Training on them would inflate the Adrian metric without teaching the failure behaviour. If the plan’s “15 real conversations” are these eval scenarios, the seeds are eval-adjacent by construction.

## Ranked judgment

G = genuine history dependence, F = answer fit, C = connection to the prior subject, R = quote supports gloss, V = plain target with no headers or meta language. Each 1–5. Score is editorial, 0–100. Rule: a wrong passage or R = 1 caps the score at 30; a target that fails the requested transformation cannot rank above 70.

| Rank | Row | Subject | G | F | C | R | V | /100 | Decision and reason |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 13 | Data ingestion | 5 | 5 | 5 | 4 | 5 | 86 | Keep. New, shorter sentence (122 → 71 chars); gloss adds “raw”, “outside”, and “your own” beyond the quote. |
| 2 | 5 | Schema | 5 | 3 | 5 | 5 | 5 | 78 | Rewrite evidence. Clean and supported, but the target quote is exactly the history quote (95 chars), so no new evidence. |
| 3 | 6 | Technical solutions | 5 | 4 | 5 | 4 | 1 | 70 | Trim quote. The takeaway is right, but the target is four lines with “Our definition” and “It bears repeating:”. |
| 4 | 8 | CDC | 5 | 3 | 5 | 3 | 4 | 64 | Trim. New shorter sentence (160 → 142), but the heading is inside the quote and “instant” overclaims the quote’s timing. |
| 5 | 1 | Data maturity | 5 | 2 | 5 | 3 | 5 | 60 | Replace evidence. The quote is identical to history (196 chars) and the gloss says “improve its business” where the quote says “competitive advantage”. |
| 6 | 11 | CRUD | 5 | 1 | 5 | 5 | 4 | 55 | Change question or quote. Correct definition and gloss, but “shorter” produces 181 chars vs 115 in history (+66). |
| 7 | 2 | Reverse ETL | 5 | 2 | 4 | 2 | 5 | 48 | Rewrite quote. Target is longer and more technical than history (95 → 150); warehouse/CRM come from the passage, not the quote. |
| 8 | 3 | Watermark | 5 | 2 | 4 | 2 | 5 | 46 | Fix gloss. Quote defines a window-lateness threshold; gloss says “all earlier events have arrived”, which is the history definition, not this quote. |
| 9 | 7 | Streaming storage | 5 | 2 | 4 | 1 | 4 | 30 | Rewrite quote. Quote only says requirements differ; the DVR/rewind gloss is invented. Quote the retention/replay sentence instead. |
| 10 | 4 | Cloud economics | 5 | 1 | 3 | 1 | 1 | 24 | Drop. Quote is a chapter preamble plus the “Cloud” heading; pay-as-you-go versus buying servers is not in it. |
| 11 | 14 | Push vs pull | 5 | 1 | 2 | 1 | 5 | 22 | Drop. Quote is about streaming fit; gloss defines push/pull from memory; passage never defines either. |
| 12 | 10 | Idempotence | 5 | 1 | 1 | 1 | 5 | 20 | Drop. Quote is about ORM class structure; gloss is an elevator analogy. Same chapter, unrelated entity. |
| 13 | 15 | Latency/throughput | 5 | 1 | 1 | 1 | 5 | 20 | Drop. Quote is about row explosion in joins; gloss defines latency/throughput from memory. |
| 14 | 9 | ACID | 5 | 1 | 1 | 1 | 5 | 18 | Drop. Quote says small companies run analytics on OLTP; gloss defines ACID guarantees. Passage never mentions ACID. |
| 15 | 12 | Compaction | 5 | 1 | 1 | 1 | 2 | 15 | Drop. Quote is Snowflake micro-partitioning; gloss describes file compaction; “hundreds” is invented. |

All 15 pass G only because a bare `shorter` or `Explain more simply` is meaningless without history. That is shallow dependence: the subject comes from the history, but no row requires choosing between referents or between passages. The supplied single passage often reveals the subject on its own.

Target-length evidence for the transformation rows: 3 (160 → 167), 4 (248 → 254), 11 (115 → 181), and 12 (107 → 162) all got **longer** despite asking for shorter/simpler/plain English. Row 13 is the only row that measures a real shortening **and** has a supported gloss (122 → 71; total 244 → 167). Row 8 also shortens (160 → 142) but overclaims timing; rows 10, 14, and 15 shorten while quoting an unrelated passage.

### Drop list

**Hard drop (wrong evidence or unsupported target): 4, 9, 10, 12, 14, 15.**
With the current passage bundles, rows 9, 10, 12, 14, and 15 should have had the exact refusal `Not in this book.`; row 4 needs a different quote from the same chunk. Replacing the passage would create a new example, not repair these labels.

**Rebuild before use: 1, 2, 3, 5, 6, 7, 8, 11.**
Rows 1, 5, and 6 re-quote the history sentence; rows 4 (dropped) and 7 also re-quote it under a heading. Rows 2, 3, and 8 have a gloss that drifts from the quote. Row 11 fails the requested shortening.

**Keep unchanged: 13.** No row is approved as a distinct new evidence example except this one.

## Three short examples

- **Row 13, good.** History quote 122 chars; target quote 71 chars from the same chunk (“moving data from one place to another”); gloss says the same thing in reader words. The only drift is “raw”, “outside”, and “your own”, which the passage supports but the quote does not.
- **Row 9, wrong passage.** The quote says small companies run analytics directly on an OLTP. The gloss defines ACID. The passage never mentions ACID, so the target teaches the model to answer from history and attach an unrelated quote.
- **Row 3, gloss drift.** The quote defines a watermark as a threshold a window uses to decide whether data is late. The gloss says “all earlier events have arrived”, which is the history’s invented definition. The quote is real; the answer is not derived from it.

## What the two known failure questions need

The exact questions are already held out in hard-bench:

- `multi_turn_07`: “What are the key trade-offs and operational overhead of using it?” after two Kafka/ingestion turns.
- `multi_turn_02`: “Why do the authors warn against that?” after “Should teams build their databases from scratch?”

Do not seed from those conversations or close paraphrases.

The current file has none of the required shapes:

| Missing shape | Current count |
| --- | ---: |
| Interrogative follow-up about a property of the prior entity (“what are its trade-offs”, “why is it used”) | 0 |
| Deictic subject (`it`, `that`, `they`) as the question’s subject | 0 |
| Two prior turns (`HISTORY_TURNS = 2`) | 0 (all one turn) |
| More than one passage per row / a competing distractor passage | 0 |
| Exact refusal target | 0 |
| Premise-trap or false-presupposition target | 0 |
| Target gloss that resolves a pronoun to the prior entity | 0 (no pronoun questions) |

**Entity-relation rows** need: a prior turn that introduces entity E; a follow-up that asks about E’s trade-offs, overhead, cost, limitation, or reason for use through a pronoun or elided subject; the *property* chunk as the evidence, with the definition chunk as a distractor; and a gloss that names E (“Kafka’s overhead is …”) so the model cannot pass with generic wording. Include topic-change negatives so history cannot be used as the answer.

**Premise-trap rows** need: a prior turn where the authors recommend the practice, followed by “Why do the authors warn against that?”; a property the book never states (“How much does AWS charge per hour for that?”); or a prior gloss that asserts something the passages do not support. Targets must be either a passage-supported correction or the exact refusal. History may identify the subject; it must never supply the missing evidence.

The current data does the opposite: it supplies invented history and then answers from it. Ten of the 15 history quotes are not in the corpus. Five targets (9, 10, 12, 14, 15) pair a fabricated history with an unrelated passage; row 4 uses a grounded history but a preamble quote.

## Recommended 200-row class mix

These are generation targets, not observed results. Primary classes are mutually exclusive.

| Class | Rows | Share | Required cases |
| --- | ---: | ---: | --- |
| Entity-relation | 90 | 45% | 40 trade-off/operational-overhead; 25 valid warning-reason; 25 other antecedent (how it works, why used, who created, which chapter). 30 two-turn; 60 with a competing passage. |
| Premise-trap | 50 | 25% | 20 false-warning premises; 15 history-only assertions unsupported by passages; 15 absent property/price/year. Target 35 exact refusals and 15 supported corrections. |
| Simplify | 30 | 15% | 12 plain-language, 8 shorter (measure a shorter target), 6 analogy, 4 ELI5. Require a **new** evidence sentence, not the history sentence; no stronger guarantee than the quote. |
| Highlight | 30 | 15% | Selection carried through the actual serving renderer; 10 rows where the selection names a term the history did not. Follow-up must need the selection. |
| **Total** | **200** | **100%** | 35 planned refusals; 30 two-turn; at least 100 with a distractor passage. |

Cross-cutting quotas: 15 training-only conversation families with documented provenance; split by source conversation and source-passage family before generation; 30 two-turn histories; 100 rows with a competing passage; 35 refusals. Do not count siblings from one conversation as independent coverage.

Acceptance gate for every teacher row:

1. System equals `prompt.SYSTEM`; user equals `answer.user_message` byte-for-byte.
2. Every history quote is verbatim in `data/index.json` for its source chunk.
3. The target quote is verbatim in the supplied passage and is either a new sentence or an explicitly justified re-gloss.
4. The gloss is entailed by the quote, not by the history.
5. The follow-up cannot be answered without the history; and for relation/trap rows, cannot be answered without the correct passage.
6. The row is disjoint from Adrian, hard-bench, wide-net, and sealed conversation families.

## Execution record

Checks ran locally with Python 3.12 and the repository’s `prompt` / `answer` modules for constants and `_quote_in_passage`. All 15 rows and all seven `data/index*.json` files were read. No model calls, no training, and no test suite were run; this is a dataset audit.

One method artifact: a merged index map that lets later files overwrite earlier ones reports 8/15 target quotes, because the alternate chunkings (`index.pre-sentence.json`, `index.embeddinggemma-2.json`) do not contain the same text for seven chunks. Against the served `data/index.json`, the count is 15/15.

No source, data file, existing report, or artifact index was edited. This report is the only write.
