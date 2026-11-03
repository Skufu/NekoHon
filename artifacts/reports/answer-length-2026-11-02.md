# Answer length — 2026-11-02

Owner ask: a knob for how many words the answer holds, for technical books as
well as fiction.

Two environment variables, both `0` (off) by default so every measured prompt
stays byte-identical:

| variable | aims | default |
|---|---|---|
| `TECHNICAL_ANSWER_WORDS` | a technical answer's gloss | 0 |
| `FICTION_ANSWER_WORDS` | a novel's paragraph | 0 |

The count is the answer's **own prose**: the quoted lines are evidence and are
not part of it. The trace reports what was written (`outcome.answer_words`)
next to what was asked (`query.generation_profile.answer_words`).

## What it took to make the number do anything

First attempt was the obvious one: replace "one line of gloss" with "about N
words of gloss" in the system prompt. On `ddia`, same question, same user turn:

| lever | words written at target 150 |
|---|---|
| system prompt aimed, user turn plain | 19 |
| user turn aimed, system plain | 19 |
| both aimed | 35 |
| both aimed, gloss prompt switched from "1 to 2 sentences" to a paragraph | 63–70 |

So three changes were needed, and each is in the code:

1. The target replaces the length sentence inside the system prompt
   (`prompt.technical_system`, `answer_gloss_system`, `fiction_system`,
   `compare_system`).
2. `prompt.length_hint` adds `Write about N words.` to the user turn — the turn
   the model reads last.
3. `answer_words` forces the gloss pass (`_ensure_answer_gloss`), because with a
   coherent first gloss that pass normally never runs, and above
   `PARAGRAPH_WORDS = 40` the gloss prompt becomes a paragraph prompt: the
   definition-first and list-naming rules are what keep a short gloss correct
   *and* what stops the model writing past one line.

The token cap rises to `max(512, 2 × words)`.

## Measured

`answer.respond`, one run per setting, Ollama on the same machine
(`nekohon_q35_2b_x3_2e`). Each set: three answerable questions plus one the book
cannot answer.

Technical (`ddia`, five passages, temperature 0):

| target | mean words | range | refusals | mean answer time |
|---|---|---|---|---|
| 0 | 26.0 | 25–27 | 1 / 4 | 2.6 s |
| 80 | 36.0 | 29–49 | 1 / 4 | 3.6 s |
| 200 | 56.7 | 44–67 | 1 / 4 | 3.5 s |

Fiction (`Mushoku Tensei` Vol. 25, eight passages, temperature 0.55, two or three
merged rounds):

| target | mean words | range | refusals | mean answer time |
|---|---|---|---|---|
| 0 | 16.0 | 11–19 | 1 / 4 | 6.2 s |
| 80 | 21.7 | 10–31 | 1 / 4 | 7.1 s |
| 240 | 28.7 | 14–44 | 1 / 4 | 11.0 s |

The unanswerable question ("What is the recipe for sourdough bread?") is refused
at every setting in both kinds, so a large target does not buy an invented
answer.

## The ceiling, and what is not done

The target is an aim, not a setting. This fine-tune stops at roughly 65 words of
gloss and about 45 words of fiction paragraph: at target 300 the same gloss
prompt wrote 26 and 64 words on two questions. Reaching 300 would need a model
fine-tuned on long answers, not a longer prompt.

Two mechanical ways to force the count were measured and rejected:

- **Continuation rounds**: append "two more sentences" from the same passage,
  repeat to the target. It reaches 131 words in three rounds, but round 2
  re-states round 1's sentence almost verbatim. That is padding, not
  elaboration.
- **Prefill continuation**: continue the model's own last sentence. Degenerate
  repetition from the first continuation ("A write-ahead log records … to
  ensure consistency after a crash.A write-ahead log records …").

Both are excluded because the engine's job is an answer a reader can trust, and
a repeated sentence is a visible defect. If a longer answer is wanted, the
honest lever is the model: fine-tune on long technical answers (and long prose
for fiction), then the same knob will be honoured.
