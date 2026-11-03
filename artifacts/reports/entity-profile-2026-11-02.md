# "Who is X" on a fiction book — 2026-11-02

Owner ask: on the fantasy book, *who is atofe* and *who is rudeus* came back as
one thin, sometimes wrong line. Wanted: a profile, ideally bulleted, built from
what the book actually says.

## What was wrong

Not generation. Retrieval and shape.

`Atofe` appears in **51 chunks across 8 chapters**; `Rudeus` in **65 across 11**.
Dense retrieval has nothing to rank a bare name on, so the window landed on one
scene and the answer described that scene:

| question | before |
|---|---|
| who is atofe | 1 citation · "Atofe was here. The narrator states that Atofe is present at the scene." · 12.3 s |
| who is rudeus | 2 citations · "Rudeus is called the Second North God Kalman by his enemies." (not in the book) · 5.8 s |
| who is sandor | 2 citations · "Sandor is a knight on patrol who is being watched closely by others." · 4.0 s |
| who is eris | 2 citations, both from chapter 8 · "Eris wields a blade that transcends normal combat." · 6.3 s |

## Why the model is not asked to write it

Four prompt shapes, `who is rudeus`, eight evidence chunks, temperature 0.3:

| shape | bullets | passed verification |
|---|---|---|
| bullets with a trailing tag | 5 | 1 |
| tag-first bullets (`- [Ch. N] fact`) | 5 | 1 |
| tag-first, explicit "a bullet without a tag is a mistake" | 0 | — |
| tag-first with a shape example | 0 | — |

The model wrote a wiki entry from its own knowledge — "a character from the epic
fantasy series *The Legend of the Northern God*", "master of the village of
Superd" — and tagged every bullet `[Ch. 1]` whatever passage the fact came from.
A verification pass (bullet's content words ≥ 60 % present in the chapter it
cites) kept 1 of 5.

One summary sentence was tried instead of the whole profile, given four tagged
sentences as context. It wrote **"Master Rudeus is the ruler of the Asura
Kingdom"** from a passage that says the ruler is *close to* him. Word overlap
cannot tell a misread relation from a correct one, so there is no cheap gate.
That line was dropped.

## What ships

`entity.py` builds the profile from the book, and the model is not called:

1. Keep, per chapter, the best sentence that names the person: scored by a title
   or rank next to the name, the name opening the sentence, and length.
2. Skip front/back matter (`section-NNNN`), and skip a chunk adjacent to one
   already used **in the same chapter** — that is the same scene.
3. Emit those sentences as ordinary quote lines, then the titles their own
   sentences use, verbatim.

| question | after | time |
|---|---|---|
| who is atofe | 4 citations (ch 2, 6, 8, 9) + "Known as: Immortal Demon King Atofe; Demon King Atofe." | 14 ms |
| who is sandor | 4 citations (ch 3, 5, 6, 8) + "Known as: North God Sandor." | 15 ms |
| who is eris | 4 citations (ch 3, 4, 6, 7) + "Known as: Sword King Eris." | 14 ms |
| who is rudeus | 4 citations (ch 1, 4, 8, 9), no title line — the book only calls him "Master Rudeus" | 13 ms |
| who is ruijerd | 4 citations (ch 3, 5, 6, 8) | 13 ms |

No model call, so no latency and nothing to invent: the profile is passage text
by construction, and the citation gate, the UI's quote cards and the chapter
chips read it like any other answer.

## Bullets or cards

The body is one tagged quote line per chapter, which the reader UI already
renders as one card per fact with its chapter chip — the same information a
bulleted list would carry, with the evidence visible. Text dashes were not used
because `.answer` renders them and `lib/answer.ts` splits cards from the same
lines; two layouts for one thing is the bug.

## Limits

- The profile is a set of moments, not a biography. It says what the book says
  about the person, in the book's words; it never summarises them.
- `Rudeus` has no "Known as" line: the book addresses him as "Master Rudeus",
  which is an honorific, and honorifics are filtered out. Inventing a role to
  fill the gap is exactly the failure this path exists to avoid.
- Dialogue-heavy sentences are trimmed at the speech boundary; when the name
  only appears after the speech the whole sentence is kept and its quote marks
  are dropped, so a chapter can read as two speakers in one line. It is
  readable, not typographic.
- The path fires only when the name appears in at least two chapters, on a
  fiction book (`bookkind`). A selection stays on the normal path (that is
  about the highlighted passage), and so does asking about the same person
  again inside a thread (that is a follow-up on them). A different person in a
  thread, or an earlier question that was not about a person, starts a new
  subject and gets a profile.
- A scroll position does not block it. The reader UI sends the on-screen
  `chunk_id` with every question, and the first version of this path treated
  that as an anchor, so the profile fired from a bare curl and never from the
  app. `retrieval_context` already ignores such a pin for the same reason;
  measured 2026-11-02 with `chunk_id` set: before the fix 2 citations and a
  one-line gloss, after it 4 citations across chapters 1, 4, 8, 9.

## Tests

`tests/test_entity_profile.py` — 22 tests: question forms (`who is`, `who's`,
`tell me about`, lower-case name), pronouns and concept questions refused, one
sentence per chapter in reading order, front matter excluded, quotes end a
sentence, titles copied verbatim, honorifics dropped, a profile built with zero
model calls, ask mode parity, follow-up stays on the normal path, technical
book never takes it, unknown name answers normally, the app's `chunk_id` does
not block a profile, a new person in a thread still profiles while the same
person asked again does not, and the trace records `shortcut: entity_profile`.
