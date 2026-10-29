# Comparison answers — 2026-10-29

## Problem

A follow-up to `what is an AI agent` — `How does this compare to LLM?` — returned:

```
In Chapter 1. From LLMs to Agents: , AI connects to this topic: From LLMs to Agents: The Foundational Blueprint...
```

The model had written a coherent answer. The generic follow-up post-processor replaced it.
Four causes:

1. `GENERIC_FOLLOWUP_RE` treated `how does this compare to X` as an ordinary in-topic follow-up, so the old chunk stayed pinned.
2. `_extract_query_entities` dropped `LLM` because `"llm"` is a substring of `"llms"` in the heading, leaving only `AI` from the injected `Regarding AI agent:` prefix.
3. The entity check matched `AI` inside the word `paired`, so the template fired.
4. `_advance_followup_quote` selected a chapter-title/subtitle fragment as the quote.

## Fix

- New comparison branch in `respond` (`_comparison_sides` → `_comparison_body`).
  It keeps both sides, adds one retrieval pass for a missing side, quotes the book's
  contrast sentence (`_comparison_quote`), and asks `COMPARE_SYSTEM` for a gloss that
  names both sides.
- If one side is absent, the existing `_half_covered` path states the boundary instead
  of inventing a difference.
- Whole-word entity matching; heading/subtitle glue rejected; the follow-up template
  only runs when no coherent live gloss exists and never overwrites one.
- `Read as:` and `Asked as:` are preserved; comparison citations can be one dual
  sentence or one sentence per side.
- Ask mode keeps the model's citations unless one exact sentence carries both sides
  and a strictly higher contrast score.

## Before / after

The 20-case matrix runs the same questions and flags against the live
`nekohon_q35_2b_x3_2e` in-process.

| Metric | Before | After |
|---|---:|---:|
| 20-case matrix | 9/20 | 20/20 |
| Comparison cases | 3/12 | 12/12 |
| Non-comparison controls | 6/8 | 8/8 |
| Answers containing `connects to this topic` | 2 | 0 |
| Citations starting with a heading fragment | 6 | 0 |

Exact follow-up:

- Before: quote from `ch01-001` starting `From LLMs to Agents: The Foundational Blueprint...`, then the template.
- After: quote from `ch01-002` starting `Unlike a standalone LLM, which is limited to static text generation...`, then `An LLM is a static text generator, whereas an AI agent executes tasks through tools and feedback loops.`

## Variation set

An 18-case extension covers `standalone LLM`, `plain LLM`, `language model`,
`compare with`, `separates from`, `different from`, relational `relate to`,
workflow/tools, DDIA and FDE comparisons, negatives, and non-comparison controls.
Result: **17/18**.

The one failure is `ai-negative-plain-model`: the gloss says a plain model
“executes single queries without autonomous action,” while the cited `ch08-030`
passage only says a plain text response may be insufficient for testing. The
comparison branch checks both sides and coherence, not claim-level grounding.
This needs a separate groundedness gate.

The extension was authored after the fix, so it is an after-only stress set. The
20-case matrix is the before/after.

## Verification

- `python -m unittest discover -s tests` → **694 tests, OK**.
- `python -m unittest tests.test_comparison_regression -v` → **30 tests, OK**.
- Live matrix: `python artifacts/harnesses/comparison-matrix.py --label after`
  (`artifacts/evidence/comparison/`).
- Extension: add
  `--cases artifacts/datasets/comparison-cases-extra-2026-10-29.json`.

The server serves the code it loaded at startup. Restart
`artifacts/runs/start-engine.bat` after changing `answer.py`.

## Residual risk

- Claim-level grounding on a loosely covered side (the one extension failure).
- Relational questions (`compare to a workflow/tools`) get a relation, not a sharp
  contrast; the relation is accepted when both sides are named.
- Ask-mode alignment is conservative by design and may keep a one-sided citation
  when no exact dual sentence beats it.
- A long body line without terminal punctuation can still be mistaken for a
  subtitle; the 80-character cap limits this.
