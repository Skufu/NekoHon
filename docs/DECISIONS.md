# Decisions

Why the code is the way it is. The Python source carries no comments or
docstrings; the measured reasons live here. Each bullet: the decision, the
reason or measurement, and where it lives. Dates are measurement dates. A
constant listed here has a stated reason; do not move one without a new case
and a rerun of the gates (`.agents/skills/verify/SKILL.md`).

## Ingest

- **Sentence-boundary packing, never a mid-sentence cut.** Chunks are packed
  from whole sentences and the overlap is whole trailing sentences. The old
  cut at the last space and a word-count overlap made 37% of chunks start
  mid-sentence (373 of 1013). A cut chunk makes the model quote a fragment.
  `ingest._pieces`, `_sentence_tail`.
- **Sentence splitter leans toward not splitting.** Known abbreviations and
  initials do not end a sentence. A missed merge only makes a piece longer; a
  false split becomes a chunk that starts mid-sentence. `ingest` sentence
  splitter and its abbreviation set.
- **A sentence past the cap is cut somewhere, as a last fallback.**
  `ingest` oversize-sentence fallback.
- **Overlap tail comes from the section body, not the chunk, and a trailing
  sentence longer than the limit yields nothing.** Taking the tail from the
  chunk repeated the heading inside the next chunk. A citation list has no
  sentence ends, so its whole text read as one sentence and chunks grew past
  5,000 characters in a chain. `ingest._sentence_tail`.
- **A table stays one piece even past the cap.** A cut table is worse than a
  long chunk. `ingest._section_chunks`.
- **Chunk `section`, `anchor`, `doc`, `figures` are metadata only.** Joining
  them to the text would move every vector. `anchor` is empty when the EPUB's
  headings carry no id; a nearest-preceding anchor was measured and rejected
  (wrong deep link is worse than none). `ingest` chunk records.
- **Figure xref marker.** A hidden marker wraps a figure's xref href so the
  citing-paragraph search can find the figure; stored text drops it and keeps
  the link words. `ingest` figure pointer search.
- **Non-teaching documents are skipped** (index, front matter, alphabetical
  index chunks) because they steal search slots. Preface, part openers,
  chapters and appendices stay. `ingest` non-teaching filter.
- **Chapter tag is the number only.** A second book's spine ids were
  `chapter-4`; the prompt tag must read `[Ch. 4]`, not `[Ch. chapter-4]`
  (measured 2026-10-14). Chunk ids are unchanged. `ingest._chapter_number`.
- **Figure ids keep a letter prefix.** `figure-a1-2` and `figure-1-2` stay
  distinct; a bare `1-2` still matches. `figures` number token.
- **Figure size comes from the PNG header** (no decode, stdlib only) so the
  reader reserves the aspect ratio and never jumps on load. `figures`.
- **A figure attaches from a given passage only when that passage names its
  number, and only when the figure file exists.** There is no embedding score
  floor; do not attach by vector score. The answer never describes pixels.
  `figures.figures_for`.

## Retrieval

- **One text seam.** `normalize()` (dense view), `fold()` (matching view),
  `tokens()`/`words()` (the only tokenizers) are the only place text is
  re-viewed. Index and query go through the same function so they cannot
  drift; before this, five call sites ran their own `.lower()`.
  `chunk["text"]` is canonical, never rewritten, and is what gets cited.
  `retrieval/preprocess.py`.
- **`normalize()` is applied at embed time on both sides.** Turning it on
  without rebuilding the index leaves query and stored vectors in different
  spaces and degrades silently. It moved 3 of 1065 chunks on the first book;
  it exists for books with ligatures, no-break spaces or full-width forms.
  `retrieve.format_input`.
- **`fold()` repairs typographic punctuation by hand** (NFKC leaves curly
  quotes and dashes alone) and runs before tokenizing, otherwise a ligature
  strands part of a word. `preprocess.fold`, `stemmed_words`.
