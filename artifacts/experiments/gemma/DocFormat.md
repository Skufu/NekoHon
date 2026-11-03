# Document-side format for gemma — nothing beats today's

Embedder `embeddinggemma-2:270m-bf16-text`, book `fde` (`data/index.sqlite`, 1042
chunks). Every chunk re-embedded under six document formats, all 34 distinct fde
questions embedded with the query prefix already in `retrieve.PREFIXES`
(`task: search result | query: `), cosine computed in process over all 1042
chunks. Dense only: no FTS, no fusion, no heading boost. Rank = best rank over
the row's gold ids.

Scripts `/tmp/DocFormat/{docfmt,analyze}.py`. Machine-readable numbers, per-row
ranks and timings: `DocFormat.json` beside this file.

## The required table — canonical 35-row set, fde rows only (n = 5)

Rows: `tech-fde-01..05` from
`artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl`.

| # | document format | top-1 | top-5 | mean gold rank | ranks | seconds |
|---|---|---|---|---|---|---|
| 1 | `title: {heading} \| text: {body}` — **today** | 2/5 | 4/5 | 3.60 | 1,2,2,12,1 | 161 |
| 2 | `title: none \| text: {heading}\n\n{body}` | 3/5 | 5/5 | 1.80 | 1,1,1,3,3 | 142 |
| 3 | `title: {heading} \| text: {heading}\n\n{body}` | 2/5 | 5/5 | 1.80 | 1,2,1,2,3 | 138 |
| 4 | chunk text as stored, no prefix at all | 4/5 | 5/5 | 1.60 | 1,1,1,4,1 | 107 |
| 5 | `passage: {heading} \| text: {body}` | 3/5 | 4/5 | 3.00 | 1,1,2,10,1 | 58 |
| 6 | `title: none \| text: {body}` (no heading anywhere) | 2/5 | 5/5 | 1.80 | 1,1,2,3,2 | 68 |

Five rows cannot separate these. Every paired sign-flip test against format 1 has
p between 0.25 and 0.75 on mean gold rank, and the whole spread is one row
(`tech-fde-04`, the Kinesis question, rank 12 today, 2–4 in formats 2, 3, 4 and
6, 10 under the `passage:` prefix) plus three others swapping places inside the
top 5.

Seconds are 1042-chunk pass times on a shared Ollama with three peer experiments
embedding at the same time — the same format re-run alone took 54 s, so read the
column as contention, not as a format property (median batch 0.9–2.4 s).

## Widening the fde sample flips the ordering back to a tie (n = 34)

Five rows is not enough to choose a format, so the same six vector sets were
scored against every distinct fde question on disk: the 5 canonical rows, 8 more
from `retrieval-recall-2026-11-02.legacy-audited.jsonl` (`fair-dev-*`), and the
21 wide-net rows (`artifacts/datasets/wide-net-2026-10-23.jsonl`, 7 targets ×
3 registers: literal / conversational / vague). Deduped by question text.

| # | format | top-1 | top-3 | top-5 | top-10 | mean gold rank | MRR |
|---|---|---|---|---|---|---|---|
| 1 | **today** | **18/34** | **27/34** | 27/34 | 29/34 | 4.91 | **0.669** |
| 2 | title none, heading in text | 18/34 | 25/34 | **28/34** | **30/34** | 4.85 | 0.648 |
| 3 | heading in both places | 13/34 | 26/34 | **28/34** | **30/34** | 5.03 | 0.598 |
| 4 | raw text | 17/34 | 24/34 | 26/34 | 29/34 | 10.09 | 0.632 |
| 5 | `passage:` prefix | 16/34 | 26/34 | **28/34** | **31/34** | **4.53** | 0.630 |
| 6 | no heading anywhere | 18/34 | 27/34 | 27/34 | 29/34 | 10.65 | 0.662 |

Paired against today's format on the same 34 rows (positive = better rank):

| format | mean rank delta | 95 % CI | sign-flip p | rows moved | top-5 gained / lost |
|---|---|---|---|---|---|
| title none, heading in text | +0.06 | −1.27 … +1.15 | 0.96 | 15 | +2 / −1 |
| heading in both places | −0.12 | −2.24 … +3.03 | 0.96 | 19 | +3 / −2 |
| raw text | −5.18 | −12.29 … +0.09 | 0.14 | 17 | +2 / −3 |
| `passage:` prefix | +0.38 | −1.77 … +0.85 | 0.63 | 18 | +3 / −2 |
| no heading anywhere | −5.74 | −16.62 … +0.29 | 0.20 | 16 | +2 / −2 |

Nothing clears zero. Today's format has the best top-1 (18) and top-3 (27) and
the best MRR; the alternatives buy at most one top-5 row, which is one row.

