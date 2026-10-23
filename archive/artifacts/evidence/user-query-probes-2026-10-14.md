# User query probes — six raw single runs (2026-10-14)

Record of six queries the project owner ran by hand on the live app (answer
mode, window default), interpreted against the engine contract in `answer.py`,
`canonical.py`, `retrieve.py`, `readings.py`, `prompt.py`, `server.py`.

**These are single manual runs, not controlled probes — no rate may be read
from them.** The identical ten-query set has a controlled repro through the
answer seam: `artifacts/evidence/probe-trial-queries/probe-trial-queries-2026-10-14.{json,log}`
(both models, temperature 0, one draw each), discussed in
`artifacts/reports/x2-trial-2026-10-14.md` and `artifacts/reports/engine-edges-2026-10-14.md`.
Where the owner's paste and that record agree, both are cited. Labels:
**[M]** = measured (recorded in the repo's artifacts, or the owner's stated
observation); **[I]** = inferred (code-path reading, recommendation).

Default under test: `prompt.py:49` — `ANSWER_MODEL` defaults to the finetuned
`smallbook_x2` (env override `ANSWER_MODEL=qwen2.5:7b`); the window defaults to
`answer` mode (free generation, citation = the model's own `[Ch. N]` tags;
groundedness is measured, not enforced — `answer.py:546-575`). [M: source]

## The six runs

| # | query | observed (single hand run) | recorded repro, x2 | expected per engine contract | verdict (mine) | verdict (owner) |
|---|---|---|---|---|---|---|
| 1 | `what is` | answered with the query definition, cited `[Ch. 8]` | answered, `cited=[]` [M] | none defined — no degenerate-input rule exists today; per the proposal below: refuse before generation | **WRONG** — degenerate input, answer is an arbitrary passage [I] | WRONG |
| 2 | `hey` | answered with an RDBMS definition citing `[Ch. 5]`, plus `Read as: "they"` | answered, `cited=[ch05-030]`, same text + `Read as: "they"` [M] | mechanics: contract-conform (the `Read as` line is by design); product intent: a greeting is not a book question — the 7B refuses, correctly | **WRONG** — engine over-repair `hey→they` (repair target is a stopword) [I] | unlabeled |
| 3 | `warrup` | `Not in this book.` | refused, misses `ch05-053 ch05-030 app01-017` [M] | refusal — junk token, no in-book reading | **CORRECT** — matches both models [M/I] | unlabeled |
| 4 | `Location` | `Not in this book.`, "nearest misses: ch07-046 app02-005 ch03-071" | refused, same three misses [M] | answer from `ch07-046` (the passage exists; the 7B answers from it) | **WRONG** — false refusal; the right chunk is itself in the misses [M/I] | WRONG |
| 5 | `Our Advice` | answered with a CIO / data-culture definition | answered, `cited=[]` (no `[Ch. N]` tags in the text) [M] | no rule for section titles; prose without tags is kept (not refused) by `parse_answered` | **WEAK — WRONG** (subject drift, untagged); genuinely new class [I] | unlabeled |
| 6 | `DE Lifecycle` | nothing in the owner's paste | refused, misses `ch02-004 preface01-003 ch01-006` + figure note "nearby, not an answer" [M] | answer from ch02 (the 7B answers the full five-stage definition) | **WRONG** per the record — false refusal; the empty paste itself is not evidence [M/I] | unlabeled |

Note on row 1: the owner's paste cited `[Ch. 8]`; the recorded repro run cited
nothing and worded its second sentence differently. Single temperature-0 runs
vary in their tags (same warning as `engine-edges-2026-10-14.md`, Uncertainty).
[M]

## Why — the code paths

1. **`what is`** — `canonical.py:48` passes any text containing a WH word
   through unchanged; both tokens are stopwords so nothing is left to search on,
   but retrieval has no relevance floor: `retrieval_context` returns the top-5
   (`PASSAGE_LIMIT = 5`, `answer.py:25`) and the model decides. Measured top
   passage 0.7405, a high cosine with no meaning (`engine-edges` case c). [M/I]
