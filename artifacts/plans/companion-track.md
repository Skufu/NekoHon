# Companion track

The multi-turn companion: a reader asks a follow-up on a margin card and the
answer stays anchored to the book. Pointers, not copies. Before touching
history or the thread, read [conversation-map.md](conversation-map.md); for the
reader and margin UI, [pane-now.md](pane-now.md).

## How it works

- The browser holds the thread. Each margin card keeps its own `turns[]`
  (`web/lib/store.ts`, `web/lib/turns.ts`). The server is stateless.
- A follow-up sends the card's last two completed turns as `history` on
  `POST /ask`. The engine clips them (`engine/answering/sanitize.py`).
- Follow-up retrieval stays in the chapter neighborhood of the earlier turns
  (`engine/answering/conversation.py`, `engine/answering/context.py`), so a
  reference such as "what does it do?" does not jump chapters.
- A "simpler" cue (`SIMPLIFY_RE` in `engine/answering/messages.py`) takes a
  shortcut: it rebuilds the answer from the prior turn's anchor sentence and a
  short gloss without a full regeneration (`pipeline.simplify_shortcut`).
- Follow-up chips come from the cited chunk and its neighbors
  (`engine/answering/intent.py`, `compute_dynamic_followups`).
- Quotes are checked against this turn's passages only. History helps resolve
  references; it is never evidence.

## Multi-book

`data/books.json` is the machine-local catalog. `POST /ask` takes `book_id`;
figure resolution reads the filesystem (`engine/figures.py`). The library view
lists only books the engine has indexed.

## Verification

- `python3 -m unittest tests.test_query_understanding tests.test_intent`
- `python3 artifacts/harnesses/adrian-eval.py` and
  `python3 artifacts/harnesses/crossbook-evil-eval.py` (live engine and Ollama).
  Both include scenarios that the current model fails; read the output, do not
  compare it to an old number.

## Parked

Conversational clarify turns and other open work: [backlog.md](backlog.md).
