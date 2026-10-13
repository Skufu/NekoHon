# Query phrasing sensitivity and the "?" flip (2026-10-13)

Trigger: user's live report — "What is nonrelational database" answered from
ch05-032's paragraph; adding one "?" changed the shown quote to ch05-034's
"NoSQL remains vague in 2022" sentence.

## The flip is model-side, not retrieval

`probe-nonrelational-ask`: the pool is the same both ways (ch05-032 leads at
0.7786 vs 0.7864; order identical). A one-character prompt change moved the
model's quote choice at temperature 0 — the documented temp-0
nondeterminism class, not a ranking failure.

## Battery sweep: strip trailing "?.!" (`probe-query-normalize`, 23 × 2)

- quote text changed in 4/23 asks;
- pin flips 2/23, in opposite directions: transformations `?` loses its pin
  (ch02-027 -> ch02-025); nonrelational `?` gains it (ch05-034 -> ch05-032);
- multicloud flaked (refused both variants; known flake — it passed 2/2 in
  a control run minutes earlier);
- France refusal intact.

Net: blanket punctuation normalization is not a correctness fix — it moves
coin flips around, one for one. It buys consistency (one behavior per ask),
and only that.

## The book's link graph (`probe-epub-links`)

The EPUB carries the links the user remembers: the MAD pointer sentence
holds an internal xref to `ch01.html#data_engineering_described` and to the
figure-4-1 anchor; the caption links out to the live landscape. 2,900
`<a href>` / 2,621 anchors over 25 content files. The index keeps no
chunk-level links (figures keep `anchor` / `referencing_paragraph`).

A link channel (ingest internal xref targets, one deterministic hop, fuse as
a third ranked list beside dense and lexical) is a real candidate for
questions where the link target holds the definition. It would NOT have
changed the MAD answer: its hop targets (ch01's intro, ch01-018) were tested
and the model ignored them (`mad-ask-ceiling.md`).

## Verdicts

1. Do not add query-normalization rules; net 0 on pins, and per-question
   rewrites would be fitting the test set (hard-rule violation).
2. The deterministic-selection pattern that fixed answer mode
   (`_evidence_quote` by overlap) is the architectural answer to "one
   character changes everything" in ask mode too — but ask mode's quote is
   the model's by contract; that is a mode redesign and needs a yes.
3. Finetune: the recorded direction (quote-or-refuse, ~2.5GB class; the
   search was done and its brief was deleted 2026-10-13); wrong-passage-
   choice-with-right-present is explicitly its quote-selection target
   (`mad-phrasing-probe.md`).
4. Link channel: backlog-probe candidate; not a MAD fix.

Files: `probe-nonrelational-ask.*`, `probe-query-normalize.*`,
`probe-epub-links.log`.
