# Owner pattern — what the owner likes and dislikes (2026-10-15)

Mined, not invented: every line cites the record that shows it. This is the
brief for the persona rater — the owner delegated the sample-rating seat
2026-10-15 ("not my forte"); the owner overrides any row at any time.

Sources: `evidence/user-query-probes-2026-10-14.md` (owner verdicts column),
`reports/query-coverage-gaps-2026-10-14.md` (owner query surface, false
refusals), `datasets/training-list-2026-10-14.md`, `reports/x2e-verdict-2026-10-15.md`,
`datasets/owner-rated-2026-10-15.jsonl` (owner findings, 2026-10-15).

## Dislikes — failures the owner called out

- **False refusals when the book has the material.** `Location` (owner:
  "WRONG — the right chunk is itself in the misses"), `DE Lifecycle`,
  `ddr4 vs ddr5` (answered-but-uncited 2026-10-14, refused 2026-10-15),
  `why's kafka so popular?` (book has Kafka material, ch03-086; recorded
  teacher ceiling).
- **Answers that drift off the asked subject.** `Our Advice` (CIO culture
  definition — owner: "WEAK — WRONG"); `Location` answered from streaming
  regions instead of the term.
- **Degenerate input answered instead of refused.** `what is` (owner:
  WRONG); whitespace-only input returning an arbitrary quote; greeting
  over-repair (`hey` -> `they`).
- **Wrong question shape.** "versus" asked as "What is X versus Y?"
  (owner 2026-10-15: "that's not a correct way to do it").
- **List questions answered with the lead-in sentence, not the list.**
  Community-managed OSS factors finding, 2026-10-15.
- **Blank panes.** Two (micro-partitioning; the typo'd "Dataa…" ask) —
  always bad, regardless of the answer content underneath.
- **Fragment or headless quotes.** Snowflake's quote missing its subject;
  OLAP's subordinate clause; "It's hard." openings (MAD).

## Likes — choices the record shows

- Quote-first with a citation the reader can check; every quoted word from
  the book (GOAL's reader standard).
- Right shape for the question: definition for "what is X", a list for
  "what are X", a comparison for "X vs Y".
- Visible repairs: `Read as:` for typos (atermark), `Asked as:`
  disclosures kept.
- Honest refusal when the material is truly absent (France control stays
  exact).
- Concision: one-line plain gloss, no filler, no recitation, no duplicated
  sentences.

## What "not standard" meant (owner's words, 2026-10-15)

"Sometimes when we answer things, it's not standard." The standard the
record supports: right shape, complete (the book's own material preferred
over its thinnest line), grounded, cited, no fragments, no filler.