- **Tokens keep alphanumerics with a letter** (`S3`, `3NF`, `DDR4`); pure
  digits are not tokens. `preprocess.TOKEN`.
- **Stopwords are the vendored SMART list; stemming is vendored Snowball
  (Porter2).** Both are matching views, never rewrites. Stopwords never anchor a
  paragraph. `vendor/`, `preprocess.STOPWORDS`, `stem`.
- **Embedding task prefixes live in code** because Ollama's Modelfile does not
  add them. Unknown models fail closed. nomic uses `search_document: ` and
  `search_query: `; gemma writes a real heading into the text. `retrieve`
  prefix table.
- **Embedding hygiene guards.** A response vector that is the wrong width,
  non-finite, all-zero, or from a short batch is refused before storage and
  names the chunk. `rank_chunks` refuses an empty or non-finite query vector,
  a query contradicting `embedding_dims`, and a drifted stored width. Measured
  clean on the live index (all vectors 768-wide, none zero or non-finite).
  `retrieve.embed_index`, `rank_chunks`, `scripts/verify_index.py`.
- **`rank_chunks` ranks with pre-normalized unit vectors** (dot product), a
  measured 2.6x faster dense ranking. Zero-length vectors score 0.
  `retrieve`.
- **`dense_rank` has no evidence without an embedder.** An index with no
  embedder returns an empty rank map, and callers needing evidence fail
  closed. `retrieve.dense_rank`.
- **Reader payload is one block per chunk.** No two consecutive chunks overlap
  in the first book, so nothing needs merging; the repeated heading line is
  dropped and travels as its own field. `retrieve.chunks_payload`.
- **Rare-word gate: `RARE_DF = 8`.** A question word living in at most 8
  chunks lets the lexical channel join. It is a trigger only; the safety is
  the band below. `keywords.rare`.
- **Anchors: `COVER_DF = 80`.** Question words rare in the book (df <= 80)
  mark a paragraph as answering material. A fixed English list-word list is not
  shippable (sampled list words ran from df 1 to 77, no natural cutoff); the
  book's counts are. Stopwords are filtered first because their df says how
  the book talks, not what the question is about. `keywords.anchor_words`.
- **Fusion: `RANK_BAND = 0.20` is the tail veto.** A lexical candidate must
  sit in the dense top 20% of the corpus. The band, not word counts, decides:
  with the df gate forced open the France candidate (dense rank 649 of 1042,
  62%) is rejected at 0.10 and injected at 1.00. 0.10 silently dropped the MAD
  anchor (13.1%) and with it the right sentence; 0.20 admits every measured
  anchor and refuses France by more than 3x. Dimensionless on purpose so a
  bigger book is not distorted. Do not move it without a case outside 13.1%-65%.
  `fusion.RANK_BAND`.
- **Fusion: one lexical candidate, `RRF_K = 60`.** 60 is the RRF paper's
  constant. A head of five candidates flooded out dense leaders (mid-frequency
  word sums: df about 178 for "about", 333 for "engineers") and flipped the MAD
  quote to the data-mesh passage. One candidate reproduces the prior swap's set;
  RRF only decides where it lands. Ties break on dense rank, then lexical rank.
  A candidate with no dense rank has no evidence and is dropped. A candidate
  already in the set moves nothing (the battery has cases that fell over when a
  present passage moved). `fusion.fuse`.
- **Fusion runs only when the question carries a rare word.** It pays one
  embed plus a full cosine pass (~0.11 s). Widening the trigger is a separate,
  measured step. `context.retrieval_context`, `keywords.rare`.
- **Caption seeding runs last, after fusion.** Its measured effect is which
  chunk leads, and fusion would otherwise demote that lead. The comparison base
  is the best chunk score in the set, not the first passage's, because fusion
  reorders. A naming chunk already in the set is left where it is: moving a
  present one to the front broke a golden. Measured case: caption 0.751 vs best
  chunk 0.671 for the MAD landscape question. `captions.caption_seed`.
