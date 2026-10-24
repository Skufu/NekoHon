# Test fairness — 2026-10-24

Owner direction 2026-10-24: make the gate fair, and make all testing fair for
future testing.

The trigger: the Qwen3.5 candidate scored 6/10 on the ask battery twice against
a bar of 8, which read as a regression. It was not. The battery required the
model's first citation to equal one stored chunk, and four of those ten chunks
were not the top-ranked passage. The candidate consistently quotes the
top-ranked passage. It failed exactly those four.

## 1. What the old rule measured

Retrieval rank of each pinned chunk, and the rank each model cited (in-process,
same index, 2026-10-24):

| ask | old pin | pin rank | x3 cited | q35 cited |
|---|---|---:|---:|---:|
| What does CRUD stand for? | `ch05-019` | 1 | 1 | 1 |
| What is data ingestion? | `ch07-002` | 1 | 1 | 1 |
| What is a watermark? | `ch08-039` | 1 | 1 | 1 |
| When is an insert-only table useful? | `ch08-107` | 1 | 1 | 1 |
| Where does storage sit in the lifecycle? | `ch06-001` | 3 | 3 | **1** |
| What do source systems provide? | `ch05-004` | 2 | 1 | **1** |
| How does data architecture relate to EA? | `ch03-013` | 1 | 1 | 1 |
| Batch vs streaming | `ch02-019` | 1 | 1 | 1 |
| What happens after extraction in ETL? | `ch08-094` | 2 | 2 | **1** |
| What do transformations do? | `ch02-025` | 2 | 2 | **1** |

The old gate was `first citation == pin`. Six pins were rank 1, so both models
passed. The four rank 2-3 pins were exactly the four the candidate failed. The
incumbent passed three of them by skipping past the top-ranked passage; the
candidate never skips.

Two pins were wrong on their own text, with no model involved:

- `ch05-004`, for "What do source systems provide?", is a section intro:
  *"Source systems produce data in various ways. This section discusses the main
  ideas..."* It never says what they provide. `ch02-005` does: *"A source system
  is the origin of the data used in the data engineering lifecycle."*
- `ch06-001`, for "Where does storage sit?", answers importance: *"Storage is
  the cornerstone... underlies its major stages"*. It never places storage among
  the stages. `ch02-002` enumerates the five stages, which is where position
  comes from.

## 2. The rule now

`artifacts/harnesses/fair_cite.py`, used by every answer-model gate:

- **A citation passes when the passage it points at contains the question's
  terms.** Terms are authored from the question and stored in
  `artifacts/datasets/battery-pins.json`, never from a model output.
- **The pin is a note.** Citing a different passage that answers is a pass.
- **Retrieval is scored separately.** In answer mode the pinned passage must
  still be among the shown passages; that is retrieval's job, not the model's.
- **A chapter expectation has a content escape.** If the item declares required
  concepts and the cited passage carries them, a different chapter passes. A
  chapter mismatch with no content signal still fails, and `forbidden_chapters`
  and `same_chapter_as_previous_turn` stay hard, because those test behaviour.

Re-pins, with the justification recorded in the JSON:

| question | old pin | new pin | why |
|---|---|---|---|
| Where does storage sit in the lifecycle? | `ch06-001` | `ch02-002` | old answers importance, not position |
| What do source systems provide? | `ch05-004` | `ch02-005` | old is a section intro that never answers |

The other eight pins were already the passage that answers, so they stay.

## 3. What changed in each harness

