# Answer-model bake-off — results (2026-10-12)

Plan: `artifacts/answer-model-bakeoff-plan.md` (rules frozen before the runs).
Evidence: `artifacts/bakeoff-<tag>.{json,log}` (one battery run per model),
`bakeoff-qwen2.5-7b-run1-flaked.*` (intermittent probe refusal, rerun clean),
`bakeoff-qwen3-4b-instruct-retries.txt` (MAD x3, deterministic),
`bakeoff-side-asks.txt` (monolith + storage, all four models),
`bakeoff-digest.py` (the reader used for every answer below).

Baseline snapshot: `bakeoff-qwen2.5-7b.*` — fresh run today, 18/18 PASS, warm asks
0.42–1.17s. The flake note above is the known intermittent multicloud refusal
(refused while citing ch04-037); it recurred once today and cleared on rerun.

## Gate table (frozen rules: France exact, typos exact, probes pass, no golden answered→refused)

| model | MB | France | typos | probes | golden (bar 8) | battery | warm asks |
|---|---|---|---|---|---|---|---|
| qwen2.5:7b (live default) | 4,683 | PASS | PASS | PASS | 10/10 | PASS | 0.42–1.17s |
| qwen3:4b-instruct | 2,497 | PASS | PASS | **FAIL (MAD)** | 7/10 pin / reviewed below | FAIL | 0.79–1.88s |
| granite4.1:3b | 2,100 | PASS | PASS | **FAIL (multicloud)** | 9/10 | FAIL | 0.73–1.38s |
| granite4.1:8b | 5,348 | PASS | PASS | **FAIL (multicloud)** | 8/10 | FAIL | 1.07–3.82s |

Cold first-ask loads: 33.0s / 11.9s / 18.8s (4b / granite3b / granite8b). No ask
went answered→refused for any model; no model refused anything it used to answer.

## What the reading found (per candidate)

**qwen3:4b-instruct** — 10/10 answered, gloss on almost every answer.
- insert-only: ch05-021 instead of ch05-020. Quote describes the pattern's mechanics;
  the gloss answers the "when useful" part. Acceptable.
- batch vs streaming: ch02-018 instead of ch02-019. Quote is batch-only; so is the
  baseline's quote. Wash.
