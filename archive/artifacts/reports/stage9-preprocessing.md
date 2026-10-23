# Stages 5-9 preprocessing — evidence (2026-10-13)

Scope: make text-processing stages 5-9 (text processing, punctuation,
tokenization, stop words, stemming) real, standard, and measured. New views
only — `preprocess.normalize` (dense path) and `words()` (lexical path) keep
their exact behavior; nothing in `keywords.py`/`fusion.py` is rewired yet.

Hard rule restated: `chunk["text"]` is canonical. Every function below is a
view over text; none writes back.

## Stage map

| Stage | Behavior | Code | Source |
|---|---|---|---|
| 5 text processing | NFKC + whitespace fold (dense); NFKC + typography repair + casefold (matching) | `normalize()` unchanged; new `fold()` | stdlib `unicodedata` |
| 6 punctuation | punctuation never becomes a token; text never rewritten | `tokens()` unchanged | existing `[A-Za-z]+` |
| 7 tokenization | the single tokenizer, both index and query side | `tokens()` / `words()` unchanged | existing regex |
| 8 stop words | 570-word SMART list, filtered in matching views | new `STOPWORDS` | `vendor/stopwords-en.txt` (header names source) |
| 9 stemming | Snowball English (Porter2) stemmer | new `stem()`, `stemmed_words()` | `vendor/snowballstemmer/` 3.1.1, BSD-3-Clause, `COPYING` next to it |

## Planned downloads (recorded BEFORE pulling)

| # | Artifact | Source | Approx size (planned) |
|---|----------|--------|----------------------|
| 1 | `snowballstemmer` wheel (PyPI) | https://pypi.org/project/snowballstemmer/ — pure-Python Porter2 (Snowball English) + other languages, BSD-3-Clause | ~0.1 MB (wheel) |
| 2 | English stopword list | Snowball English stop list planned first (https://snowballstem.org/algorithms/english/stop.txt, ~1-2 KB) | tiny |

The stop list source changed during the pull — see "Why SMART". Nothing else
was downloaded. Bundled runner/models already on disk were not touched.

## Downloads, measured

- `snowballstemmer` 3.1.1 **wheel: 104,164 bytes** (PyPI JSON API for the
  3.1.1 release; sdist 123,314 bytes, not used). Installed with
  `python -m pip install snowballstemmer`, then vendored; **the pip copy was
  uninstalled afterwards** and the suite re-run green from the vendored copy
  alone (proof below).
- SMART stop list raw download: **3,589 bytes** (`curl -fsSL <url> | wc -c`),
  571 lines, 570 unique — upstream lists `would` twice; kept verbatim, the
  frozenset deduplicates.
- Vendored into the repo (final): 39 `.py` files **766,688 bytes** +
  `COPYING` **1,630 bytes** + `stopwords-en.txt` **4,615 bytes** (header +
  571 words) = **772,933 bytes** of source. File set verified identical to
  the installed distribution's `RECORD` (only intentional extras: `COPYING`,
  generated `__pycache__`).

### Why SMART and not the Snowball stop.txt

The Snowball English stop list was fetched and read first. It is clean but it
does **not** contain "actually" — the standard list there is 174 function
words (pronouns, auxiliaries, articles, prepositions). The requirement for
this stage names "actually" explicitly, so a list that covers it was needed.
The SMART list (Salton's group, Cornell, 1960s — the classic IR stop list,
571 words) contains `actually`, `the`, `what`, `would`, and contains none of
`extract`, `watermark`, `data`, `storage`, `pipeline` (checked, output in
(b)). It is vendored as data with its provenance in the file header.
Rejected runner-up: stopwords-iso English (7,677 bytes, 1,298 words, MIT) —
same membership answers, but 2.3x the filter size and a younger compilation.

## (a) stemming: the standard Snowball (Porter2) stemmer

Command: `python artifacts/probe-stages.py` (offline, reads `data/index.json`
read-only). Verbatim excerpt:

```
== (a) stemming: the standard Snowball (Porter2) stemmer ==
   stem('extracted') = 'extract'
   stem('extract') = 'extract'
   stem('extracting') = 'extract'
   published Porter2 example families:
   consigned    -> consign      (ok)
   consigning   -> consign      (ok)
   consignment  -> consign      (ok)
   relational   -> relat        (ok)
   generously   -> generous     (ok)
   ties         -> tie          (ok)
   tied         -> tie          (ok)
   tying        -> tie          (ok)
   skies        -> sky          (ok)
   skis         -> ski          (ok)
   news         -> news         (ok)
   dying        -> die          (ok)
   idempotent on all probe words (stem(stem(w)) == stem(w)): True
   book-relevant families collapse too:
   ingest/ingesting/ingested/ingestion -> {'ingest'}
   transform/transforming/transformed/transformation -> {'transform'}
   stream/streaming/streamed/streams -> {'stream'}
```

The (ok) column are the published Porter2 example families and the
algorithm's documented exceptions (`ties/tied/tying`, `skies/skis`, `news`,
`relational`), computed by the vendored stemmer — not hard-coded. The
implementation is the standard one: `vendor/snowballstemmer/english_stemmer.py`
is generated from `english.sbl` by Snowball 3.1.1 (its own header says so).

## (b) stop words: the SMART list

Verbatim excerpt from the same probe run:

```
== (b) stop words: the SMART list ==
   STOPWORDS: 570 words (vendor/stopwords-en.txt)
   actually   in STOPWORDS: True
   the        in STOPWORDS: True
   what       in STOPWORDS: True
   would      in STOPWORDS: True
   extract    in STOPWORDS: False
   watermark  in STOPWORDS: False
   data       in STOPWORDS: False
```

## (4) NFKC in the matching fold

Verbatim excerpt:

```
== (4) fold: NFKC + typographic punctuation to ASCII ==
   'the book’s “ﬁle” — done' -> 'the book\'s "file" - done'
   equals the straight-ASCII form: True
   fold is idempotent: True
```

`fold()` = NFKC + a six-entry translation (curly quotes, curly apostrophes,
en/em dash) + `casefold()`. NFKC alone does not touch U+2019 or U+2013, which
is why the translation table is there; NFKC does the ligature (`ﬁ` → `fi`).
`words()` and `normalize()` do not adopt this view (that would move every df
count and every stored vector) — `fold` is the proposed matching fold.

## (c) real index: stemmed word map over `data/index.json`

Verbatim excerpt (index is 1,042 chunks):

```
== (c) real index: raw word map vs stemmed word map ==
   index.json: 1042 chunks
   content-word keys: raw 7809, stemmed 4920
   map build: raw 116 ms, stemmed 3257 ms
   document frequencies BEFORE stemming, one entry per surface form:
     df('extract') = 14
     df('extracted') = 4
     df('extracting') = 5
     df('extraction') = 9
   AFTER stemming, one entry for the family:
     df('extract') = 29
     stemmed set == raw family union: True
     example chunks in the family: ch01-075, ch02-022, ch02-023, ch02-028, ch03-007, ch03-058
   control: 'watermark' is not a stopword and stems to itself; raw df(watermark)=1, df(watermarks)=2 -> stemmed df(watermark)=2 (surface forms ['watermark', 'watermarks'] merged, none swallowed)
   question 'how is data extracted'
     raw term df('data') = 933
     raw term df('extracted') = 4
     stemmed term df('data') = 933
     stemmed term df('extract') = 29
   stem throughput: 151656 tokens in 3823 ms (39,671 tokens/s)
   stem only the 8244 unique keys: 241 ms (the map-build cost that matters; cache it once per process)
```

Notes, measured:
- 14 + 4 + 5 + 9 = 32 surface-form positions collapse to a 29-chunk family:
  the stemmed map is exactly the union (set equality True; the difference is
  chunks that use two forms of the family).
