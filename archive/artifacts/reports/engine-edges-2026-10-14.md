# App-edge failures, measured 2026-10-14

Investigation only; no engine file changed. One command per finding:
`python artifacts/probe-engine-edges-2026-10-14.py a|b|c|d [--answer]` (d is stubbed, no real 120 s wait). App lines quote `probe-trial-queries-2026-10-14.log`.

## (a) `hey` is read as `they` and answers an RDBMS passage

Measured (case a): `canonical_query("hey")` → `"hey"` (opener, `canonical.py:27-31`); df(`hey`)=0, so `_fixes` considers it; `_closest` → SequenceMatcher **0.8571** to `they` (one inserted `t`), runner-up `he` 0.8000 — cutoff `0.85` (`readings.py:55`) passed, unique top. Literal top **0.5617** `ch05-030` (RDBMS); repaired reading `they` **0.6022** `preface01-016`, delta **+0.0405**; gate `ranked[0][0] > literal_top` (`readings.py:210`) keeps it. Repair source: **difflib, no model** — `answer.py:496` runs `second_reading` first, and with a raise-on-model `generate_fn` the whole `retrieval_context` completes, so `llm_second_reading` never runs. Live: `refused=False`, RDBMS text, `Read as: "they"`; trial log line 3-4 matches (cited `ch05-030`).

Why a greeting qualifies:

1. `hey` is out-of-book (df=0), and the repair path needs only one candidate.
2. On a 3-letter token, one insertion gives 0.8571 ≥ 0.85; short words clear the cutoff almost automatically.
3. The gate passes because `they` is a book-wide function word; matching one preface chunk raises cosine by +0.0405.
4. The system reads +0.0405 as a better reading; it is embedding noise, not topic match.
5. `Read as:` is printed after generation, so it cannot stop the wrong answer.

Candidate guards (testable rules, not word lists):

- **G1 minimum token length:** in `_fixes`, skip `len(word) < 4`. Failure mode: it kills the documented `CRU → CRUD` fix (delta +0.110; `readings.py:26-29`), a measured win — G1 alone regresses.
- **G2 improvement margin:** keep only when `ranked[0][0] - literal_top >= MARGIN = 0.05`; blocks `hey` (+0.0405), keeps `atermark` (+0.244) and `CRU` (+0.110). Failure mode: the constant is fitted — one absurd fix is not a noise floor; a genuine +0.03 fix would be dropped. A sharper variant (unnumbered here): never repair *to* a stopword target.

## (b) `speed of ddr5s` never repairs

Measured (case b): canonical `"What is speed of ddr5s?"`; `tokens` → `what, is, speed, of, ddr, s` — `[A-Za-z]+` (`preprocess.py:52`) drops digits, so `ddr5s` splits into `ddr` + `s`. All six are book words (`ddr` df=1, `s` df=477, `speed` df=25), so `_fixes` → `[]`, and the LLM gate (`any(word not in word_map)`, `readings.py:160-162`) sees `out-of-book tokens = []` and returns `None` before any model call (the raising stub proves it). Counterfactuals: `ddr5s/ddr5 = 0.8889` (> cutoff) but `ddr5` is not in the vocabulary (book `DDR5` also tokenizes to `ddr`); `ddr5s/ddr = 0.7500` < 0.85. Retrieval already leads with the right passage (**0.6528** `ch06-011`), yet both models refuse (live `smallbook_x2`: `refused=True`, cited `ch06-011/006/009`, matching log line 19). Root cause: the tokenizer erases the distinctive digit, so the plural is invisible as OOV. A digit-aware fix moves every df count on both index sides (`tokens()` docstring warns); not proposed here.

## (c) degenerate `what is`

Measured (case c): canonical unchanged (WH match, `canonical.py:48`); `words = [what, is]`, both stopwords, **content words = 0**; no repair (both in `word_map`; LLM gate pre-empts); the model receives `Question: what is` verbatim, top passage **0.7405** `ch05-045`. Live: `refused=False`, answering the `Queries` passage (log line 1-2). Proposed rule: after canonicalization, if `[w for w in words(q) if w not in STOPWORDS] == []`, do not call the answer model — return the refusal or an echo-clarification. Probe check (case c prints it): fires on `what is` only; `hey` and the five fixture questions do not fire:

| q | content words |
|---|---|
| what is | (none) |
| What does CRUD stand for? | crud, stand |
| What is data ingestion? | data, ingestion |
| What is a watermark? | watermark |
| When is an insert-only table useful? | insert, table |
| Where does storage sit in the data engineering lifecycle? | storage, sit, data, engineering, lifecycle |

Scope honesty: this rule cannot catch `hey`; (a) needs its own guard.

## (4) 120 s timeout → HTTP (read-only)

`answer.ollama_generate` sets `timeout=120` (`answer.py:110`) on `urlopen` (`answer.py:126`); `options` carry only `temperature: 0` (`answer.py:115`), no `num_predict`, so the 120 s socket clock is the only generation bound. On expiry the body read raises `TimeoutError`; the urlopen phase wraps it as `URLError(TimeoutError)`. `server.do_POST` wraps the mode call in `try` (`server.py:110`); `server.py:122-124` catches `(urllib.error.URLError, TimeoutError, RuntimeError)` and returns **HTTP 500 `{"error": "answer model unavailable"}`** — no partial text, never `Not in this book.` Case d measured all three shapes → identical 500. Whether Ollama aborts generation server-side on client disconnect is unverified. This feeds the no-output-cap backlog item.

## Uncertainty

- Dense deltas come from nomic + this index; not a noise-floor estimate.
- G2's 0.05 is chosen against one measured absurd fix; validate before shipping.
- App quotes are one temperature-0 run each; citation tags differ between runs (live `hey` cited nothing; log cited `ch05-030`).