| file | change |
|---|---|
| `harnesses/fair_cite.py` | new: `judge_citation`, `judge_chapter`, `text_lookup`, `missing_terms` |
| `datasets/battery-pins.json` | new: questions, pins, terms, expected phrases, and the two re-pins with reasons |
| `harnesses/step2-battery.py` | ask mode judges the cited passage, not the pin; pins load from JSON |
| `harnesses/hard-bench.py` | the gold chunk is a note; the cited passage must carry `key_fact` when one exists |
| `harnesses/adrian-eval.py` | chapter check uses `judge_chapter` with the cited passage as the escape |
| `harnesses/crossbook-evil-eval.py` | same escape, using the answer text (HTTP-only, no chunk text) |
| `harnesses/sealed-eval.py` | content is the gate, pin is a note (already); rubric fix for `sealed-def-22` |
| `datasets/sealed-2026-10-24.jsonl` | `sealed-def-22` key fact `input\|number\|output` -> `uniform\|distribut\|hash`; the old one rejected a correct definition ("takes skewed data and makes it uniformly distributed"). New sha256 `7f1dfd6a...` |
| `tests/test_harness_fairness.py` | new: pins must carry their terms; replaced pins must fail their own terms; the judge accepts a different answering passage; source guard against identity gating returning |
| `tests/test_eval_leakage.py` | sealed sha updated |

## 4. Before and after

`old` is the identity rule, `fair` is the rule above. Same machines, same day,
in-process unless noted.

| gate | x3 old | q35 old | x3 fair | q35 fair |
|---|---:|---:|---:|---:|
| battery ask (bar 8) | 8/10, 9/10 | **6/10, 6/10** | 9/10 | **10/10** |
| battery answer | 10/10 | 10/10 | 10/10 | 10/10 |
| hard bench | 59/60 | 59/60 | 59/60 | 59/60 |
| adrian | 31/35 | 31/35 | 31/35 | 31/35 |
| sealed | 27/30 | 25/30 | **28/30** | 25/30 |
| crossbook | 23/30 (2026-10-18) | not run | 24/30 | **26/30** |
| **total** | | | **161/175** | **161/175** |

The candidate no longer fails any gate. The two models tie on the item total and
win in different places: the candidate on ask-mode citation and cross-book
adherence, the incumbent on the sealed unseen set (28 vs 25).

Ask mode flipped from 6/10 to 10/10 because the candidate's citations now count
when the passage answers. The incumbent dropped 8-9 to 9 because on "Where does
storage sit?" it quotes `ch06-001`, which never mentions where storage sits. That
is a real content miss the old pin hid, because `ch06-001` *was* the pin.

## 5. What is still identity-based, and why

- **Explain mode** pins the chunk by design: the model is handed that passage
  and asked to explain it. Citing another chunk is a real failure there.
- **adrian / crossbook chapter turns without `must_contain`**: 66 of 78 chapter
  turns declare no required concepts, so there is no content signal to escape
  with. They stay behavioural. Adding terms to those turns is the next
  improvement; it is authoring work, not a rule change.
- **hard-bench items without `key_fact`** (15 of 60) judge refusal and format
  only. They are adversarial and multi-turn items with no gold chunk, so there is
  nothing to pin.
- **`qa-questions-overnight.json`** remains training-derived and is not a gate
  (see `test_eval_leakage.py`).

## 6. Retired 2026-10-24: the "ET" typo

One typo item was not a typo. `What happens to data after it is extracted in
ET?` assumed "ET" is absent from the book, but it appears 12 times in "et al".
`readings.py` repairs a word only when it is absent, so no repair fired; the
item passed only when retrieval happened to land on a passage containing
`extracted`. It failed 2/2 for the 844-row model while older models passed it by
luck. Retired with that reason in `datasets/battery-pins.json`, replaced by
`What is ingestoin?` (0 of 1,042 chunks, repairs to `ingestion`, passes 2/2 on
both models).

## 7. Verify

```
python -m unittest tests.test_harness_fairness tests.test_eval_leakage
python artifacts/harnesses/step2-battery.py                     # ask, needs :8000
BATTERY_MODE=answer python artifacts/harnesses/step2-battery.py
python artifacts/harnesses/hard-bench.py <model>
ANSWER_MODEL=<model> python artifacts/harnesses/adrian-eval.py --direct
python artifacts/harnesses/sealed-eval.py <model>
python artifacts/harnesses/crossbook-evil-eval.py               # needs :8000
```

Full suite 2026-10-24: 440 tests, 2 failures, both
`test_frontend_rules` against `web/app/study.css` (uncommitted frontend work,
untouched here).
