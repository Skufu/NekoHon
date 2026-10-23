# Gloss and craft references

Design research the reader UI draws on. Implementation: `web/README.md`.

## Gloss (github.com/Nutlope/gloss, main @ 54b13b8) — copy / skip

COPY:

- The anchor model `{start:{b,o}, end:{b,o}, quote}` + `spanIn`/`segments()`
  mark splitting — offsets over plain block text survive marks, fonts, themes.
  (Implemented in `web/lib/anchor.ts` as character offsets over block text.)
- `Margin.compute`/`place`: document-relative geometry; the active card pinned
  at its anchor, others pushed forward/pulled back; 16 px gaps (4 px between
  mini cards); passages starting within 88 px collapse to mini; SVG bezier
  leader line + dot in the gutter; below 1080 px the active gloss becomes a
  bottom sheet.
- `Cite` + `Peek`: hover/focus previews the passage (220 ms debounce, up to 6
  clamped lines); click → smooth scroll to 28% viewport + a 1.9 s flash;
  unknown ids render disabled, not dead.
- `Lens`: the selection toolbar (fixed, clamped 12 px from edges, arrow aimed
  at the text); "just type" capture — the first printable key goes straight
  into the ask box; Enter opens an empty ask box; docked at the bottom on
  coarse pointers.
- `ask.ts` loop: `res.body.getReader()` + TextDecoder, frames split on `\n\n`,
  tokens batched per requestAnimationFrame, one AbortController per card; abort
  with content is silent, without content reads "Stopped.".
- `GlossCard` states: collapsed gist, fresh-placement (no transition until the
  top is known — no slide-from-top on load), streaming skeleton, stop/retry/
  copy/delete, follow-up thread.

SKIP: Clerk/accounts/quota/keys; web search + `[1]` sources; sync/Postgres;
importers (readability/PDF); `docPayload` windowing; Brief/Notebook/Listen;
usage/cost receipts; the model allow-list.

Gloss has **no Vercel AI SDK** — its server route streams raw SSE from a
`ReadableStream`. Our equivalent is the hand-rolled NDJSON reader in
`web/lib/engine.ts`.

## prompt-kit + interior.dev — the ask state machine

idle → selection → composing → submitted → first token → streaming →
complete / refusal / stopped / error. Numbers the sources actually give:

| Number | Value | Source |
| --- | --- | --- |
| skeleton delay / min visible | 120 ms / 380 ms | interior.dev |
| caret blink | 1.06 s stepped | interior.dev |
| textarea autosize cap | 240 px (min 44 px) | prompt-kit |
| entrance stagger / rise | 60–90 ms / 16–32 px | taste-skill |
| prompt-kit verdict | copy the PromptInput pattern + stick-to-bottom behavior; skip the Radix/shadcn dependency and the Message/Loader/shimmer set | audit |

Anti-patterns: no percentage meter (the duration is unknown — show elapsed,
then lock the real number); no idle spinner over the ~25 s cold load (say the
cause); no skeleton flash (120/380); no typewriter on a frozen response; no
layout shift above the answer (fixed rows, zero-width caret, reserved figure
boxes); `aria-busy`/`aria-disabled`, never native `disabled` in flight;
refusal only from `final.refused`, never from partial tokens.

## Our engine's extra state: reset / the hold

The engine holds provisional generations — tokens stream only for the
generation whose text becomes the answer (`engine/server.py:_stream_response`) — so the
pane shows one continuous stream. `reset` still marks that a draft was
discarded and usually arrives before anything was shown (no-op it); the `[Ch. `
retry's stream leads with the prefill. On every `final`, replace what is
displayed with `final.body.answer` verbatim (a rejected retry is the one late
swap).
