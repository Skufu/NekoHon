# Fiction generation profile — 2026-11-01

Owner ask: for a fantasy/novel book, stop answering with one strict quote and
one gloss line. Make the sampler looser, take more passages, and let the
answer hold more than one moment.

Measured on `data/index.mushoku-tensei_-jobless-reincarnation--light-novel--vol-80a406d0.sqlite`
(274 chunks, 333 260 characters). Eight questions, `answer.respond`, one run
per configuration. Ollama on the same machine, `nekohon_q35_2b_x3_2e`.

## What was wrong

Two causes, both structural rather than sampling:

1. `_ensure_answer_gloss` rewrites every non-refused body down to the first
   citation line plus **one** gloss line. A 600-character scene came back as a
   two-line answer regardless of what the model wrote.
2. The parsers assume technical prose. `parse_completion` takes the first
   `"…"` pair on a line as the quote — in a novel that is the character's
   speech, not the passage. `parse_answered` rebuilds the quote from the
   best-overlapping passage sentence and drops anything under
   `KEY_MIN_CHARS = 40`; a novel's dialogue is mostly shorter than that, so it
   fell back to the whole passage (one 909-character citation seen live).

Baseline (`respond`, before any change, temperature 0, five passages):
mean 246 characters, one citation in 8 of 8 answers, 0 refusals, ~4 s.

## Prompt shape alone does not fix it

Three prompt shapes, eight questions each, same window:

| prompt | answers citing >1 passage |
|---|---|
| quote-first, "quote two or three passages" | 0 / 8 |
| three mandatory quote lines, each ≤2 sentences | 1 / 8 |
| inline `[Ch. N]` tags at sentence ends | 1 / 8 |

The fine-tune answers with one quote whatever the instruction says. Prefilling
`[Ch. ` and `[Ch. 1] "` did not change that (1–3 citations, inconsistent, and
the prefill pins the chapter).

## What works: ask again, from a narrowed window

`answer._fiction_body`: round 1 uses the eight passages; every later round
drops the passages already quoted, so the model cannot quote the same scene
again. Each round is parsed by `parse_fiction`, which accepts a quote only when
a shown passage holds it verbatim. Quotes merge, one per passage (the longer
cut wins), up to two passages; the longest paragraph any round wrote is kept.

| configuration | cites >1 | mean cites | mean chars | mean answer time |
|---|---|---|---|---|
| baseline, 1 round, five passages | 0 / 8 | 1.00 | 246 | 4 s |
| 2 rounds, window repeated | 2 / 8 | 1.25 | 154 | 20 s |
| 3 rounds, window repeated | 2 / 8 | 1.25 | 200 | 31 s |
| 3 rounds, window narrowed | 6 / 8 | 1.75 | 336 | 31 s |

Times are wall clock while other work ran on the machine. Two rounds on an
idle machine measured 7.0 s and 8.5 s per HTTP answer (traces
`/tmp/fiction-http2.jsonl`, two generations each).

`num_predict` stays at 512: at 900 one rambling round took 56 s, and no fiction
answer in the run used more than half the cap.

The streamed path carries the same profile: `stream: 1` on *Describe Eris*
emitted 222 `token` frames and one `final` with two citations (2 × `[Ch. 9]`
and `[Ch. 8]`), one generation, 36 s under load, `query.generation_profile`
recorded in the trace.

## Known limits

- The second moment is sometimes off-topic ("The summoning worked." for *why
  did the Superd attack*). It is still verbatim from a shown passage, so it is
  honest evidence, but it does not always support the paragraph.
- A quote long enough to be a scene is cut at 600 characters on a sentence
  boundary (`_cap_fiction_quote`); the rest of the scene is not shown.
- Front/back matter chunks carry their section id as the chapter
  (`[Ch. section-0015]`), which reads oddly in a citation. That is ingest's
  chapter labelling, unchanged here.

## Knobs

`FICTION_TEMPERATURE` (0.55), `FICTION_PASSAGE_LIMIT` (8),
`FICTION_QUOTE_TARGET` (2), `FICTION_SAMPLE_ROUNDS` (3). A book's kind is
`index["kind"]`, else `bookkind.detect_kind`; `python3 scripts/book-kind.py
<index> --set fiction` pins it.

## Technical books

Unchanged, and verified live: `ddia` "What is a write-ahead log?" ran with
`generation_profile {kind: nonfiction, passage_limit: 5, options {temperature:
0, num_predict: 512}}`, one citation, 5.5 s. `test_fiction_profile` holds both
profiles to those numbers.
