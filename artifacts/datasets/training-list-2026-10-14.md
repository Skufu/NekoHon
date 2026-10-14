# Next training list — the five sealed items x2d still fails after the retry (2026-10-14)

Source: the post-retry sealed-suite re-measure
(`artifacts/reports/retry-safety-net-2026-10-14.md`), 10 draws per item.
Four of the five are teacher-passable and become generation targets; one is a
measured teacher ceiling.

**The sealed items themselves are never trained.** This file names content
targets and form classes; every generated form goes through the per-build
seal check (`probe-fragment` aborts on a near-match; declared twins are
logged, never trained).

| sealed item (never trained) | x2d post-retry | 7B (same draws) | class | content target (gold) |
| --- | --- | --- | --- | --- |
| `how do` | 0/10 | 10/10 | bare wh-fragment | — (degenerate; the teacher answers from the top passages) |
| `Time Series` | 1/10 | 10/10 | bare topic | ch05-045, ch05-046 ("Time series") |
| `column-oriented vs row-oriented` | 0/10 | 10/10 | order pair B | ch06-066, ch06-067 ("The evolution from rows to columns"); app01-008 (Columnar Serialization) |
| `row-oriented vs column-oriented` | 0/10 | 10/10 | order pair B, flipped | same |
| `why does` | 0/10 | **0/10** | bare wh-fragment | — **teacher ceiling: the 7B fails it too — do not promise this from 7B distillation; record it, or fix by another route** |

Next-build actions:

- `how do` / `why does` (fragments): teach the fragment-continuation shape
  over existing cards (the x2d build's classes covered `explain` and
  `what about`, both now 10/10, but not bare wh-fragments).
- `Time Series`: the bare-topic class took for Streaming / Micro-Batch /
  Event Streams (10/10 each) but not this card — find why at build time
  (gold above) and add it.
- Pair B (both directions): the order class generated pair A only
  (`batch vs streaming` both directions, now 10/10 each); generate pair B
  from the ch06-066/067 + app01-008 cards.

Also in the same build (same citation gap, visible targets, not sealed):

- `Location`, `DE Lifecycle`, `ddr4 vs ddr5` — answered but still uncited
  after the retry (measured 2026-10-14): teach the cited-answer form for
  these three cards.

Recipe (unchanged from the x2d build): teacher capture through the shipped
seam at temp 0; ~3 forms per card for the classes above; counts per the x2d
builder; seal check + contamination probe per build; hold-outs stay sealed
(`artifacts/datasets/sealed-forms.json`).

A sixth failure recorded today was engine-side, not training: the second
book's `chapter-N` labelling (`ingest._chapter_number`) — fixed same day
(`chapter-4` -> `4`, index rebuilt, citations transfer; retest in
`artifacts/reports/second-book-2026-10-14.md`).
