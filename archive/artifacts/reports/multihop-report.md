# Multi-hop retrieval hunt: agentic loop vs single-shot (measured)

Date: 2026-10-13. Index: `data/index.json`, 1042 chunks, nomic-embed-text,
answer/decision model qwen2.5:7b, temperature 0. Read-only; nothing wired.

Commands run (from repo root):

- `python artifacts/multihop-probe.py` (live Ollama; raw data in
  `artifacts/multihop-results.json`)
- `python artifacts/multihop-explore.py ...` (index greps and tool-reach checks)

Wall-clock latency is not reported as a clean number: other processes share the
Ollama server. Seconds are in the JSON under `seconds_unreliable`. The
trustworthy measures here are model-call/step counts and found/not-found.

## Method

Two retrieval paths per question, exactly as specified:

- single-shot: `answer.retrieval_context(index, question)["passages"]` -- the
  top-5 the answer model is shown (after reading repair, fusion, caption seed).
- agentic: `agentic.agentic_search(index, question)` -- up to 3 model-picked
  tool calls, merged passages uncapped.

Ground truth per question is a fixed list of chunk ids that together carry both
halves of the question, established by grepping the index (exploration log in
the probe's `note` fields; full texts checked with `multihop-explore.py
--show`). "Surfaced" = every needed chunk id appears in that path's passages.
One question per candidate, one run; decisions are deterministic (temperature
0), but this is a single sample per question.

Two evidence policies matter for honest counting, both measured:

- Overlapping chunks: `ch06-045` and `ch06-046` share the key sentence
  ("Update management for object storage is the central idea behind the data
  lakehouse concept..."). For Q4 either chunk satisfies the relation half.
- Alternate chunks: Q2's mechanism half ("which database mechanism does CDC
  rely on") is carried by `ch05-018` (write-ahead logs) and independently by
  `ch02-023` (binary logs). Either satisfies it.

## Results

Needed = ground-truth chunk set; "single" = single-shot top-5; "loop" = merged
passages (position shown). Steps are loop decision calls.

| # | question (abbrev) | needed chunks | dense rank | single-shot | loop | verdict |
|---|---|---|---|---|---|---|
| 1 | data contract / SLAs | ch05-071, ch09-004 | 3, 4 | found (pos 3, 4) | found (3 steps, semantic x3, pos 3, 4) | tie |
| 2 | CDC / mechanism | ch05-013 + ch05-018 or ch02-023 | 2, 17, 11* | **miss** (ch05-013 only) | **found** (3 steps, semantic x3; ch05-013 pos 2, ch02-023 pos 9/11) | loop-only, outside a top-5 cut |
| 3 | normal forms / columnar | ch08-051, ch06-067 | 1, 2 | found (pos 1, 2) | found (3 steps, semantic x3, pos 2, 1) | tie |
| 4 | lakehouse / object storage | ch03-082 + ch06-045 or ch06-046 | 5, 6, 2 | found (ch03-082 pos 5, ch06-046 pos 2) | found (2 steps, semantic x2, all pos <= 6) | tie (overlap; see below) |
| 5 | multicloud motivation / advice | ch04-036, ch04-041 | 1, 4 | found (pos 2, 5; 1 gen call, rejected reading) | found (3 steps, semantic x3, pos 1, 4) | tie |
| 6 | BASE / object consistency | ch06-023, ch06-049 | 2, 1 | found (pos 2, 1) | found (2 steps, semantic x2, pos 2, 1) | tie |
| 7 | PII transformation / access | ch02-066, ch10-011 | 5, 212 | **miss** (ch02-066 only) | **miss** (3 steps, semantic x3; ch02-066 pos 6/13, ch10-011 absent) | both miss |
| 8 | MDM / governance | ch02-059, ch02-013 | 1, 313 | **miss** (ch02-059; ch02-046 partial) | **miss** (3 steps, semantic x3, max_steps; ch02-059 pos 1, ch02-013 absent) | both miss |
| 9 | reverse ETL / serving | ch02-040, ch09-055 | 2, 1 | found (pos 2, 1) | found (2 steps, semantic x2, pos 2, 1) | tie |
| 10 | streaming decision / unbounded | ch02-020, ch07-007 | 6, 115 | **miss** (neither) | **miss** (2 steps, semantic x2; ch02-020 pos 6/10, ch07-007 absent) | both miss; loop gains one half |

*Q2 dense ranks: ch05-013 #2, ch05-018 #17, ch02-023 #11 (measured after the run, same question).

Totals: single-shot surfaced the full needed set on 6/10; the loop on 7/10
(any position) and 6/10 within its first five merged passages. Per evidence
half: single 15/20, loop 17/20. The loop's two extra halves (`ch02-023` Q2,
`ch02-020` Q10) each arrived at merge positions 9 and 6 respectively -- at or
outside a 5-passage cut. The loop's top-5 coverage is the same six questions
as single-shot.

Cost (measured, same runs): the single-shot path spent 1 model call over the
10 questions (Q5's reading-repair proposal, rejected; Q3's reading was the
offline difflib repair). The loop spent 26 decision calls (2-3 per question,
2.6 average), merged 10-13 passages per question (109 total vs 50), and
stopped by `nothing_new` 9 times and `max_steps` once. All 26 decisions chose
`semantic`; keyword and regex were never picked. The decision queries were
paraphrases of the original question, e.g. Q7: "data engineers personally
identifiable information handling regulations access control" (three times).

## Overlap correction (Q4)

The raw run showed Q4 as single miss / loop found. That was a ground-truth
artefact, not a retrieval win: single-shot's passage list contained `ch06-046`,
which -- because the chunker's span overlaps `ch06-045` -- carries the same
key sentence ("...central idea behind the data lakehouse concept, which we
introduced in Chapter 3"). The loop's extra hit was the duplicate `ch06-045`
at merge position 6. With either chunk counted as the relation evidence, Q4 is
a tie.

## Tool reach (why the loop missed Q7/Q8/Q10)

Offline checks: if a tool is *handed* a query, can it reach the chunk the loop
never surfaced? Queries below were written by me (not by the model) to test
tool reach, not decision behavior.

| missed chunk | hand query | semantic | keyword | regex |
|---|---|---|---|---|
| ch05-018 (Q2) | "database logs change data capture binary log" | rank 2 | rank 5 | not top 10 |
| ch10-011 (Q7) | "masking PII sensitive data access control views" | rank 1 | rank 1 | not top 10 |
| ch02-013 (Q8) | "master data golden records data governance tracking" | not top 10 | rank 1 | not top 10 |
| ch07-007 (Q10) | "streaming ingestion preserves unbounded nature of data" | not top 10 | rank 1 | rank 7 |

Measured reading: the misses are a decision-policy failure, not a tool-reach
failure. The evidence was reachable (semantic or keyword, rank 1-5) under
queries that name the missing half; the loop's paraphrase-only semantic
queries did not reach it (dense ranks of the missed chunks under the original
questions: 17, 212, 313, 115).

## Verdict

No measured win on this set justifies wiring the loop. Strongest single case:
Q2 -- the mechanism half (binary logs, ch02-023) appeared only in the loop's
merge, at position 9 of 11, so translating it into an answer still requires a
cut/order rule the prototype does not have. Cost side: +2.6 decision calls per
question, 2.2x merged passages, and zero use of the two non-semantic tools over
26 decisions. Unproven: whether a decision policy that actually picks keyword/
regex (all four misses are reachable, per the table above) turns reach into a
win; whether a 5-passage cut can preserve the loop's extra evidence; and
whether any of this transfers to other books or decision models.

## Files (new, untracked; no tracked file modified)

- `artifacts/multihop-probe.py` -- the runner (candidate set, both paths, JSON).
- `artifacts/multihop-results.json` -- raw per-question data (ids, steps,
  tools, queries, positions, unreliable seconds).
- `artifacts/multihop-explore.py` -- index grep / chunk dump / tool-reach helper.
- `artifacts/multihop-report.md` -- this report.