- **Readings (typo repair) show their work and prove themselves.** An
  out-of-book word is swapped for its unique closest book word (difflib,
  `CUTOFF = 0.85`, no tie at the top); the reading is kept only when its best
  dense score strictly beats the literal question's. The reading becomes the
  question the model answers and the answer says `Read as: ...`. The gate, not
  the cutoff, protects refusals: France -> "Franca" scored 0.544 -> 0.530 and
  was dropped though one letter away. Hints failed: six shapes of note
  returned a refusal for the CRU question, because the model will not map
  `CRU [book: "CRUD"]` onto `CRUD`. `readings.second_reading`.
- **Reading guards.** Skip mid-sentence Titlecase proper nouns, camelCase and
  PascalCase tokens, and tokens with digits (`DDR4`, `3NF`); keep all-uppercase
  acronym typos and lowercase typos. Spellings restore the book's own casing
  (`CRUD`, not `crud`). `readings` guard and spelling map.
- **LLM second reading is the fallback under the same gate.** It wins the cases
  difflib cannot see ("normilazation", "ingestoin"). Two structural guards, both
  from measured failures: the folded words must change (`iops` -> `IOPS` passed
  the score gate on embedding jitter), and the token count must not change (no
  expansion; a same-count wrong fix, CRU -> CRC, still faces the gate). A failed
  call leaves the literal question. `readings.llm_second_reading`.

## Answering

- **Prompt alignment (2026-10-15).** Answer mode serves the same quote-first
  `SYSTEM` + `user_message` as ask, the prompt the student was trained on. The
  older "a few sentences in your own words" prompt made a model that followed it
  paraphrase and fail the verbatim check (40/160 vs 111/160). `answer`,
  `freeanswer.respond`, `_retry_uncited`.
- **`[Ch. ` prefill retry.** An uncited reply is retried once with the
  assistant turn prefilled `[Ch. `, kept only when a citation whose quote is
  verbatim passage text survives a parse (`parse_answered` first, then the ask
  parser, since a tag-first continuation validates only through it). Every
  failure path returns None and the original answer stands. The trigger is
  "uncited and passages present", not an anchors gate: anchors missed half of
  the non-control suite items. A generator seam without prefill support keeps
  the original answer. `freeanswer._retry_uncited`.
- **Ask mode retries a refusal once, with the same prefill.** `ask` parses
  strictly (`parse_completion`: a `[Ch. N]` tag, then a quote that is verbatim
  passage text), so a reply that skips the tag or paraphrases becomes a refusal
  even though the book holds the answer. When that refusal happens and every
  content word of the question is present in the shown passages and the book's
  word map, `_retry_uncited` regenerates once with `[Ch. ` prefilled and keeps
  the result only if each citation quote is verbatim passage text. A follow-up
  whose question was rewritten from history may also retry, unless the question
  matches the trap pattern (`_TRAP_QUERY_RE`). If the retry yields nothing and at
  least three passages are shown with the same evidence test, the last resort is
  the lead passage's sentence with the most question-word overlap, quoted as
  is. Out-of-book questions fail the evidence test and keep the exact refusal.
  `quoteask.ask`, `freeanswer._retry_uncited`, `freeanswer._has_passage_evidence`.
- **A retry for false refusals needs grounding.** It fires only when every
  content word in the query is in the shown passages and the book's word map
  (stem-level, alphanumerics preserved). Out-of-book questions (France) fail
  closed immediately. `freeanswer` grounding gate.
- **Answer mode is a meter, not a gate.** Tags become citations, unbacked
  quotation marks are stripped, a zero-overlap claim stays uncited rather than
  guessed, and a hallucination is a measurement. The refusal is the exact first
  line only. `freeanswer.parse_answered`; meter in
  `artifacts/harnesses/groundedness.py`.