## Why the numbers move without meaning anything

**The rank changes are real, not embedder noise.** Re-embedding the whole book
under format 1 a second time gives a bit-identical vector set (max absolute
component difference 0.0). The baseline column is also the shipped index: my
format-1 reconstruction produces the same top-5 as the vectors stored in
`data/index.sqlite` on 34/34 queries (20 of 1042 stored vectors differ by more than 1e-3,
max 0.029, from an older formatting pass; the rest match to float noise, and no
rank changes).

**But the top-5 sets are not stable.** Mean Jaccard of the shown five against
today's format: 0.51 for format 2, 0.55 for 3, 0.46 for 4, 0.57 for 5, 0.45 for
6. Only 1–5 of 34 queries keep the identical five. So a format change swaps
roughly three of the five passages the reader sees, and yet top-1 and top-5 come
out where they started. The gold chunk is not sharply favoured by this embedder;
the ranking below the top few is a pool of near-ties that any change to the
document text reshuffles. Reformatting is a lottery ticket, not a lever.

**Each format is uniquely best on its own rows.** Counting rows where a format
ties or wins the best gold rank: today 21, format 2 20, format 3 19, format 5 19,
format 4 18 of 34. Today's format is the worst of the six on 8 of 34.

**The mechanism is heading duplication.** 743 of 1042 chunks share their heading
with another chunk (`Additional Resources` covers 25, `Conclusion` 16, `DataOps`
15), and every chunk's stored text already begins with its heading line. So the
title field is usually not a discriminator, and today's format spends it on a
label that several chunks carry. Where the heading is actively wrong for the
question the format hurts: `tech-fde-04` ("what does Kinesis Data Firehose do")
hits `ch07-013`, whose heading is "Synchronous Versus Asynchronous Ingestion",
and today's format buries it at rank 12 while the heading-in-text forms put it at
2–4. Where the heading is right for the family, they push the gold down instead:
`fair-dev-05` goes 12 → 13 (format 3), and format 3 loses whole-family rows
(`fde-2-vague` 6 → 43). The two effects cancel, which is exactly the n = 34
result.

**The product already survives this.** Asking instead whether the shown five
contain *a* chunk with the gold chunk's heading: today 29/34, format 5 30/34,
format 3 28/34, format 6 28/34. The reader usually gets the right section even
when the exact chunk is a sibling. The residual exact-chunk misses are the same
family-ambiguity the metric itself cannot resolve — lead's problem, as stated.

## Cross-experiment (peers, same worktree, same day)

The three levers measured against this baseline point at one fact, and the
honest version of it is narrower than "granularity works, format does not":

- **Format (this report).** Changes the shown five by ~35 % per question and
  moves no accuracy metric beyond noise.
- **Granularity (Granularity).** Its own correction: halves are 21/30 top-1/top-5
  against whole-chunk 19/30 over all 35 rows — +2 top-1 with a bootstrap CI of
  −3…+8 and no top-5 change; sentences lose 4 top-5. Halves move the same row
  this report moves (`tech-fde-04` 12 → 2, versus 12 → 2–4 for formats 2–4) and
  move a novel row the wrong way (4 → 17). So grain is the same reshuffle, at 2×
  to 6× the index size, and formats are the free version of it.
- **Dimensions (Dims).** Truncation to 256-d leaves the top-5 pool almost intact
  (33/35 rows unchanged) while moving mean gold rank 3.00 → 2.40, i.e. it sharpens
  depth inside an unchanged pool rather than re-drawing the pool.

Shared fact: gemma's ranking is a pool of near-ties, so levers that re-draw the
pool (grain, dimensions) move top-1 by a couple of rows with CIs spanning zero,
and levers that only relabel the same pool (document format) move nothing.

## Verdict

**Nothing beats the current document format. Keep `title: {heading} | text:
{body}`.** Delta against today on fde: format 2 gains +1 top-1 and +1 top-5 on the
5 canonical rows, then gains 0 top-1 and +1 top-5 of 34; format 4 gains +2 top-1
on the 5 rows but loses 1 top-1 and 3 top-3 of 34, with two queries collapsing to
rank 98 and 100 because a bare text with no task prefix is off-distribution for
this model; format 5 keeps only 3.6 of today's 5 passages on average (Jaccard
0.57) for the same total. The document-format question is closed: on this book the embedder's top-1
does not respond to how the chunk is labelled, and the no-heading ablation
(format 6, identical 18/34 top-1 to today) says the heading contributes nothing
to top-1 at all — retrieval is carried by the body, and the body is what the
engine already sends.

Note for whoever owns the metric: format 6 and format 4 match or beat today on
top-1 while doubling mean gold rank through outliers, so mean rank on this book
is tail-sensitive; top-1 and top-5 are the honest summaries here.
