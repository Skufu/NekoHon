# Validation-gated retry — reduction to practice (2026-10-14)

The x2d verdict (`x2d-plan-2026-10-14.md`) closed with option (c): build the
P1-1 retry from `finetune-expert-review-2026-10-14.md`, re-measure the suite,
then decide. This is that build and that measurement. No model changed; the
engine did.

## What shipped

`answer.py`:

- `ollama_generate(..., prefill="")` — a trailing assistant turn makes Ollama
  continue from the prefill instead of starting a reply (probed on this box
  2026-10-14 before designing on it: `hello` continued as ` world`). The caller
  prepends the prefill text.
- `_retry_uncited(...)` — when an answer-mode reply is not a refusal and has
  zero citations, ask once more with the assistant turn prefilled `[Ch. `.
  The retry body is adopted only when a citation survives a parse AND its
  quote is verbatim passage text; every other path returns None and the
  original answer stands. Monotone by construction: it can only add citations.
  Two parsers are tried: `parse_answered` (prose continuation) and
  `parse_completion` (ask shape) — `_sentence_claims` cites text *before* a
  tag, so the tag-first reply the prefill actually produces can only validate
  through the ask parser (measured while building; the first implementation
  silently rejected every retry).
- `respond` calls the retry only in the standard branch (not the plain
  register), once, and never on refusals.

**Trigger widened from the review's "anchors present", with a measured
reason.** Anchor coverage on the sealed suite (computed 2026-10-14,
`anchor_words` against the shipped index):

| item | anchors |
| --- | --- |
| explain | `explain` |
| Time Series | `series` |
| File Formats | `file`, `formats` |
| Micro-Batch | `micro` |
| Event Streams | `streams` |
| column/row-oriented (both) | `column`, `oriented`, `row` |
| what does etls stand for | `stand` |
| benefits of data meshs | `benefits` |
| how do, what about, why does, Streaming, batch vs streaming, streaming vs batch, pipeliness | (none) |

