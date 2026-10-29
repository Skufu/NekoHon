# Trace-derived interaction regression set — 2026-10-29

Source: `artifacts/runs/traces.jsonl` (52 live traces, 2026-10-29 07:43–09:56
UTC, all `status: ok`; 49 on `nekohon_q35_2b_x3_2e`, 2 retrieve-only with no
model, 1 on `qwen2.5:7b`). Dataset:
`artifacts/datasets/trace-interaction-2026-10-29.jsonl`. Every question below
is the reader's wording from the trace; no question was rewritten.

The traces are claims, not evidence. Only the book indexes were trusted for
gold text. No engine restart, no provider calls, no `*.py` edits; every Python
run used `OBSERVE=0`.

## Dataset

12 items: 9 answered, 3 refused. Fields are exactly `id`,
`source_trace_id`, `book_id`, `turns`, `gold_chunk_ids`, `must_include_terms`,
`expect`, `why`.

| id | book | turns | gold chunk | expect | state in source trace | what it locks |
| --- | --- | --- | --- | --- | --- | --- |
| `fde-early-2000s-repeat` | fde | 4 | `ch01-010` | answered | gold absent; cited `ch01-025` (data maturity) | The repeated early-2000s follow-up: the pin drifted with the previous answer (`preface01-007` → `preface01-017` → `ch01-025`) and the dot-com passage was never retrieved. |
| `fde-watermark-examples` | fde | 2 | `ch08-039` | answered | refused (`Not in this book.`, 17 chars) | The examples follow-up after a successful watermark turn; the book's late-arriving-data case was in the shown passage. |
| `qz-quantization-plain` | quantization | 1 | `chapter-1-003` | answered | answered, zero citations | Plain-register grounding: the "simple words" answer paraphrased with no citation at all. |
| `qz-quantization-examples` | quantization | 2 | `chapter-2-006` | answered | cited `chapter-1-003`; walkthrough was rank 1 in shown | Example advancement: the follow-up re-quoted the definition instead of the 1.5 walkthrough. |
| `ag-fsm-examples` | ai-agents | 1 | `ch01-013` | answered | cited `ch01-013`, quoted a transition-detail sentence | Example answers: the model glossed the definition and never used the blog-post state example. |
| `ag-fsm-examples-followup` | ai-agents | 2 | `ch01-013` | answered | cited `ch01-012` (definition) | History carry for examples: the follow-up stayed on the definition chunk. |
| `fde-storage-position` | fde | 1 | `ch06-001` | answered | cited `ch02-002`; gold shown at rank 3 | The storage-role pin: it cited the five-stage list instead of the sentence that says where storage sits. |
| `fde-multicloud-disadvantages` | fde | 1 | `ch04-037` | answered | cited `ch04-037`, quoted only the lead-in | List answers: the disadvantages question never reached the egress-cost/complexity list. |
| `fde-insert-only-utility` | fde | 1 | `ch08-107` | answered | cited `ch08-107`, glossed "auditing" | "When is X useful" grounding: the gloss invented a use case and skipped the book's current-view use. |
| `fde-refuse-sourdough` | fde | 1 | none | refused | refused, exact 17 chars | Negative control: a baking question must stay out of the book. |
| `fde-refuse-france` | fde | 1 | none | refused | refused, exact 17 chars | Negative control: the canonical out-of-book question. |
| `ag-refuse-single-node` | ai-agents | 1 | none | refused | refused, exact 17 chars | Negative control: a single-node-vs-distributed-databases claim must not transfer between books. |

The intended suite check is: `expect` matches the outcome; every
`gold_chunk_ids` entry appears in `shown_passages` or `citations`; every
`must_include_terms` entry appears (case-insensitive) in the final answer text
(quote plus gloss); a refusal is exactly `Not in this book.`. Under that
check the source traces score **3/12**: all three refusal controls pass, all
nine answered items fail. Under a reading that drops only the answer-text term
check (gold in `shown_passages` or `citations`, `expect` still enforced) 2 of
12 fail — the early-2000s item (gold never retrieved) and the watermark item
(refused).

## Verification run

`data/index.json` is the `fde` index only, so each item was verified against
its own book's `index_path` from `data/books.json`:

- `fde` → `data/index.json`, 1,042 chunks (34 traces)
- `quantization` → `data/index.quantization.json`, 473 chunks (5 traces)
- `ai-agents…` → `data/index.ai-agents_…-anna-s-archive.json`, 637 chunks
  (13 traces; `book_id` is the full catalog slug, copied from `data/books.json`,
  not retyped by hand)