- **Tag parsing masks `Ch.` periods.** Tags are masked before the sentence
  split, including the second `Ch.` of "[Ch. 2, Ch. 7]"; otherwise the claim is
  dropped and the answer loses all citations (measured 2026-10-13). Text
  accumulates until a tag arrives. `freeanswer._sentence_claims`.
- **Citation quote is the sentence with the most claim overlap,** the rule the
  passage choice already uses; a copied run only breaks ties and is the
  fallback. A stray generic run ("by data scientists, analysts, and other") must
  not hand the quote to an enumeration sentence (measured 2026-10-13: the plain
  register rewrote the enumeration, not the definition).
  `freeanswer._evidence_quote`.
- **Footnote glue splits sentences.** A marker glued to an attribution
  ("Maxime Beauchemin4") has no sentence end, so whitespace collapse ran it
  into the next sentence. The split view only; chunk text untouched.
  `shared._sentences`.
- **Quote check is verbatim except figure references.** "(Figure N-N)" is
  stripped from both quote and passage, because the model drops it when copying
  and the book puts it mid-sentence. Typography folds the same way (curly
  quotes, interior commas; "data about data"). Word order is kept.
  `quotecheck`.
- **Span fix.** When the model edits a near-verbatim copy, keep the longest
  word-for-word run, floor `SPAN_MIN_CHARS = 40`; shorter overlap stays a
  refusal. `KEY_MIN_CHARS = 40`. `quotecheck`, `shared`.
- **`MIN_QUOTE_CHARS = 20`.** A complete sentence may be a quote under the span
  floor: "Everything fails, all the time." is 30 characters. Shape decides
  (upper-case start, terminal punctuation, real cleaned length); a fragment or
  bare heading does not pass. `shared`, `quotecheck`.
- **Tag-slip rebuild.** A verbatim quote from any attached passage is a true
  quote even when the `[Ch. N]` tag is wrong (measured: `[Ch. 1]` on a ch04
  sentence); the chapter is rebuilt from the matched hit. A quote in no passage
  still refuses. A tagless verbatim reply is tagged from the matched passage.
  `quotecheck`.
- **Heading trim runs once, after every path that sets a quote.** The anchor
  expansion replaces the quote with the whole paragraph, heading line included.
  The heading is dropped only when a genuine new upper-case sentence follows it;
  "Modularity (Figure 4-5) is..." and "Storage is the cornerstone..." keep their
  subject. `listshape`, `quotecheck`.
- **Paragraph expansion, `PARAGRAPH_CAP = 1200`.** When the paragraph around a
  verified quote holds an anchor word the quote lacks, or a plural anchor
  ("disadvantages", "types", "steps"), the paragraph replaces the quote. One
  screen (about 16 lines of 75 characters); chosen for readability, not tuned.
  Paragraph text is passage text, so the quote check holds by construction.
  Plurals are detected by a regular-plural suffix rule, not a dictionary;
  irregulars fall through to the model (the safe side). `listshape`, `shared`.
- **List asks take the items, not the lead-in.** A trailing colon is the
  printed cue; "the following" is a lead-in only when what follows is itself a
  lead-in. The repair moves passage text after the lead-in into the quote;
  nothing is added the passage does not contain. A colon lead-in is often its own
  paragraph, so the next one holds the items. `listshape`.
- **Figures attach only from a passage the answer cited.** Not every kept
  passage. Refusals keep the "nearby, not an answer" labelling. `quotecheck`.
- **Canonical form.** A structurally bare phrase is asked as `What is X?`
  before retrieval and prompt, so both see one string (a prefix reaching only
  the prompt refused the ask-mode question). Guards: no `?`, no wh-word, first
  token not an auxiliary, opener, imperative or list marker, no pronoun. These
  are closed English classes, not topic lists; non-triggering input passes
  through byte-for-byte. The rewrite is disclosed as `Asked as:`. Explain is
  gated off (its highlight is a book sentence). Measured 2026-10-13: bare labels
  drew surveys and three figures; the question form stayed on one naming chunk.
  `canonical`.