2. **`hey`** — opener → canonical unchanged (`canonical.py:27-31,50-51`); `hey`
   is not in the book (df=0) so `_fixes` considers it; difflib `hey→they`
   scores 0.8571 (runner-up `he` 0.8000) ≥ `CUTOFF = 0.85` (`readings.py:55`),
   and the strict-improvement gate keeps it (`they` chunk 0.6022 vs literal
   0.5617, +0.0405). `they` is a SMART stopword (vendor list) — a function
   word, not a topic. `Read as:` is printed after generation
   (`answer.py:573`) and cannot suppress the answer. [M/I]
3. **`warrup` / `Location` / `DE Lifecycle` refusals** — `_refusal`
   (`answer.py:453-467`) attaches the top-3 passages as citations; the window
   renders their ids as "nearest misses:" (`window/index.html:64-66`). For
   `Location` the #1 miss is the exact chunk the 7B answers from — retrieval
   was fine; the refusal decision was the model's. `DE Lifecycle` adds the
   refusal figure note ("nearby, not an answer", `index.html:69-74`). [M/I]
4. **`Our Advice`** — `our` is in `PRONOUNS` (`canonical.py:32,52-53`), so the
   bare-fragment trigger does not fire; the literal string retrieves advice
   sections and x2 wrote an untagged CIO definition. Citations come only from
   `[Ch. N]`-tagged sentences (`parse_answered`, tags matched to shown
   passages); untagged prose is kept, not refused — hence `cited=[]`. [M/I]

## Wart classes vs the x2 trial, and x2c coverage

- **Bare fragments (known class):** `Location`, `DE Lifecycle` — canonical
  fires on both; the trial report files them as model warts, "same disease as
  CRU/Codd: the decision margin sits a hair from refusal on any form not
  memorized exactly" [M].
- **Oral/lowercase acronym forms:** none of the six (the session's
  `DDR5 vs ddr4` / `ddr4 vs ddr5` flip pair is the other known class and is
  not among these six). `warrup` is not an acronym; `DE Lifecycle` is an
  abbreviation the report classes as a bare topic. [M/I]
- **Genuinely new:** `what is` (degenerate), `hey` (greeting → repair to a
  stopword), `Our Advice` (pronoun-guarded section title). `warrup` is not a
  wart — both models refuse, which is right. [M/I]
- **x2c swaps** (`artifacts/probes/build-finetune-data-2026-10-13.py:112-165`;
  not yet trained [M]): (a) 10 casing/acronym swaps, (b) 10 order flips,
  (c) 10 bare topics. **No one of the six query strings appears in the swap
  dict.** `Location`/`DE Lifecycle` get class-level coverage only ((c) trains
  the bare-fragment behavior on ten other strings, counts and ratio held); they
  remain visible acceptance targets in the pre-registered gate
  (`x2-trial-2026-10-14.md` §Pre-registered swap gate — the visible ten are
  NOT the sealed suite). `what is`, `hey`, `Our Advice`, `warrup`: no x2c
  coverage; the first two are engine-guard items. [I]
- (b)'s flip list contains no `ddr4/ddr5` pair, and (a) contains no greeting —
  state this when the x2c result is judged. [M/I]

## Degenerate queries — there is no contract today; recommendation

Today a zero-content fragment (`what is`) or a greeting (`hey`) reaches
retrieval and the model with no defined behavior; the outcome is whatever the
model decides (`engine-edges` case c says "return the refusal or an
echo-clarification" was *proposed*, never shipped). Recommended engine rules,
all pre-generation, no model call: [I]

- **R1** — after canonicalization, if no content word survives stopword
  removal, return the frozen refusal (`Not in this book.`) before retrieval.
  Measured on the proposal: fires on `what is` only, not on `hey` or the
  fixture questions (`engine-edges` case c table). [M for the probe]
- **R2** — a reading repair may never rewrite *to* a stopword target. Blocks
  `hey→they`; keeps `CRU→CRUD` and `atermark→watermark`. [I]
- **R3** — with R1+R2, if no content word of the asked form occurs in the book
  (df>0 or repaired), refuse before generation; this makes `warrup`'s correct
  outcome deterministic instead of model-dependent. [I]

Keep the wire shape frozen (`refused: true`, exact sentence; `server.py:110-125`
unchanged) and keep "nearest misses". An "ask a fuller question" hint belongs
in the window, not in the `/ask` contract. [I]

Scope: read-only investigation; no engine file changed, nothing run live.
Placed under `evidence/` per the request (the repo's dated-findings zone is
`reports/`); no `artifacts/README.md` index row was added — this request froze
the deliverable to one file.
