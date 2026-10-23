# Glossary

Plain definitions for the vocabulary this repo uses. For how the parts fit, see
[ENGINEERING.md](ENGINEERING.md); for why, [DECISIONS.md](DECISIONS.md).

## Product

- **ask mode** — the model must quote one sentence verbatim from a shown
  passage, tagged `[Ch. N]`, with a short gloss. A quote that is not verbatim
  fails the check and becomes a refusal (`engine/answering/quoteask.py`).
- **answer mode** — the window default. The model writes a short answer from the
  shown passages with the same quote-first prompt as ask mode. Its `[Ch. N]` tags
  become citations matched back to the shown passages, and quotation marks the
  passages cannot back are stripped (`engine/answering/freeanswer.py`).
- **explain mode** — the reader's selection is the question; the selection's
  chapter neighborhood is the evidence (`engine/answering/explain.py`).
- **quiz mode** — one question plus one key sentence from one chunk. The
  question must not contain the key (`engine/answering/quiz.py`).
- **import mode** — `POST /ask` with `mode: "import"` registers an EPUB: ingest,
  embed, save, update the catalog (`engine/server.py`).
- **refusal** — exactly `Not in this book.` It means the book does not cover the
  question, never "I did not understand you" (`GOAL.md`).
- **citation** — `[Ch. N]` plus a quote that appears in the named passage.
- **passage / chunk** — one indexed piece of a book. A `chunk_id` such as
  `ch06-011` is the chapter label plus a running number.
- **pin** — the chunk the reader selected (`chunk_id` on the request), kept
  among the shown passages. In tests and datasets, the chunk id a question is
  expected to cite.
- **canonicalization** — rewriting a bare phrase into a question (`watermark`
  becomes `What is watermark?`) before retrieval and prompt; the answer ends with
  `Asked as: "..."` (`engine/answering/canonical.py`).
- **Read as:** — the answer's note when a typo was repaired: a question word
  absent from the book was replaced by its closest book word
  (`engine/retrieval/readings.py`).
- **retry** — the one regeneration with the assistant turn prefilled `[Ch. `,
  used when a reply has no valid citation. It is kept only when a citation
  validates as verbatim passage text; it can add a citation, not change the
  answer's meaning.
- **gloss** — the one or two plain sentences that explain the cited quote
  (`engine/answering/gloss.py`).
- **plain register** — answer mode when the question carries a cue such as "in
  simple words": evidence sentences from a draft are rewritten one in, one out
  (`freeanswer._plain_body`).
- **half-covered comparison** — a "X vs Y" question where the shown passages
  cover only one side; the answer quotes that side and says the other is not in
  the passages (`engine/answering/comparison.py`).
- **follow-up** — a second question on a margin card. The client sends up to two
  prior turns as `history`; history resolves references and is never evidence.
- **follow-up chips** — suggested next questions built from the cited chunk and
  its neighbors (`engine/answering/intent.py`).
- **highlight intent** — the structural class of a selection: concept term, vague
  fragment, multi-sentence passage, or author question
  (`engine/answering/intent.py`).
- **passing mention** — a selected term that appears in a passage only
  incidentally; the engine grounds the answer in the passage that explains the
  term instead.
- **figure attach** — a figure is attached when a cited passage names its number
  and the figure file exists. The engine never describes pixels.
- **Multi-Book Catalog** — `data/books.json`: the books this machine has
  ingested, with chunk, figure and chapter counts and cover paths. Machine-local.

## Retrieval

- **dense search** — embed the question with the embedder, rank chunks by dot
  product against pre-normalized unit vectors, take the top 10; the answering
  layer shows 5.
- **rare-word gate** — a question word that appears in few chunks lets the
  lexical channel contribute a candidate (`engine/retrieval/keywords.py`).
- **anchor words** — question words rare in the book; a paragraph containing one
  counts as answering material.
- **RRF (reciprocal rank fusion)** — places the lexical candidate among the dense
  results by both ranks (`engine/retrieval/fusion.py`).
- **rank band** — the dense-rank limit inside which a lexical candidate is
  admitted, so it cannot rescue an out-of-book question.
- **caption seeding** — when a figure caption outscores the best chunk, the best
  chunk naming that figure leads the passages (`engine/retrieval/captions.py`).
- **text seam** — `normalize`, `fold`, `tokens`, `words`, `stem` in
  `engine/retrieval/preprocess.py`: the only places text is re-viewed. Chunk text
  itself is never rewritten.
- **postings / word map** — the in-memory inverted index from word to chunks,
  built once per index (`keywords.postings`).
- **reader payload** — `GET /chunks`: the book as the reader needs it, in reading
  order, without vectors, figures as cards with their pixel size
  (`retrieve.chunks_payload`).

## Streaming

- **frames** — NDJSON lines on `stream=1`: `token`, `reset`, `final`, `error`.
  A stream that starts always ends with `final` or `error`.
- **reset** — a frame signalling that a streamed draft was discarded.

## Frontend

- **lens** — the pill at a text selection: Explain, Ask, Copy, highlighter
  swatches (`web/components/reader/Lens.tsx`).
- **margin card** — an answer anchored beside its passage, with its own turns
  (`web/components/margin/MarginCard.tsx`).
- **composer** — the bottom whole-book question box
  (`web/components/reader/Composer.tsx`).
- **citation jump** — clicking a `[Ch. N]` chip or the quote scrolls the reader
  to the cited block and marks the quote.
- **rail** — the left minimap with chapter ticks, highlight bars and gloss dots
  (`web/components/reader/Rail.tsx`).
- **library** — the start menu: shelf and grid views, book detail, EPUB drop
  (`web/components/library/`).

## Models

- **answer model** — the local Ollama model that writes answers. Default
  `nekohon_x3` (3B); `nekohon_x3_mobile` (1.5B) is the smaller companion;
  `ANSWER_MODEL` overrides (`engine/answering/prompt.py`).
- **embedder** — `nomic-embed-text`, used for chunks, figures and queries.
- **student / teacher** — the small shipped model and the larger model whose
  answers it was trained on.
- **LoRA** — the small trainable adapter used to finetune; the app loads the
  merged GGUF.

## Testing

- **battery** — scripted live checks with pinned chunks
  (`artifacts/harnesses/step2-battery.py`); `BATTERY_MODE=answer` runs answer mode.
- **cassette** — recorded Ollama traffic and engine responses; replay must be
  byte-identical (`.agents/skills/verify/cassette.py`).
- **harness** — a reusable measuring tool under `artifacts/harnesses/`.
- **judge** — an LLM that grades softer qualities. Default is the cloud
  `muse-spark-1.3-contributor`; `JUDGE_BACKEND=ollama` switches to the local
  `granite4.1:8b`. Verdicts are a triage dial, not a gate
  (`artifacts/harnesses/judge.py`).
- **groundedness meter** — the share of answer sentences whose 4-grams appear in
  the shown passages (`artifacts/harnesses/groundedness.py`).
- **loop** — a generation that stops only at the token cap or repeats a phrase.
- **contract** — the frozen `POST /ask` request and response shape
  (`tests/test_contract.py`).
- **engine-reset rule** — a running server keeps the code and model it loaded;
  restart after any change and check `/api/ps`.