- **Comparator rewrite.** Exactly one comparator (vs, versus, compared to,
  compare X with Y) asks "the difference between X and Y", before the bare-phrase
  rules; two or more connectors, a sentence, or an already-spelled-out difference
  question pass through. Owner decision 2026-10-15 (rated sample rows 27 and
  8): a label asked as a definition was rated wrong. `canonical`.
- **Half-covered comparisons.** When exactly one side is in the shown passages
  and a verbatim span can be quoted, the answer quotes that side and names the
  other in a gloss, never quoting it or giving it attributes the passages lack.
  Owner decision 2026-10-15: `ddr4 vs ddr5` answers the covered side with a
  boundary gloss. Digits stay in comparison tokens so numbered sides do not fold
  to one stem. `comparison`.
- **Plain register.** A "simple words" cue routes through `_plain_body`: the
  draft selects evidence sentences, each rewritten one-in-one-out with
  `PARAPHRASE_SYSTEM`, keeping its source chunk's tag; citations keep the
  original book sentences. Nothing is written from scratch. `PARAPHRASE_LIMIT =
  5` is a call budget, not a quality knob. Cues are generic English phrases.
  An all-empty rewrite set falls back to the draft. Measured scorecard 8/10
  under the release judge with +/-1-2 borderline noise per draw. `freeanswer`.
- **Selection text is cleaned** (short colon lead-in lines dropped, whitespace
  flattened), and `Asked as:` is suppressed whenever a selection or history is
  present. `explain`, `context`.
- **Explain pins the reader's chunk.** The chunk the reader selected leads and
  stays in the passages even when dense search prefers another chapter; a short
  highlight is asked as `What is X?` with the heading so search knows which
  sense. The figure attaches only on a cited number, a heading match, or a caption
  sharing content words with the selection. `explain`, `context`.
- **Gloss coherence guard.** Rejects short or gibberish text, a content word
  repeated 4+ times, adjacent repeated words, sentences ending in an auxiliary or
  determiner, meta-commentary, pointer non-answers, prompt leakage and quote
  repetition; a grounded gloss is then synthesized from the anchor sentence.
  Repetition threshold is 4 to allow parallel list items; `is/are/was/were` are
  not dangling endings. Case-insensitive `[Ch.` tags are stripped from glosses.
  `gloss`.
- **Intent classification** is structural: author question (ends `?`),
  multi-sentence (>= 140 chars or 2+ sentences), vague fragment (2-10 words
  opening on copula, auxiliary or preposition), concept term (1-6 words or a
  heading). Meta lead-ins ("Before we discuss...") never anchor. Dynamic
  follow-up chips use contrast only on contrast cues, look forward not backward
  for neighbors, and need >= 60% stemmed overlap to count as redundant.
  `intent`.
- **Follow-up topic shift** requires no deictic reference or generic follow-up
  stem and no content-word overlap with the history. `conversation`.
- **Prompt injection defense** strips control tokens and collapses forged
  section headers; history is clipped to the last `HISTORY_TURNS = 2` turns.
  `sanitize`.
- **Quiz.** One question, one key sentence from one chunk; the question must
  not contain the key (a leak is a refusal); weak narrative transitions never
  key; a part title or index chunk is not a teaching chunk. `quiz`.

## Prompts & model

- **Refusal is exactly `Not in this book.`** Period included, nothing else; in
  answer mode the first line must be the exact sentence. `prompt`.
- **Default model `nekohon_x3`.** Revert without editing:
  `ANSWER_MODEL=qwen2.5:7b`. `prompt.ANSWER_MODEL`.
- **Steering a student by instruction failed repeatedly** (definition verbs,
  spelling notes, gloss forcing, multi-quote, a narrow gloss-content steer): each
  either skipped the format or broke goldens by turning answers into refusals.
  The levers that held are code-side (retry, parse, repair).
  See Negative results.
