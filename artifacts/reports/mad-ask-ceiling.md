# MAD data landscape in ask mode — the textual ceiling (2026-10-13)

Trigger: user's live report. "MAD data landscape" answers with the Ch. 4
pointer sentence ("…that we introduced in Chapter 1 (Figure 4-1)") plus the
gloss "The passage mentions …" ("looks like first person … who even is Matt
Turck"). Reproduced exactly, both phrasings (`probe-mad-quote`).

## What the book has

- "MAD" appears in running text only in ch04-019/020 — the pointer
  paragraph. ch04-020 is a pointer chunk: its remaining sentences are the
  Hive/Presto decline example.
- Ch. 1's treatment of the landscape is the figure figure-1-3 ("Matt
  Turck's Data Landscape in 2012 versus 2021"); the paragraph referencing
  it is ch01-018 ("data tools have proliferated at an astonishing rate …
  modern data stack … interoperation"). It does not say "MAD" or "Turck".
- figure-4-1's caption "Matt Turck's 2021 MAD data landscape" is already
  displayed under the attached image.
- "Who is Matt Turck" is nowhere in the book; the honesty rules forbid
  answering it.

## Experiments — all negative, in-process, qwen2.5:7b, temperature 0

| # | lever | probe | result |
|---|---|---|---|
| 1 | baseline | `probe-mad-quote` | quote = pointer sentence, 2/2 phrasings; gloss describes the passage |
| 2 | + ch01-018 after the lead | `probe-mad-seed` | same quote; one draw dropped the gloss entirely |
| 3 | figure caption as a passage | `probe-mad-caption` | never quoted; caption-first refused "what is MAD data landscape" |
| 4 | gloss-content steer ("never write 'The passage'") | `probe-gloss-steer` + control | meta-gloss unchanged; refused two battery pins (transformations, multicloud) 2/2 draws each; control passes 2/2 both ways |

The model picks the pointer sentence in 4/4 draws: it is the book's only
sentence naming MAD, and verbatim question terms beat explanatory material
that lacks them. The meta-gloss follows from the quote: a pointer has
nothing to gloss.

## Consequence

- No quote-level, pool-level, or prompt-level fix exists for this question
  within the locked design. The prompt-steer family is now 0/4; do not retry
  a prompt shape without a model change.
- "Caption quoting" (post-v1 backlog) as a model-input change: measured
  unhelpful here; the caption already reaches the reader under the figure.
- Remaining levers are product decisions: accept (the quote says where the
  book covers it — Ch. 1, Figure 1-3 — and figure-4-1 attaches), or defer
  to a model swap / scoped multi-hop (slow, optional).

Files: `probe-mad-quote.*`, `probe-mad-seed.*`, `probe-mad-caption.*`,
`probe-gloss-steer.*`, `probe-gloss-steer-control.*`.

## Same-day follow-ups (2026-10-13)

Answer mode, 2 draws per phrasing: "MAD data landscape" -> stable distractor
survey (cites ch03-099, ch02-037, ch11-018; figures figure-3-18, figure-4-1,
figure-11-1). "What is MAD data landscape?" -> stable clean draft (ch04-020
only; figure-4-1). Not draw noise; phrasing-stable.

Prefix rule (`probe-prefix-rule`, `probe-prefix-bare-terms`): a structural
canonicalization — bare phrases (no "?", no wh-word) asked as "What is X?"
before retrieval and prompt (V2):
- fixes the MAD survey -> clean in both modes, 2/2 draws;
- a prompt-only prefix (V1) breaks ask mode (refusal) — the prefix must
  reach retrieval too;
- 6 bare-term controls held (watermark, CRUD, data ingestion, data mesh
  pins in ask; multicloud pin both modes), no new refusals; bare
  out-of-book ("capital of France") still refuses.
Not landed; needs a yes plus battery reruns.