For each of the 9 answered items the gold chunk id was looked up in that index
and every term was checked as a literal, lowercased substring of the chunk
`text`, with the match offset printed. Result: **9/9 gold chunks exist, 17/17
terms found verbatim, 0 misses.** Terms were then re-checked against the
source trace's `answer_preview` to record today's state: **0/17 term hits
across the 9 answered items.** Where the answer quoted at all, it quoted a
sentence that did not carry the asked-for content (the definition instead of
the example, the lead-in instead of the list); one answer
(`qz-quantization-plain`) carried no citation at all.

The exact gold check (re-runnable, read-only):

```bash
cd /Users/adriangabriellfrancisco/workspace/github.com/Skufu/ask-this-book
OBSERVE=0 python3 - <<'PY'
import json
books={b['book_id']:b for b in json.load(open('data/books.json'))}
idx={b:{c['chunk_id']:c for c in json.load(open(v['index_path']))['chunks']} for b,v in books.items()}
for line in open('artifacts/datasets/trace-interaction-2026-10-29.jsonl'):
    it=json.loads(line); ch=idx[it['book_id']]
    for g in it['gold_chunk_ids']:
        assert g in ch, (it['id'],g)
        for t in it['must_include_terms']:
            assert t==t.lower() and t in ch[g]['text'].lower(), (it['id'],g,t)
print('gold chunks and terms verified')
PY
```

Refusal evidence (same index scan, lowercased chunk text): `fde` contains
`sourdough` 0 times, `france` 0, `capital of france` 0; the ai-agents book
contains `single-node` 0, `distributed cluster` 0, `distributed clusters` 0,
`replication` 0, `single node` 0. The three negative controls are genuinely
out of book, not merely missed by retrieval.

Trace-side corroboration: every `source_trace_id` exists in the 52-line log;
each refusal trace reports `answer_chars: 17` and `final_refused: true`; the
four-turn early-2000s chain matches the `history_preview` chain across
`83787ac87d54` → `a347b2ee4293` → `d38bcbb6e523`/`879b5033eedd`.
`248e2fb886c4` predates `history_preview`; its first turn was taken from its
resolved question (`Regarding finite state machines in simple words: …`) and
the twin trace `15dbd46fd234`, which carries the same history explicitly.

## Excluded candidates

- **Wrong-model trace.** `1c3b55d2c030` ran `qwen2.5:7b`, not the shipping
  default; its question is a duplicate of `4f868ef97772` (which passed on the
  default), so nothing was derived from it.
- **No answer produced.** `e444a3a99672` and `8263372dd453` are
  `retrieve`-mode traces (blank model, no answer); they cannot express an
  interaction.