- **Plain-register prompt:** the draft selects evidence, each sentence is
  rewritten one-in-one-out so invention has nowhere to go. `PARAPHRASE_SYSTEM`.
- **Spell enhancer prompt:** the model proposes; the strict-improvement gate
  decides; a kept correction is always disclosed as `Read as`.
  `prompt.SPELL_SYSTEM`.
- **`num_predict: 512`.** Caps runaway generations: a loop becomes a truncated
  answer instead of a 120 s timeout. Far above the longest legal reply (answer
  p90 is 622 characters). `think: false`, `temperature: 0`,
  `keep_alive` default 24h. `engine/llm.py`.
- **Prefill is a raw continuation.** A trailing assistant turn makes the model
  continue from the prefill (probed 2026-10-14: "hello" continued as " world").
  Callers prepend the prefill themselves; the token stream carries it so the
  pane shows `[Ch. 7] ...` not a bare `7] ...`. `llm.generate`,
  `generate_stream`.

## Server & streaming

- **Stream contract.** Every stream that starts ends with `final` or `error`,
  never bare EOF, or the client sits on a blank pane. The catch-all frames any
  exception and prints the traceback. `rank_chunks`/`caption_seed` refuse with
  `SystemExit`, which would otherwise kill the handler thread. `server`,
  `tests/test_stream_contract.py`.
- **Only the generation whose text becomes the answer streams live.** A
  `reset` frame signals a discarded draft and is emitted even when nothing was
  shown; the UI keeps the frame as its discard signal and no-ops on empty text.
  The retry's continuation is live as the first generation. `server._stream_ask`.
- **CORS echoes only the dev UI origins (:3100, :3200);** the built UI is
  same-origin. `server.ORIGINS`.
- **Static export serving.** `web/out` is served at `GET /` when present,
  falling back to `window/index.html`; traversal attempts (encoded, absolute,
  backslash, drive letter) 404, and engine routes are never shadowed.
  `server`.
- **`DEFAULT_BOOK_ID`** (`server`, `context`) is kept for single-book callers; its literal is built so
  the generalization guard does not trip. Open item in `artifacts/plans/backlog.md`.
- **Warm-up** primes in-process caches (catalog, index, postings, chunks
  payload and gzip) and Ollama models with the same options as the real calls,
  then verifies `/api/ps`; it may run in a background thread so the server
  listens at once. Measured cache wins: postings 82 ms -> ~0 ms, dense ranking
  2.6x, chunks payload 1.14 MB -> 328 KB gzipped. `server`, `scripts/launch.py`.
- **Launcher port hygiene.** It kills a listener only when its command line is a
  Python process running `server.py`/`engine.server`; otherwise it names the
  PID and exits non-zero. Recommended Ollama env, measured 2026-10-18:
  `OLLAMA_NUM_PARALLEL=1` (100% GPU at 2.2 GB vs 2.7 GB at 4; TTFT 38.4 vs
  44.7 ms) and `OLLAMA_FLASH_ATTENTION=1` (median TTFT 72.7 -> 33.4 ms).
  `scripts/launch.py`.
- **Request limits and import paths.** `POST` bodies over `MAX_BODY_BYTES`
  (64 MiB) get `413` before the body is read. Base64 inflates 4/3, so the cap
  admits an EPUB of about 48 MiB, above any book in the catalog; a missing
  `Content-Length` counts as 0, and a non-numeric or negative one gets `400`
  (a negative length used to read until the client closed). Import `epub_path` is
  resolved and must sit under `books/` (`400` otherwise), so the route cannot
  read arbitrary files. Figure routes normalize `book_id` with
  `_normalize_book_id`, so `../` cannot leave the figures root, and
  `get_book_index` (behind `/chunks` and `/ask`) refuses any non-default id
  that normalization would change, so `book_id` cannot reach a path outside
  `data/`. An import
  clears the `id(index)`-keyed caches (`retrieve.clear_index_caches`) so a
  recycled id cannot return a stale ranking. `_lru_get` uses `pop(key, None)`
  so two threads on one key cannot raise `KeyError`. `server`,
  `tests/test_robustness.py`.
