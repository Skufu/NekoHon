# Overnight QA report — night of 2026-10-13

Doing the loop you do: ask questions the way you ask them, check coherence,
fix what breaks, invent new tests. Everything below is measured; nothing ships
unverified. Live default stayed `qwen2.5:7b`; no downloads; server left up.

## 1. The coherence guard: built, fixed the known cases, failed at scale, reverted

Built from our Codd/MAD thread: a quote must contain the question's rarest book
word; else the tightest anchor sentence replaces it (readings exempt).

- Known cases fixed on granite4.1:3b: "Codd introduced the idea of what" ->
  "Codd introduced the idea of normal forms."; "what is MAD data landscape" ->
  the MAD sentence, stale gloss dropped. qwen2.5's answers unchanged.
- 96 tests green, battery 18/18 with it; committed (d3981cf).
- Then the at-scale audit — all 303 sweep questions replayed, every swap
  captured before/after (`guard-audit.json`): 21 swaps, **2 saves, ~19
  misfires.** Saves: "what is denormalization" was being answered with the
  normalization definition; "togaf defines data architecture as what" lost its
  subject. Misfires: the word-picker can't tell a subject from vocabulary
  ("hood", "afternoon", "achievable") — worst: "under the hood, batch
  processing is what" replaced a real answer with "You still need to understand
  what's going on under the hood."
- Verdict: **reverted the same night** (battery re-verified PASS on the
  reverted tree). It will not come back until it has a subject-word
  discriminator — the open-class problem `keywords.py` already warns about,
  not a bigger constant.

## 2. Question sweep (your test style, at scale): 303 asks

Set: 124 authored questions in your styles (bare / what-is / quiz / list /
subject-first, with typos; `qa-questions-overnight.json`, from a subagent),
plus what-is asks for the 120 rarest book words and 60 headings. Runner:
`qa-sweep.py`; results `qa-sweep-default.{json,log}`.

Headline: **223 answered / 80 refused; of the answered, 30 flagged incoherent
(mostly guard word-picker artifacts) and 179 had no gloss line (the known
qwen2.5 behavior).**

Triage of the 80 refusals (`refusal-classes.json`, `refusal-split.json`, raw
completions captured in-process):

- **58 are correct refusals** — the sweep asked junk ("what is aashish",
  "what is abandon"); refusing name-words and stray vocabulary is right.
  Sweep-design lesson: ask about topics, not every rare word.
- **~14 are mechanical discards of correct model answers** (the real finding):
  - 9x short-but-complete quotes killed by the 40-char floor: "Everything
    fails, all the time." (30 chars), "Metadata is data about data." (27),
    "Hot, warm, and cold data" (24).
  - 3x answers without the `[Ch.` tag: "Normalization is a database data
    modeling practice..." — verbatim book text, discarded on format.
  - 1x typographic mismatch: the book's curly quotes (“data about data,”) vs
    the model's straight quotes break the match.
  - 1x unmatched.

## 3. Proposals (each small, each needs its own tests + battery rerun; none shipped)

1. **Short complete-sentence quotes**: accept a quote under 40 chars when it is
   sentence-shaped (uppercase start, terminal punctuation, >= ~20 chars) and
   matches the passage. Fixes the 9.
2. **Tagless verified answers**: when the reply has no `[Ch.` tag, run the same
   verification (whole text verbatim in a shown passage, else the >= 40-char
   span) and rebuild the tag from the matched passage; refuse only if nothing
   verifies. Output contract unchanged — unchecked prose is still a refusal.
   Fixes the 3.
3. **Typographic folding in the match**: normalize curly quotes/typography in
   `_quote_in_passage` and the span fallback. Fixes the 1 (and any book with
   smart quotes).
4. **Refusal rescue** (bigger): the multicloud probe refuses on cold runs
   (5 recorded occurrences, 4 today, every one on a first cold run; warm reruns
   always clear), and 8 sweep refusals had the evidence word shown. One re-ask
   when the model refuses but the shown set plainly holds the question's word
   would target both. Needs design + frozen-rule rerun.
5. Retrieval gaps for the RRF side: "acquisitions", "anthos", "actors" — the
   word exists in the book but never reaches the shown set.

## 4. Housekeeping

- Guard evidence kept: `coherence-guard-evidence.txt`, `cru-postguard.txt`,
  `step2-battery-postguard.*`, `guard-audit.*`.
- The RRF side's late battery run is still untracked (`step2-battery-rrf-late.*`).
- 91 tests green; battery green on the reverted tree (warm run).
- Server up on :8000 with the default model on the current code.

Post-report addendum: all three proposals shipped 2026-10-13 — `eb598e1`
(short complete-sentence quotes), `92e11ad` (tagless verified replies),
`85f4d80` (typographic folding). Retests and battery in
`refusal-fixes-evidence.txt` and `step2-battery-refusal-fixes.*`. The sweep's
"hot warm cold data" case stays refused by design (the model quotes only the
heading, and a bare heading is not an answer); IOPS stays a retrieval item.