- **Reader selections and fragments, not questions.** `1ed0987c3450`,
  `fb8a1aaf4afc`, `af8c8afdc56e`, `2a3e200a4678`, `d55e117a4e80`, `680f67be33c1`
  are `explain` calls on a highlighted span, fragment completions ("simple
  words", "Discrete states?"), or one-word asks ("Python"); `explain` has its
  own contract and a fragment is not a whole reader question.
- **Known ceiling, not a regression.** `5859ccdc72bb` and `7ea12ce97f18`
  ("MAD data landscape"). The fde prose names MAD once, in the pointer
  sentence (`ch04-020`); the Ch. 1 treatment is a figure. A must-pass item
  would demand a passage the book does not have (recorded 2026-10-13,
  `reports/mad-ask-ceiling.md`).
- **Same conversation, folded in.** `83787ac87d54`, `a347b2ee4293` and
  `d38bcbb6e523` are earlier turns of `879b5033eedd`; making them separate
  rows would score one conversation four times.
- **Same failure class, already represented.** `0e918e4efcff`,
  `dfd0eb69f01d` and `8a9eea081ffa` are three draws of the FSM "simple words"
  question with zero citations; the plain-register citation defect is kept
  once, on the quantization trace, to avoid duplicating a book/model/transform
  triple. `15dbd46fd234` and `cf6cf0d0af9e` are the FSM examples follow-up on
  a different draw and *passed* (cited `ch01-013` with the blog-post example);
  they are evidence the item is achievable and are not separate rows.
- **Passed, or defect not expressible here.** These answered with the right
  chunk and are already pinned in the battery/demo set: `4f868ef97772`
  (five stages), `7c803bdc4b67`/`accb0ff95d47` (CRUD/CRU), `543544c9ea81`/
  `e2289e1eb7e7` (ingestion), `56f6888a31cc`/`8f51e7e6fd16` (watermark),
  `628402c7e4f2` (atermark), `4133c2dd071e`/`e84d13f35325` (pragmatic),
  `9bdb8e8862e9` (Codd), `b41a5f3517d7` (data mesh), `9aad5d1db530`
  (endpoint), `9296afed39fc` (ETL), `0be846700cfc` (transformations),
  `42c10468d8a7` (source systems), `5a9dbeb245d5` (LLM vs agents).
  `fc9936b50507` quoted a transition sentence but cited `ch03-013`, which
  carries "Data architecture is a subset of enterprise architecture"; the
  defect is sentence choice inside a correct chunk. `f3aa361c23a0` quoted one
  side of batch-vs-streaming; comparisons are already regression-covered by
  `tests/test_comparison_regression.py` and the 2026-10-29 comparison report.

## What the traces say about interaction quality

1. **Refusal precision is intact; the boundary fails on follow-ups.** Three
   of four refusals are correct (sourdough, France, single-node databases).
   The only false refusal is `can you give examples?` immediately after a
   successful watermark answer — the pipeline refused with the right passage
   already in the shown set.
2. **Follow-up state is the weak layer.** All four follow-up items failed,
   and the early-2000s chain shows the mechanism: the pin follows the previous
   answer's chunk (`preface01-007` → `preface01-017` → `ch01-025`) until the
   reader's same question is answered with data maturity. Four of the nine
   answered failures are follow-ups, not standalone questions.
3. **The dominant answer defect is quote choice, not retrieval.** In 8 of the
   9 answered-expectation items the gold chunk was already in
   `shown_passages`; the only retrieval miss is the early-2000s chain. The
   model finds the passage and then quotes the wrong sentence in it — or, in
   plain register, drops the citation the register still owes.

## Limits

- The dataset schema guarantees `must_include_terms` are verbatim in a gold
  chunk; it does not itself say the runtime check is on the answer. This
  report defines that check explicitly above so a consumer cannot quietly
  choose the weaker shown-or-cited reading.
- `data/index.json` is only the fde index; the quantization and ai-agents
  items were verified against their own `index_path` entries. Any future
  checker that hardcodes `data/index.json` will silently skip 5 of 12 items.
- The trace log is a 2026-10-29 battery/comparison session, not a random
  sample: 49 of 52 traces are one model, and 41 of 52 are `answer` mode.
  These items lock observed failures; they do not estimate a failure rate.

## Baseline — measured 2026-10-29

Harness: `artifacts/harnesses/trace-regression.py` (in-process, real answer
path, turns run in order with the real history of the turns before them; only
the last turn is graded). Command:

    OBSERVE=0 python3 artifacts/harnesses/trace-regression.py

Model `nekohon_q35_2b_x3_2e`. Result: **4 of 12 pass, 8 fail** (evidence:
`runs/trace-regression-2026-10-29.json`, gitignored).

| item | result | reason |
| --- | --- | --- |
| `fde-early-2000s-repeat` | fail | cited `ch11-022`, not `ch01-010`; no asked-for term |
| `fde-watermark-examples` | fail | refused a covered follow-up |
| `qz-quantization-plain` | fail | no citation |
| `qz-quantization-examples` | fail | re-quoted the definition (`chapter-1-003`), not the walkthrough (`chapter-2-006`) |
| `ag-fsm-examples` | fail | cited the right chunk but quoted a transition sentence, no example states |
| `ag-fsm-examples-followup` | pass | cited `ch01-013` with the example |
| `fde-storage-position` | fail | cited `ch02-002`, not the storage sentence |
| `fde-multicloud-disadvantages` | fail | quoted only the lead-in sentence, no list |
| `fde-insert-only-utility` | fail | gloss invents an auditing use the book does not give |
| `fde-refuse-sourdough` | pass | exact refusal |
| `fde-refuse-france` | pass | exact refusal |
| `ag-refuse-single-node` | pass | exact refusal |

The three negative controls pass, so the suite cannot be cleared by answering
everything. All eight failures reproduce defects seen in the traces; none is a
grading artefact — every gold term was re-checked verbatim in its chunk.