- **Preflight is read-only and derives every path and model name from engine
  constants** so it cannot drift from the app. `scripts/preflight.py`.
- **Index audit** treats a chunk or figure with no vector as dirty, not a
  warning. `scripts/verify_index.py`.

## Frontend

- **Static export.** `next build` writes `web/out/`, which the engine serves at
  `GET /`. Dev runs `next dev -p 3100` against the engine on :8000. The
  Turbopack root is pinned because it otherwise infers its workspace root from a
  stray `package-lock.json` in the home directory. `web/next.config.ts`.
- **Engine base URL.** The dev server on :3100 targets :8000; when the engine
  serves the page it is same-origin and relative URLs are used.
  `web/lib/engine.ts`.
- **Stream reader.** EOF with no `final`/`error` frame means a crash or dropped
  socket; unhandled, the pane stays blank and the store's controller is never
  cleared. A non-JSON error body is tolerated. `web/lib/engine.ts`.
- **Health polling** is capped at 60 s, backoff 500 -> 1000 -> 2000 ms. Only an
  explicit `ready: false` from a reachable engine disables input; a failed
  fetch must not. The engine's catalog is the truth: only books indexed on this
  machine are listed. `web/lib/store.ts`.
- **Selection offsets** are plain-text characters over the chunk's `<p>` elements
  joined by `\n`. `Range.comparePoint(p, 0) === 0` keeps a selection in paragraph
  2+ from resetting `start = 0`. Heading and caption selections return
  `start: -1`; headings re-encode with negative sentinel offsets (`start <=
  -100`) so a heading highlight never marks matching body words. Short
  lead-ins ending `:` (<= 32 chars) snap to the next paragraph; partial words
  snap to word boundaries. Cross-chunk selections split into start, whole
  intermediate and end chunks. `web/lib/anchor.ts`.
- **Reader-first answer order (owner decision 2026-10-15).** The engine writes
  quote-first; the UI shows gloss, then the italic quote with its chapter chip.
  Only order and styling change. If recovery is impossible, show the verbatim
  answer plus the chips row so a citation is never lost. `web/lib/answer.ts`.
- **Citation jump** scrolls with a cubic-bezier ease-out and a late-paint
  correction, because `content-visibility: auto` chunks shift height after
  paint. `web/components/reader/Reader.tsx`.
- **Margin layout.** The active gloss sits at its anchor; others stack away
  without overlapping; crowded or inactive minimized cards become pills; below
  1080 px a sheet replaces the margin. `web/components/margin/Margin.tsx`.
- **Composer** delays closing suggestions so clicks register. **TopBar** tucks
  on scroll down, reveals on scroll up. `web/components/reader/`.
- **Offline UI.** System fonts only, no external requests (GOAL.md). Inputs use
  a font size that prevents mobile Safari focus zoom; reduced motion is handled
  case by case. Themes (5), pens (4), highlighters (4) are tokens in
  `web/app/tokens.css`; layout is a 3-column grid with a 60 px fixed topbar.

## Evaluation & verification

- **Behavior cassette** (`.agents/skills/verify/cassette.py`) intercepts
  `urllib.request.urlopen` for `:11434`, so a refactor of the Ollama wrappers
  cannot bypass it; an unknown request fails hard. Replay needs no Ollama.
- **Mutation check** (`artifacts/harnesses/probe-test-mutations-2026-10-13.py`):
  five in-memory breaks of canonicalization must turn the suite red; 0 survivors.