- transformations: ch02-025 instead of ch02-027. Definition-first quote ("the next
  stage … is transformation, meaning data needs to be changed from its original form
  into something useful"); better than the baseline's abstract quote.
- **MAD probe FAIL (gate):** cites the right chunk (ch04-020, figure-4-1 attached)
  but quotes the "technologies fade into obscurity" sentence; the MAD sentence sits
  in the same chunk unquoted. 3/3 identical, deterministic.

**granite4.1:3b** — 10/10 answered, gloss on almost every answer.
- ETL full question: ch02-022 instead of ch07-033. Quote is about pull ingestion
  ("ETL's extract (E) part clarifies that we're dealing with a pull ingestion model")
  and does not answer "what happens after extracted". Genuine miss — notable because
  the same model answers the typo variant ("in ET?") correctly from ch07-033.
- multicloud probe FAIL (gate): right chunk, quote stops after three sentences
  ("…introduce significant complexity"); the pinned "dizzying array" sentence is in
  the same paragraph unquoted. Correct but incomplete.
- MAD passed (quotes the MAD sentence); batch passed with a gloss stating both sides.

**granite4.1:8b** — 10/10 answered, gloss on almost every answer.
- batch vs streaming: ch02-018 instead of ch02-019; quote batch-only, gloss states
  the streaming side. Pin-only deviation, content equal to baseline.
- transformations: ch02-025, same definition-first quote as 4b. Better than baseline.
- multicloud probe FAIL (gate): same three-sentence stop as 3b.
- ETL full question passed (ch07-033); MAD passed.
- Slower: warm asks 1.4–3.8s vs baseline 0.4–1.2s.

## Side asks (`bakeoff-side-asks.txt`)

Both weak asks answer on all four models; every candidate glosses both.

- **monolith:** granite4.1:8b quotes the actual definition (ch03-056, "The general
  notion of a monolith includes as much as possible under one roof") — the
  definition-first gap that prompt steering could not fix is reachable by model
  choice. qwen3:4b quotes the "technology mainstay for decades" paragraph and
  defines in the gloss; baseline and 3b quote the pros paragraph. Baseline these
  two: quote only, no gloss.
- **What is a storage:** all four cite ch06-001 with figure-6-1. Candidate glosses
  restate the book's metaphor ("cornerstone / most important part"); qwen3:4b's
  brushes the plain sense ("where data is kept and used"), but no model gives a
  literal definition the book never wrote. The two-layer question (book quote +
  plain-words meaning) remains open — it is a format decision, not model ability.

## Verdict (per the frozen rules)

- **No swap. `qwen2.5:7b` stays the default.** Every candidate fails one hard gate.
- All three candidates fix the open gloss weakness (gloss on almost every answer vs
  the baseline's 2/17). That weakness is qwen2.5's behavior, not the app's format.
- Closest to passing: qwen3:4b-instruct (one deterministic content-selection miss);
  granite4.1:3b (one content miss + the multicloud span); granite4.1:8b (multicloud
  span only, but slower and bigger than baseline with no gate advantage).

## Findings and open decisions

1. **Multicloud span vs list-quote expansion.** Expansion fires only when the
   paragraph holds a question anchor the quote lacks (`answer.py`, `_covers_more`);
   a quote that already names "disadvantages" blocks it even when the paragraph
   holds more. The landing note described the feature as "list word → whole
   paragraph". Proposed, NOT applied: show the whole paragraph whenever the question
   names a list word. That would flip granite's multicloud gate — decide on the
   feature's intent, not on the test, and rerun all 18 asks after any change.
2. **Finetune base.** qwen3:4b-instruct (ecosystem: Unsloth walkthrough exists;
   2,497MB) vs granite4.1:3b (closest off-the-shelf behavior: MAD pass, full glosses,
   2,100MB, one content-selection miss). Neither ships as default as-is. Decision
   deferred until (1) is settled.
3. **The failure classes to train on.** MAD (right chunk, wrong sentence) and the
   ETL miss (right chunk retrieved, wrong chunk quoted) are quote-selection
   behaviors — the finetune's target, with labels from our own quote check.

## Not done

No re-embedding, no index change, no re-pins, no prompt edits, no default swap, no
engine change beyond the `ANSWER_MODEL` env seam (`prompt.py`, header in
`artifacts/step2-battery.py`). `step2-battery.{json,log}` hold the live default's
fresh PASS run.

## v2 rerun — after the expansion (2026-10-13)

Tree: the quote-to-paragraph expansion (`_whole_paragraph`, PARAGRAPH_CAP=1200)
uncommitted on top of the RRF fusion commit `853736b`. Frozen across all runs:
md5 fingerprints of `answer.py`, `fusion.py`, `keywords.py`, `captions.py` and the
five test files were identical before and after; every run is snapshotted as
`bakeoff-<tag>-v2.{json,log}`, side asks in `bakeoff-side-asks-v2.txt`.

| model | France | typos | probes | golden (bar 8) | battery |
|---|---|---|---|---|---|
| qwen2.5:7b | PASS | PASS | PASS | 10/10 | PASS |
| qwen3:4b-instruct | PASS | **FAIL (CRU refused)** | **FAIL (MAD)** | 7/10 pin | FAIL |
| granite4.1:3b | PASS | PASS | PASS | 9/10 | **PASS** |
| granite4.1:8b | PASS | PASS | PASS | 8/10 | **PASS** |

What the expansion changed:
- Multicloud flipped green: granite4.1:3b's answer now carries the whole
  disadvantages paragraph, "…dizzying array…diabolically complicated" included,
  with its gloss (`bakeoff-granite4.1-3b-v2.json`). qwen3:4b already passed it.
- CRUD's answer (qwen3:4b) grew to the full CRUD paragraph — the expansion firing
  on an anchored, non-list ask, as designed.

New finding, not the expansion's: qwen3:4b-instruct refuses the CRU typo ask 4/4
on this tree (`bakeoff-qwen3-4b-instruct-cru-retries-v2.txt`) where v1 answered it
from ch05-019. A refusal carries no citations, so the expansion path was never
reached — the retrieval change (RRF + caption placement) is the suspect. The other
three models pass CRU on the same tree.

Determinism: granite4.1:3b's full battery reproduced exactly on a second run
(`bakeoff-granite4.1-3b-v2-run2.*`): the same single reviewed miss (ETL full
question, ch02-022), everything else green.

Side asks (v2): all four models answer monolith and storage. granite4.1:8b still
quotes the ch03-056 monolith definition. granite4.1:3b's monolith answer lost its
gloss versus v1 (quote unchanged) — noted, not a gate. qwen3:4b's storage gloss
brushes the plain sense ("where data is kept and used") but stays book-bound.

Per the frozen rules, both granites cleared the battery. Swap granted
2026-10-13: the default became `granite4.1:3b` (`prompt.py`); the post-swap
battery with no env set was the third consecutive granite4.1:3b pass
(snapshot `bakeoff-granite4.1-3b-postswap.*`). Reverted the same day: "what is
MAD data landscape" — a natural phrasing — got the data-mesh passage from
granite4.1:3b (3/3) and a refusal from granite4.1:8b, while qwen2.5:7b answers
both phrasings (`mad-phrasing-probe.md`; post-revert check
`mad-phrasing-postrevert.txt`, battery `bakeoff-qwen2.5-7b-postrevert.*`). The
multicloud flake recurred once on the cold post-revert run and cleared on rerun
(`bakeoff-qwen2.5-7b-postrevert-flaked.*`) — third recorded occurrence, always
cold. The default is `qwen2.5:7b` again; granite4.1:3b remains the finetune
candidate. A new book or a new index triggers a fresh bake-off under the same
frozen rules.
