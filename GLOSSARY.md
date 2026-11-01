# ask-this-book

An offline companion that answers questions about technical books from the
books' own passages, cites the passage it used, and shows the figure that
passage names. This vocabulary is what the code, the traces and the team call
these things; prefer these words when talking about the system.

## The book side

**Book**:
One EPUB or PDF, ingested into its own index and identified by a stable `book_id`.
_Avoid_: volume, title, source, document

**Catalog**:
The list of ingested books with their counts, which the shelf reads from.
_Avoid_: library index, manifest

**Chunk**:
The stored unit of the index — a few paragraphs of one book, addressed by `chunk_id`.
_Avoid_: block, segment, section

**Passage**:
A chunk in the retrieval window: one of the few the model is shown for a question.
_Avoid_: chunk (when you mean a shown one), snippet, hit

**Heading**:
The line that opens a chunk and serves as its title.
_Avoid_: title

**Chapter**:
The book's own chapter number, carried by chunks and used in citations.
_Avoid_: section

**Figure**:
A picture extracted from a book, with an id, a caption, and the paragraph that references it.
_Avoid_: image, illustration

**Cover**:
The book's cover image, served like a figure.

## Retrieval

**Dense leg**:
Ranking chunks by embedding similarity to the question.
_Avoid_: vector search, semantic search

**Lexical leg**:
Ranking chunks by exact word match (BM25), turned on only when the question carries a rare term.
_Avoid_: keyword search, full-text search

**Fusion**:
Combining the two rankings by reciprocal rank so a chunk strong in either leg surfaces.
_Avoid_: merge, blend

**Rare term**:
A question word that appears in few chunks — what turns the lexical leg on.
_Avoid_: uncommon word, keyword

**Phrase boost**:
Score adjustment rewarding a chunk whose heading or phrasing matches the question.
_Avoid_: rerank

**Caption seed**:
Pulling in the paragraph a figure caption points at, when the caption matches better than any chunk.

**Window**:
The handful of passages the model is shown for one question.
_Avoid_: context, input

**Shown passages**:
The window as recorded in the trace — exactly what the model saw.
_Avoid_: hits, results

**Pin**:
The passage the reader is looking at, which leads the window on a follow-up.
_Avoid_: anchor, context chunk, cursor

**Battery pin**:
A golden question and answer that a change must keep passing.
_Avoid_: pin (when you mean the test), golden

**Canonicalization**:
Rewriting a bare phrase into a question before retrieval ("watermark" → "What is watermark?").

**Second reading**:
A retry of a question whose words are not in the book, kept only when it scores strictly better.

## Answering

**Answer mode**:
The default: free prose from the shown passages, cited per sentence; prose that names no passage is refused.
_Avoid_: chat mode, free mode

**Ask mode**:
Quote-first: a verbatim passage sentence with its citation, then a short gloss.
_Avoid_: highlight mode

**Explain mode**:
The highlight path — gloss the selected sentence and quote it.
_Avoid_: gloss mode

**Quiz mode**:
A question written from one key sentence; refuses rather than leak the answer.

**Import mode**:
Adding a new book through the app instead of the shell.

**Gloss**:
The plain-language explanation that accompanies the quote.

**Citation**:
The chapter tag plus the quoted sentence an answer is built on.
_Avoid_: reference, source

**Citation gate**:
The final check: a body must name a passage, be recovered from one, or become the refusal.
_Avoid_: citation check, verification step

**Refusal**:
Exactly `Not in this book.` — the book does not cover the thing.
_Avoid_: error, miss, "I don't know", fallback

**Guard**:
A check that refuses before the model is called.
_Avoid_: filter, validator

**Transform**:
A rewrite applied after the model answers, recorded in the trace.

**Comparison branch**:
The two-sided path for "compare X to Y" questions, preferring the book's own contrast sentence.
_Avoid_: diff mode

**Half-covered**:
A comparison where the book covers one side only; answered as a refusal.
_Avoid_: partial answer

**Plain register**:
The "explain in simple words" rewrite.
_Avoid_: simplified mode, ELI5

**Follow-up**:
A suggested next question returned with an answer.
_Avoid_: suggestion, related question

## Measurement

**Trace**:
One JSON line per request, holding what was asked, retrieved, called and returned.
_Avoid_: log line, event

**Anomaly**:
A flag on a trace that marks something worth looking at.

**Harness**:
A runnable scorer that produces evidence.
_Avoid_: benchmark (as a verb), test

**Fair set**:
The pinned 120-item set, split into dev (iterate here) and locked (hold-out).

**Sealed suite**:
The 60 held-out items used to check that a change generalises.

**Hard bench**:
A self-certifying set where each item answers its own rubric.

**Stage attribution**:
Naming the stage that failed — guard, retrieval, generation, or transform.

**Judge**:
A model that grades answers for a harness; the engine never uses it.
_Avoid_: grader (when you mean the judge)

**Evidence**:
A saved run output, dated and named by the run that produced it.

**Stale**:
A measurement older than two days, or a doc that no longer matches the code.