- **Judge verdicts are a triage dial, not a gate.** Two identical method-v2
  runs wobbled 3 of 27 rows on 2-1 vote flips; only rows 25-27 carry owner labels;
  a consecutive-call probe returned supported, supported, unsupported at
  temperature 0. `NOT_A_GATE`; `rank-answers.py` rejects `--gate`. Single-draw
  scorecards carry +/-1-2 borderline questions; repeat draws before claiming a
  one-question win. `judge.py`, `judge-stability.py`.
- **Judge backends.** Default cloud `muse-spark-1.3-contributor` over the
  OpenCode relay (`/responses`, session header, key from `JUDGE_API_KEY` or
  gitignored `.judge-key`); offline `JUDGE_BACKEND=ollama` (granite). Cloud
  replies are retried strictly once (19 of 20 paraphrased past the key list),
  transient errors up to three attempts, and negative phrasings are matched
  before positive so "not relevant" never reads as "relevant". The engine never
  uses this path. Model identity is recorded in every judged output.
- **Graded 0-3 relevance does not transfer between judges** (exact agreement
  42/105); binary stays the headline. Rating v2 asks each yes/no bit three times
  and takes the majority.
- **Groundedness meter.** A sentence is supported when at least `SUPPORT = 0.5`
  of its 4-grams appear in the shown passages; majority is the definition, not
  tuned. Tags are removed before the sentence split. Default prompt in the
  harness is `SYSTEM_ANSWER`; pass `--system-text` to measure the live prompt.
- **Battery judges answer mode as grounded-in-retrieved:** citations must point
  at shown passages and the pinned chunk be among them; which shown passage the
  tags land on is the model's call (strict pin-in-citations was 7/10, grounded
  10/10). A single red probe is suspect until it repeats; the multicloud cold-run
  flake clears on a warm rerun. `step2-battery.py`.
- **Sweep coherence** compares stems and skips stopwords when choosing the
  guard word. `qa-sweep.py`.
- **Secret scan** checks git history and the tracked tree against this
  machine's known key values and common credential formats; the blind spot is a
  prefix-less key not among known values. `secret-scan.py`.
- **Artifacts pruner** is read-only (exit 0 always); a file older than
  `--stale-days` (default 2) is a stop sign. `artifacts/prune.py`.
- **Test guards.** `tests/__init__.py` must stay: a user-site `tests` package
  shadows the directory without it. `test_generalization.py` bans chunk, figure
  and book ids in logic modules.
  The frontend rules test pins no colour literals outside `tokens.css`, no raw
  shadows, no monospace, no emoji, every class has a rule.

## Negative results

Do not retry these without a new reason or a model change.

- **Prompt-steering the student** with six note shapes for the CRU typo, a
  definition-verb list, a gloss reminder, a multi-quote line, and a "never write
  'The passage'" gloss steer. All refused or broke batteries (gloss reminder:
  golden 10 -> 6; multi-quote: watermark and atermark refused).
- **A deterministic definition-first mover** reordered passages and changed
  nothing: the model still skipped the definition.
- **The coherence swap guard** fixed known cases but misfired 19 times in 21
  swaps (the word picker cannot tell a subject from vocabulary); reverted
  2026-10-13.
- **Five-candidate fusion head** flooded out dense leaders (see Retrieval).
- **RANK_BAND 0.10** dropped the MAD anchor (see Retrieval).
- **Blanket trailing-punctuation normalization** changed 4 of 23 quotes with
  two opposite pin flips; consistency, not correctness. Not landed.
- **Agentic retrieval** (semantic/keyword/regex tools) showed no win over
  single-shot ask and never picked keyword/regex; wiring waits for a measured
  multi-hop failure and a keyword-query-shaped decision prompt.
- **Other answer models** (qwen3:4b-instruct, granite4.1 3b/8b) each failed one
  hard gate against this book's battery; `qwen2.5:7b` stayed until the
  fine-tuned students (x2d, x2g, x3) took over.
- **Late chunking and ColBERT** are vector-side tricks and cannot change the
  cited chunk text; unavailable under the stdlib and single-vector constraints.