- Key count 7,809 → 4,920: stemming merges inflections, it does not swallow
  content words (the watermark control keeps both its surface forms merged
  under their own stem).
- Cost: stemming every running token is ~3.2-3.8 s over the book, but the
  map only needs the 8,244 unique keys — 241 ms — and that is a one-time
  cost if cached per process. `fold` itself is negligible (~94 ms over
  151,656 tokens). Raw postings cost ~0.1 s.

## (d) Proposed wiring (NOT applied)

Exact signatures proposed for a later, battery-gated change:

```python
# preprocess.py (new one-liner, added at wiring time)
def content_stems(text):
    """Stage 8+9 view: stemmed words minus stop words."""
    return [w for w in stemmed_words(text) if w not in STOPWORDS]

# keywords.py (view threaded through, default preserves today exactly)
def postings(index, view=words): ...
def anchor_words(question, word_map, bound=COVER_DF, view=words): ...
def rare(question, word_map, bound=RARE_DF, view=words): ...

# call sites
table = keywords.postings(index, view=content_stems)
anchors = keywords.anchor_words(question, table, view=content_stems)
```

The index map and the question must use the SAME view — the symmetry rule
already in `preprocess.py`. Default stays `words`, so wiring is one keyword
argument at the call sites in `answer.py`.

Predicted battery impact (predictions, not measurements — no run was made):
- `rare()` (df ≤ 8) fires strictly differently: "extracted" is df 4 today,
  but its stem `extract` is df 29, so an inflected rare word typed in a
  question would stop firing the gate (df 29 > 8) while its base form keeps
  firing. Questions whose word is rare only in one inflection flip either
  direction; the pins that ride on this gate are the pragmatic (ch04-012),
  MAD (ch04-020), and multicloud (ch04-037) probes.
- `anchor_words()` (df ≤ 80) gains cross-inflection matches
  (question "disadvantages" can anchor a paragraph that says "disadvantage").
  The paragraph-cap path in `answer.py` fires more often — re-run the full
  18-ask battery and inspect the quote of every changed ask, not just pins.
- France: `stem("france")` = "franc". No "franc*" content exists in this
  book (the family probe found only the watermark pair; nothing else merged
  with it), but the admission band in `fusion.py` remains the deciding gate
  by design — do not rely on the stem's absence alone.
- Cost: cache `content_stems` map once per process (~0.25-0.35 s build);
  building it per ask at ~3.3 s is unacceptable against warm asks of 0.5-1.2 s.
- Stopword filtering removes question words like "actually" from the gate and
  anchor sets; harmless where their df is above the bounds, a behavior change
  where it is not. Measure before keeping.

## (e) test suite

Command: `python -m unittest discover -s tests`

```
Ran 128 tests in 0.072s

OK
```

113 before this change, 128 after; the 15 new tests are in
`tests/test_text_stages.py` (fold idempotence/typography/NFKC, stopword
membership both ways, stemmer families, documented Porter2 exceptions, case
folding, idempotence, fold-before-tokenize ligature case). The pip copy of
`snowballstemmer` was uninstalled before this run: the suite is green on the
vendored package alone, `import snowballstemmer` fails. No network, no
Ollama, no HTTP battery.

## Notes and open questions

- Known stemming limits, measured: `storage` → `storag` while `storing` and
  `stored` → `store` (no merge); `runner` does not merge with `run`
  (`running`/`runs` do). These are standard Porter2 behaviors, not bugs —
  the wiring prediction must live with them.
- `answer.py` has its own typography fold in the quote check (curly quotes).
  Consolidating it onto `preprocess.fold` is a separate, reviewed change —
  not this task, and not proposed silently here.
- The stop list covers the requirement's examples; whether the SMART list is
  the right size for a book about data engineering (it filters `value`,
  `use`, `need`) should be part of the wiring measurement, not assumed.
