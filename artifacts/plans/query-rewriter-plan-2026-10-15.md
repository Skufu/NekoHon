e# Query rewriter — intent-aware asking (2026-10-15)

Status: layer 0 landed 2026-10-15 (owner: go fix the open items). Layer 1 still waits on decisions B–D and the mini bake-off.

Trigger: owner findings 2026-10-15 — `Monolith Versus Modular` was asked as
`What is Monolith Versus Modular?` (wrong question form for a comparison);
typo'd, sentence-shaped input (`Dataa analysts seek to undertstand what
business performance`) has no repair path beyond the reading gates; vague
input is rewritten nowhere.

## Gap

`canonical.py` is structural only: a bare phrase gets `What is X?`. It cannot
tell a comparison from a definition, a list ask from a topic question, or a
vague request from a typo. Retrieval searches the wrong string and the model
is asked the wrong question.

## Design (two layers, cheapest first)

**Layer 0 — deterministic rules in `canonical.py`** (stdlib, no model, lands
first):

- `X vs Y` / `X versus Y` -> `What is the difference between X and Y?`
  (the monolith finding).
- list asks (`what are the factors/parts/kinds/steps of X`) are recognized
  as list asks — this drives the answer-shape rule below.

The original input is kept; the disclosure stays `Asked as:`.

**Layer 1 — LLM intent rewrite (local only, gated)**:

- One call maps messy input to two fields: `canonical` (the question asked)
  and `query` (the retrieval string, keyword-rich).
- Precedent and gate idiom: the spelling enhancer (`prompt.SPELL_SYSTEM`,
  `readings.llm_second_reading`) — the model proposes, a strict-improvement
  gate decides, every change is visible (`Asked as:` / `Read as:`). A rewrite
  is accepted only when retrieval strictly improves under the existing
  rare-word guard; otherwise the structural form stands.
- The rewrite may not import world knowledge (no outside facts): its job is
  normalizing the ask into the book's own vocabulary for search, not
  answering.
- Rewriter model is a tactic: candidates on disk are `granite4.1:3b` (small,
  dedicated) or the answerer itself; mini bake-off before adoption; env seam
  like `ANSWER_MODEL`. The engine stays local-only (constitution).

**Answer-shape rule (list asks)**: when the question is a list ask
("what are the factors…"), the answer must carry the list items, not the
lead-in sentence — the `incomplete-list` defect in the answer-quality plan.

## Pre-registered bar (before any adoption)

- battery both modes stays green; sealed suite >= standing bar, no drop vs
  x2d; owner probe >= previous PASS.
- The three owner findings, re-measured: monolith -> comparison form; OSS
  list -> lists the factors; the typo'd ask -> answered (or an honest
  refusal if truly absent), never blank.
- Disclosure exactness tests; latency budget: +<= 1 s warm for layer 1.

## Open decisions (owner)

- **A.** Land layer 0 now (deterministic `vs` + list rules, tested in
  `tests/test_canonical.py`) while layer 1 waits on the mini bake-off?
- **B.** Disclosure wording: reuse `Asked as:` (recommended) or add a
  distinct `Searched as:` for the retrieval string?
- **C.** Rewriter budget: run layer 1 only when the structural form looks
  bare/vague (recommended), or on every ask?
- **D.** Gate definition for "strictly improves retrieval": rare-word guard
  plus gold-rank non-regression on the labeled set (recommended)?
