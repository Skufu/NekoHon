# Two retrieval rules, measured (2026-10-25)

Question from the owner: on DDIA, "what is an api" returned a passing mention of
APIs with a gloss that overstated it. Two candidate fixes:

1. **definition preference** — rank a passage that defines the term above one
   that only mentions it;
2. **margin multi-quote** — when the top two passages are close, quote the
   runner-up too.

Both were implemented behind env flags (`DEF_PREF=1`, `MULTI_QUOTE=1`,
`MULTI_MARGIN=0.02`), default off.

## Rule 1 — definition preference

Model-free probe over 12 "what is X" questions across three books
(`probes/probe-definitions-2026-10-25.py`). Metric: rank of the first passage
where the phrase is followed by is/are/refers to/means/stands for.

| metric | before | after |
| --- | ---: | ---: |
| defining passage at rank 1 | 10/12 | **11/12** |
| improved | — | 1 |
| worsened | — | 0 |

The move is the reported case: DDIA "what is an api", rank 3 → 1.

It also misses definitions phrased with other verbs ("per-tensor quantization
*calculates*…"), so 1 question stays at no-match. That is a detector limit, not
a ranking failure.

Bench effect: hard-mt 12/12 before, 12/12 with the flag. No regression.

## Rule 2 — margin multi-quote

### The margin distribution

Ten standard asks: top1−top2 median **0.031**; four of ten under **0.02**; the
rest 0.028–0.227.

### What it added

Six low-margin definition questions, with the rule on: **4 of 6** got a second
quote. All four were redundant, because a defining passage was already first —
the second quote repeated the definition from another chapter.

Gated rule: skip when any top-5 passage defines the term. Result: **0 of 6**
triggers, which is the correct behaviour.

### Where it fires instead

On the 12-item bench, 11 of 12 are trigger candidates — every elided follow-up
("Why is it risky?", "Put that in plainer words.") has a tiny margin because the
question is short. With the flag on, those answers gain a second quote from a
different passage:

```
Why is it risky?
[Ch. 2] "But it is highly susceptible to outliers"
[Ch. 2] "Per-channel quantization calculates a unique (S,Z) pair for each channel…"
```

The second passage is about a different method. The bench still scores 12/12
because it does not penalise extra citations — which is exactly why the score is
not the evidence here.

### Verdict

**Do not ship rule 2.** It fires on follow-ups, where a second quote is noise,
and it is redundant on definitions, where a definer already exists. The case it
was designed for — a definition question with no defining passage — sits above
the 0.02 margin in this corpus (DDIA API: 0.029).

The trigger could be narrowed to "definition question AND no definer", which
currently matches nothing in the sampled set. That is a reason to keep the flag
for a future corpus, not to enable it now.

## Also delivered

`GET /retrieve?q=…&book_id=…&k=5` returns the ranked passages (score, chunk,
heading, text) without a model call. That is what made this analysis possible
and what a "sources" panel would use.

## Recommendation

| rule | state |
| --- | --- |
| definition preference | keep, default **off**; run on the battery and sealed set before turning it on |
| margin multi-quote | keep behind the flag, **rejected** for the product; revisit only with a corpus where a definition question has no defining passage |

## Evidence

- `evidence/definition-preference-2026-10-25.json`
- `evidence/multiquote-{before,after,after2,after3}-2026-10-25.json`
- `evidence/hard-mt/hard-mt-{baseline,defpref}-2026-10-25.json`