The anchors gate cannot fire on 7 of 16 non-control items, including the
largest failure class. The trigger is therefore uncited + passages present;
the verbatim-quote check (already the parse's own rule) does the safety work.

## Suite re-measure (sealed, 10 draws/item, answer mode, temp 0)

Commands: `python artifacts/probes/probe-fragment-2026-10-14.py --model
smallbook_x2d --draws 10` and `--model smallbook_x2`. Pre-retry files are kept
as the `.gate` twins (the numbers above are also in the x2d verdict and the
x2-trial doc).

| class | 7B bar | x2 gate | x2 retry | x2d gate | x2d retry |
| --- | --- | --- | --- | --- | --- |
| fragment | 20/40 | 20/40 | 21/40 | 10/40 | 20/40 |
| bare-topic | 50/50 | 30/50 | **50/50** | 0/50 | 41/50 |
| order-flip | 40/40 | 0/40 | 21/40 | 10/40 | 20/40 |
| trailing-letter | 30/30 | 10/30 | 19/30 | 1/30 | **30/30** |
| control | — | 20/20 | 20/20 | 20/20 | 20/20 |
| loops | 0 | 10 | 10 bare + 10 greeting | 0 | 0 |
| four gated classes total | 140/160 | 60/160 | 111/160 | 21/160 | 111/160 |

Retry mechanics (draws where it fired / draws it won): x2d 129 / 90
(fragment 20/10, bare 50/41, order 30/10, trailing 29/29); x2 89 / 50.

x2d per item still failing after the retry: `how do` 0/10, `why does` 0/10,
`Time Series` 1/10, `column-oriented vs row-oriented` 0/10, `row-oriented vs
column-oriented` 0/10. Recovered examples: all of bare except Time Series
(0→10 each), `explain` 0→10, `streaming vs batch` 0→10, all three
trailing-letter items 1/0/0 → 10 each.

x2d still fails pre-registered gate item 2 (bare 41 < 50, order 20 < 40);
x2 under the same engine also fails it (order 21 < 40, trailing 19 < 30) and
item 3 (20 loops). Gate items 1, 4, 5 are ask-mode or refusals and are
unchanged by construction (the retry is answer-mode only); item 6 unchanged
(see below).

## Visible ten (x2d, re-run 2026-10-14)

`python artifacts/probes/probe-trial-queries-2026-10-14.py smallbook_x2d`
(previous record kept as `.gate`). Answered: `what is`, `Our Advice`,
`DDR5 vs ddr4` (cited). Refused: `hey`, `warrup`, `speed of ddr5`,
`speed of ddr5s`. Answered but still uncited after the retry: `Location`,
`DE Lifecycle`, `ddr4 vs ddr5` — the three items the x2d verdict flagged as
uncited remain unresolved; the retry did not rescue them.

## Second book under the retry

Same probe as the second-book test, now on all three models
(`probe-second-book-2026-10-14.retry.{json,log}`; the pre-retry files keep
the earlier record). In-book questions rescued: x2 2/10 (`affine` and
`granular` now cite gold), x2d 1/10 (`turboquant`). Controls: x2 and x2d all
3 exact; the 7B still answers `The capital of France is Paris. [Ch. 4]` and
the app pins it to chapter-4-022. The retry's power is FDE-shaped too: 90/129
on the FDE suite vs 3/20 on the foreign book (the parse demands a verbatim
quote, and the models paraphrase more on unseen content).

## Tests

`python -m unittest discover -s tests` — 219 green, 4 new: retry adopted
(tag-first, through the ask parser), retry rejected when no quote validates,
refusal never retried, generator without prefill support keeps the answer.

## What this leaves for the decision

- The engine is strictly better for whichever model runs: x2's suite went
  60/160 → 111/160, x2d's 21/160 → 111/160, on the four gated classes.
- x2 and x2d now tie on suite total by different profiles; x2d leads on
  battery (20/21 ×3 vs 18-19), loops (0 vs 20 in the suite), pins (both ETL
  targets fixed), trailing (30 vs 19); x2 leads on bare (50 with loops vs 41)
  and by 1 draw on fragment/order.
- The 7B bar was recorded pre-retry; refreshed under the retry 2026-10-14
  (same harness, same code, 10 draws): the bar does not move — 140/160 with
  per-class scores identical to its pre-retry twin (refresh section below).
  Applying the pre-registered bar post-retry keeps `smallbook_x2` the default;
  the numbers for a swap or a keep are in the tables above.
- Not re-run: x2d q8 suite spot (follow-up), the battery (ask mode, unaffected
  by construction), the second-book index's chapter labelling (separate fix,
  still open from earlier 2026-10-14).

## 7B bar refresh under the retry (2026-10-14, same day)

The decision section above left one measurement open: would the teacher's bar
move once the retry ran for it too? Measured — it does not.

Run: `python artifacts/probes/probe-fragment-2026-10-14.py --model qwen2.5:7b
--draws 10` on the retry-era code; the pre-retry twin is preserved as
`evidence/probe-fragment/probe-fragment-2026-10-14.model-qwen2.5-7b.gate.{json,log}`
(the plain name now holds the refresh).

| model | fragment | bare | order | trailing | total /160 | controls |
| --- | --- | --- | --- | --- | --- | --- |
| qwen2.5:7b, pre-retry | 20/40 | 50/50 | 40/40 | 30/30 | 140 | 10/20 |
| qwen2.5:7b, post-retry | 20/40 | 50/50 | 40/40 | 30/30 | 140 | 10/20 |
| smallbook_x2d, post-retry | 20/40 | 41/50 | 20/40 | 30/30 | 111 | 20/20 |

Reads:

- The bar stands: the pre-registered item-2 gap (bare, order) is real, not a
  stale-twin artifact.
- The x2d deficit (29 draws) = `how do` (10) + bare `Time Series` (9) + the
  `column-oriented vs row-oriented` pair both ways (20), minus x2d's
  `what about` gain (10; the 7B fails it 0/10).
- Controls invert: x2d refuses 20/20; the 7B leaks on the violin item
  (`A violin has four strings.` before the refusal, 0/10) — pre-existing,
  identical in its pre-retry twin.
- All four teachable deficit items sit on
  `datasets/training-list-2026-10-14.md`; `why does` (0/10 both) stays a
  ceiling.
