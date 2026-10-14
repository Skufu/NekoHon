# Ask This Book (epub-local)

An offline book companion. One EPUB is indexed on this machine, and questions
are answered from the book's own passages, with chapter citations and the
figures those passages point at. Retrieval and generation are local Ollama
models on `127.0.0.1:11434` — no cloud APIs, no database server, no pip
installs, no build step.

Repo: `nekolabs-studio/epub-local` (developed internally as `ask-this-book`).

**Status (2026-10-14):** v1 complete. Phases 0-7 pass, including the wifi-off
gate (2026-10-12). The answer model is the finetuned `smallbook_x2d` (see
Models below). 223 unit tests green, index audit clean, HTTP battery PASS. A
second book was probed end to end the same day — refusals transfer, and a
chapter-number ingest fix restored its citations
(`artifacts/reports/second-book-2026-10-14.md`). Post-v1 hardening continues;
evidence lives in `artifacts/`.

---

## Models currently used

| Job | Model | On disk | Notes |
| --- | --- | --- | --- |
| Embed | `nomic-embed-text:latest` | 274 MB | 768-dim. Won the embedder bake-off: 10/10 vs EmbeddingGemma-2's 9/10. |
| Answer | `smallbook_x2d` | 1.9 GB | The default for both answer modes since 2026-10-14 (adoption + the `[Ch. ` retry: `artifacts/reports/retry-safety-net-2026-10-14.md`): a Qwen2.5-3B quote-or-refuse LoRA distilled offline from `qwen2.5:7b`. `smallbook_x2` and the teacher stay on disk (1.9 GB / 4.7 GB); `ANSWER_MODEL=qwen2.5:7b` (or `=smallbook_x2`) reverts. Temperature 0. |
| Eval judge | `granite4.1:8b` local; `muse-spark-1.3-contributor` cloud | 5.3 GB local | The LLM judge (`artifacts/harnesses/judge.py`): passage relevance, key facts, book fidelity, example use. Local is the offline default; the eval runs currently use Muse Spark 1.3 over the OpenCode Go relay. Any stronger OpenAI-compatible model can be swapped in — `judge_name()` records it and `artifacts/harnesses/judge-agreement.py` re-calibrates. The engine never uses either. |

Also on disk, not defaults: `smallbook_x2d_q8` (3.3 GB, the 8-bit quant of
the default — one suite spot scored 20/160 vs the q4's 21/160 on the same
code; different items, no gain measured) and
`embeddinggemma-2:270m-bf16-text` (losing bake-off checkpoint, kept as
documented fallback). The bake-off losers (`granite4.1:3b`,
`qwen3:4b-instruct`) and `moistral` were deleted in the 2026-10-14
housekeeping. On the Mac runner, `llama3.2:3b` and `deepseek-r1:7b` are also
on disk; both are non-defaults there.

Typo safety: a question word that does not appear in the book gets a second
reading — difflib first, then one local qwen correction under the same
strict-improvement gate (case-only changes and token-count changes are
rejected) — and a kept reading is disclosed in the answer as `Read as: "..."`.

The answer model is a seam, not a lock: `ANSWER_MODEL=<tag> python server.py`
runs any pulled model through the same battery. A swap must pass the frozen
battery in both modes before it becomes the default.

## The book

One EPUB: *Fundamentals of Data Engineering*, Joe Reis & Matt Housley,
O'Reilly, 1st ed. 2022, ISBN13 9781098108250, `book_id` = `fde`.

The EPUB is **not in this repo** (`books/` is gitignored; `books/SOURCE.txt`
records where the local copy came from), and neither are the extracted figures
or the index (`data/` is gitignored). A fresh clone supplies its own copy of
the EPUB and rebuilds — see Quickstart.

Only this book is ingested, but the logic modules are book-agnostic by rule:
`tests/test_generalization.py` fails if any chunk id, figure id, chapter
number, query string, or book id leaks into them. A second book is a rebuild
plus a fresh bake-off, not a fork.

## How a question flows (the RAG process)

```
EPUB (fde.epub, one file)
  |
  v
ingest.py ......... sentence-boundary chunks (~300 tokens, sentence-aligned
  |                 overlap) + provenance (doc, section, figures); figures
  |                 extracted as files with caption + citing paragraph
  v
retrieve.py ....... nomic-embed-text vectors (768d) -> data/index.json;
  |                 pure-Python cosine; top 10 chunks (figures embedded too)
  v
question ---------> canonical form (bare phrase -> "What is X?")
                      |  then normalize -> dense top-10; when it fires, the
                      |  answer discloses `Asked as: "..."`
                      |  (A) word not in the book -> second reading: difflib
                      |      first, then a local-model correction under the
                      |      same strict-improvement gate (case-only and
                      |      length changes rejected); a kept reading is
                      |      disclosed in the answer as `Read as: "..."`
                      |  (B) word rare in the book -> strongest lexical
                      |      candidate fused by RRF (K=60), admitted only
                      |      inside the dense top 20% band (France canary)
                      |  (C) figure caption outscores the best chunk -> seed
                      |      the chunk that names that figure
                      v
                    smallbook_x2d (temperature 0)
                      |  answer: free generation, [Ch. N] tags -> citations,
                      |          quotation marks the passages cannot back are
                      |          stripped
                      |  ask:    quote + gloss; the quote check is the gate
                      v
                    post-checks (no model): heading trim, list-question
                    paragraph expansion, figures only from cited passages,
                    refusal is exactly `Not in this book.`
                      |
                      v
window/index.html . answer + citations + figure images
```

### Modes

| Mode | What you get |
| --- | --- |
| `answer` (window default) | A direct answer written from the retrieved passages. The model's `[Ch. N]` tags become citations, each matched back to a shown passage (chapter first, word overlap decides; zero-overlap claims get no citation). |
| `ask` | One checked quote starting with `[Ch. N]`, then one line of gloss. The quote must be backed by a shown passage, or the answer refuses. |
| `explain` | The highlighted selection is the question; same quote check. |
| `quiz` | One question plus the key sentence from one chunk. The window hides the key behind "Show the key". No scoring, no sparring. |

A refusal is exactly `Not in this book.` In `answer` mode the citation list
may still show the nearest misses. A figure attaches only when the answer
cited a passage that names it (refusal figures are labeled "nearby, not an
answer"). The answer never describes image pixels — it quotes text; the window
shows the image.

A bare phrase is asked as its question first (`canonical.py`): "watermark"
reaches retrieval and the model as "What is watermark?", and the answer
discloses it as `Asked as: "..."`. Explain is exempt — its highlight is a
book sentence, not a question.

Honesty is metered, not assumed: `artifacts/harnesses/groundedness.py` measures how much
of an answer is supported by the shown passages, and the eval harness
(`artifacts/harnesses/eval.py`) scores retrieval and answer quality against a labeled
set.

An `answer` question that asks for simple words ("explain data ingestion in
simple words", "eli5", "in plain terms") takes the plain register: the draft
answer selects the evidence sentences, each is rewritten one-in-one-out into
simpler words, and each citation keeps the original book sentence. Nothing is
written from scratch, so the register cannot invent a claim its sentence does
not carry. The architecture is measured, not asserted: draws under the
release judge scored 6, 7, 8 before the 2026-10-13 fragment fix and 9, 8
after it. Citation quotes are always whole book sentences, so a fragment
source cannot reach the rewriter — that class is fixed structurally, and the
remaining misses are single-item rewriter errors
(`artifacts/reports/plain-register-night-2026-10-13.md`, section 8).

## Quickstart (fresh machine)

Prereqs: Python 3 (3.12 tested, stdlib only), Ollama, and the EPUB on disk.
Models: `ollama pull nomic-embed-text` (274 MB, the embedder). The answerer
`smallbook_x2d` (1.9 GB) is **not** a registry pull — import it from its GGUF
(`ollama create smallbook_x2d -f <Modelfile>`; same recipe as
`artifacts/reports/smallbook_x2-rebuild-2026-10-14.md`, x2d run artefacts in
`artifacts/evidence/x2d-session-2026-10-14/`). `qwen2.5:7b`
(4.7 GB) is the teacher: needed only to rebuild the answerer or to revert
(`ANSWER_MODEL=qwen2.5:7b`).

```sh
# 1. Ollama is up (on Windows it is not on PATH; see AGENTS.md machine facts)
# 2. Book: put the EPUB at books/fde.epub (books/SOURCE.txt shows its origin)
python ingest.py      # EPUB -> data/index.json + data/figures/ (no vectors yet)
python retrieve.py    # embeds 1042 chunks + 111 figures via Ollama
python server.py      # serves the window + API on http://127.0.0.1:8000/
```

Then open <http://127.0.0.1:8000/> in a browser. On a Mac the interpreter
command is `python3`, and a friend-facing walkthrough (install, index, test)
lives in `SETUP-MACOS.md`.

`python preflight.py` checks every prerequisite — Python version, the EPUB,
the index, Ollama, the two models, and the vector audit — and prints the next
step. It exits 0 only when the machine is ready to serve.

One operational rule: the engine serves the code and model it loaded at
start. After a model change (`ANSWER_MODEL=...`) or any `*.py` edit, restart
the server; Ollama's `GET http://127.0.0.1:11434/api/ps` shows the model
actually loaded.

Machine-checkable equivalent (no browser needed):

```sh
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -d '{"book_id": "fde", "question": "What is a watermark?", "selection": null, "mode": "ask"}'
```

## Using the window

`window/index.html` — one file, no build step, no npm. `server.py` serves it
at `GET /` so the page and the API share an origin; there is no second server.

- Type a question in "Ask the book". Mode `answer` is the default; switch to
  `ask` for the quote-first presentation.
- "Highlighted text" is the selection box used by `explain`.
- `quiz` ignores the question box; press "Show the key" to reveal the key
  sentence after answering it yourself.
- Under the answer: citation chunk ids (on refusals, labeled "nearest
  misses"), then figures as images with captions.

Browser-check status: the window was first opened 2026-10-12; the ask path,
explain, and the quiz "Show the key" button were all clicked and verified the
same day. This Windows box cannot run the browser-automation tool (machine
facts in `AGENTS.md`), so window checks are manual; the curl calls above are
the automatable equivalent.

## HTTP contract (short)

One route set, frozen:

| Route | Returns |
| --- | --- |
| `POST /ask` | `{answer, citations[{chunk_id, chapter, quote}], figures[{id, chapter, caption, src}], refused}` |
| `GET /health` | `{ok: true, ollama: <localhost probe>}` |
| `GET /figures/{id}` | the extracted image bytes |
| `GET /` | the window |

`POST /ask` request: `{"book_id": "fde", "question": "...", "selection": null, "mode": "answer"}`;
`mode` is `answer`, `ask`, `explain`, or `quiz`. Bad mode or a missing field
returns `400 {"error": "short reason"}`. The full shape, including the refusal
rules, is locked in `BUILD_PLAN.md` ("Contract").

## Testing and automation

All commands run from the repo root. Start with `python preflight.py`: it
checks Python, the book, the index, Ollama, the models, and the vector audit,
and exits 0 when ready. Unit tests and the index audit need no network and no
Ollama; the rest need Ollama up, and the battery-style checks need
`server.py` running.

1. **Unit suite** — no Ollama, fast.

   ```sh
   python -m unittest discover -s tests
   ```

   210 tests, green (0.17 s on this box). Covers the contract, ingest and
   chunking, retrieval guards, fusion, readings, the answer checks, figures,
   the form canonicalizer, and the generalization guard.

2. **Index hygiene** — read-only audit of the stored vectors (width,
   non-finite, zero-norm, missing). Exits 1 when dirty.

   ```sh
   python verify_index.py
   ```

   Current: `nomic-embed-text`, 768 dims, 1042 chunks + 111 figures
   (1153 vectors), 0 offenders, clean.

3. **Retrieval smoke** — 10 fixture questions with known chapter answers;
   gate is 8/10. Needs Ollama.

   ```sh
   python retrieve.py --smoke tests/fixtures/questions.json
   ```

4. **HTTP battery** — 18 asks over HTTP in four lines: golden 10/10 answered,
   typo probes, rare-word probes, the France exact refusal. Needs Ollama plus
   a fresh `server.py`; confirm exactly one listener first
   (`netstat -ano | findstr :8000` — two servers can silently share :8000).

   ```sh
   python artifacts/harnesses/step2-battery.py
   BATTERY_MODE=answer python artifacts/harnesses/step2-battery.py   # answer mode
   ```

5. **Answer-model bake-off** — the same battery per candidate:

   ```sh
   ANSWER_MODEL=<tag> python server.py    # then run the battery
   ```

   Embedder bake-off, per contender (own index file, never `data/index.json`):

   ```sh
   python retrieve.py --smoke tests/fixtures/questions.json --embedder <tag> --index data/index.<model>.json
   ```

6. **QA sweep** — 303 asks in the user's question styles (journal logs +
   JSON):

   ```sh
   SWEEP_MODE=answer python artifacts/harnesses/qa-sweep.py <label>
   ```

7. **Groundedness meter** — share of answer sentences supported by the shown
   passages; in-process, no server needed:

   ```sh
   python artifacts/harnesses/groundedness.py --battery --label <name>
   ```

8. **Eval harness + LLM judge** — labeled-set evaluation (dense recall, shown
   recall, MRR, refusal classes, key facts). The LLM judge is
   `artifacts/harnesses/judge.py`: one-word verdicts at temperature 0. Local
   `granite4.1:8b` (cross-family with the answerer, offline, keyless) is the
   default; the eval runs currently use `muse-spark-1.3-contributor` over the
   OpenCode Go relay (key in `.judge-key`, gitignored, never read by the
   engine). Judges are swappable by design: if a stronger model is available,
   `judge_name()` records the judge in every output, and
   `harnesses/judge-agreement.py` re-calibrates it against the previous one before runs
   are compared. Verdicts are unvalidated against human labels.

   ```sh
   python artifacts/harnesses/eval.py --label v1
   python artifacts/harnesses/judge-agreement.py <run-a> <run-b>
   ```

9. **Secret scan** — every git blob in history plus the tracked tree, masked
   output, exits 1 on any hit:

   ```sh
   python artifacts/harnesses/secret-scan.py
   ```

10. **Wifi-off gate** — manual by design: unplug the network, confirm the
    offline probe (`https://example.com` returns `000`), then repeat the same
    `POST /ask` and check `netstat` shows localhost only. Recorded run:
    `artifacts/probes/phase7-offline.sh`, `artifacts/evidence/phase7-offline/phase7-offline.log`.

## Measured results ledger

| Date | Check | Result | Evidence |
| --- | --- | --- | --- |
| 2026-10-11 | Retrieval smoke (10 questions) | 10/10 top-10 (gate 8/10) | `BUILD_PLAN.md` "Phase 3" |
| 2026-10-11 | Embedder bake-off | nomic 10/10 stays; EmbeddingGemma-2 9/10 | `BUILD_PLAN.md` "Phase 3b" |
| 2026-10-12 | Wifi-off gate | unplugged: `example.com` -> `000`; same cited answer; sockets `127.0.0.1` only | `artifacts/evidence/phase7-offline/phase7-offline.log` |
| 2026-10-12 | HTTP battery (18 asks) | golden 10/10 answered; typos PASS; probes PASS; France exact refusal | `artifacts/evidence/step2-battery/step2-battery.{log,json}` |
| 2026-10-12 | Answer-model bake-off | qwen3:4b-instruct, granite4.1:3b, granite4.1:8b — none beats qwen2.5:7b; the 3b swap was reverted after the MAD phrasing probe | `artifacts/reports/answer-model-bakeoff-results.md`, `artifacts/reports/mad-phrasing-probe.md` |
| 2026-10-12 | Chunk-boundary audit + fix | mid-sentence chunk starts 373 -> 0; cut ends 25 -> 0; pins re-derived | `tests/test_chunking.py`, `AGENTS.md` state |
| 2026-10-13 | QA sweep, 303 asks (answer mode) | refusals 31 -> 33 -> 33 as stopwords + vendored stemmer reached the guard; junk refusals 18 -> 8 -> 4 | `artifacts/evidence/qa-sweep/qa-sweep-answer-*.{log,json}` |
| 2026-10-13 | Groundedness over the sweep | 204/911 sentences supported (22.4%), mean 0.272; answer-prompt A/B: close wording 26.3% vs open 15.3% | `artifacts/evidence/groundedness/groundedness-*.{log,json}` |
| 2026-10-13 | Eval harness, 24 labeled items | dense recall@10 17/22; shown recall@5 22/22; MRR@10 0.708; judged relevance 68/105 (unvalidated); cited share 0.327; false answers 0/2; false refusals 1/22 | `artifacts/evidence/eval-v1/eval-v1.{log,json}` |
| 2026-10-13 | Judge calibration | local granite vs cloud Muse agree 86/105 (81.9%); graded scales do not transfer across judges | `artifacts/evidence/judge-agreement/judge-agreement-*.log` |
| 2026-10-13 | Typo fallback wired (`readings.llm_second_reading`) | normilazation -> ch08-051, ingestoin -> ch07-002, both disclosed as `Read as:`; CRU keeps the difflib path; France and iops keep exact refusals; battery PASS in both modes | commit `f48910e` |
| 2026-10-13 | Index hygiene audit | 1153/1153 vectors 768-wide, 0 non-finite / zero / drifted; `verify_index.py` clean | `artifacts/evidence/embedding-audit/embedding-audit-2026-10-13.txt` |
| 2026-10-13 | Answer-mode quote choice (`_evidence_quote`) | a stray 41-char copied run no longer outranks a higher-overlap sentence; red->green regression test | commit `954860b` |
| 2026-10-13 | Bare-phrase canonicalization (Stage 1) | "MAD data landscape" alone: 3 figures -> 1, question-form behavior everywhere covered; batteries PASS both modes; window-confirmed; 5/5 mutation kills | commit `954860b`, `artifacts/reports/query-canonicalization-2026-10-13.md` |
| 2026-10-13 | Typography-fold A/B (index-rebuild decision) | 0/21 top-1 flips; rebuild rejected | `artifacts/evidence/probe-fold-ab/probe-fold-ab-2026-10-13.json` |
| 2026-10-13 | Finetune v1 checkpoint (`smallbook`, 1.93 GB Q4) | refusal sentence learned; runaway generation (174k chars / 354 s) and wrong quotes -> v2 recipe (responses-only loss) | `artifacts/reports/finetune-data-prep-2026-10-13.md` |
| 2026-10-13 | Finetune v2/v3 checkpoints (`smallbook` 1.9 GB, `smallbook_q3` 2.5 GB) | stopping + format fixed; bench 19/21 pins each (7B: 21/21); refusals lost — over-sampling landed same day | `artifacts/reports/finetune-data-prep-2026-10-13.md`, `evidence/probe-small-ask/probe-small-ask-2026-10-13.log` |
| 2026-10-13 | Finetune data v2 (refusal over-sampling x3) | train 194 = 113 answer + 81 refusal (27 refusal questions x3); bench 45 (43/2); verifier PASS, 0 failures | `artifacts/evidence/probe-finetune-verify/probe-finetune-verify-2026-10-13.{log,json}` |
| 2026-10-13 | Finetune x3 checkpoints: refusals fixed, loops found | refusals 2/2 exact on both (France, iops); 3B loops on some answers (source-systems 1-4/10 draws across settings; CRUD 4/5 at temp 0) -> sampler rejected, ratio retrain; Qwen3-4B over-refuses (2/21 pins), parked | `artifacts/reports/finetune-loop-eval-2026-10-13.md`, `artifacts/evidence/probe-small-refuse/probe-small-refuse-2026-10-13.model-*.log` |
| 2026-10-14 | Finetune x2/x1 session (trainer truncation bug fixed mid-session) | x2 wins: refusals 2/2, battery 18-19/21 (4 passes), 0 loops in 168 capped draws; x1 loops deterministically (10/10 insert-only); app default flipped to `smallbook_x2` for trial | `artifacts/reports/finetune-loop-eval-2026-10-13.md`, `artifacts/evidence/probe-llm-loop/probe-llm-loop-2026-10-13.*.log` |
| 2026-10-14 | Trial: user fragment-pattern queries (10, both models) | x2 false-refuses Location / DE Lifecycle / ddr4-vs-ddr5 where the 7B answers; "hey" answered via a reading repair (engine backlog: greeting/plural/degenerate-input guards) | `artifacts/evidence/probe-trial-queries/probe-trial-queries-2026-10-14.{json,log}`, `artifacts/reports/x2-trial-2026-10-14.md` |
| 2026-10-14 | Train/bench contamination audit | 0 exact duplicates; 4 near-twins of bench questions in train (ingestion, enterprise-architecture, pragmatic x2, codd) — those bench passes are assisted; gate adopted for every build | `artifacts/evidence/probe-contamination/probe-contamination-2026-10-14.{json,log}` |
| 2026-10-13 | Secret scan | 516 history blobs + tracked tree, 0 hits | `artifacts/harnesses/secret-scan.py` |
| 2026-10-13 | Unit suite | 210 tests green in 0.17 s | this tree |
| 2026-10-14 | x2d adoption + `[Ch. ` retry (user decision) | battery 20/21 x3 (best small-model run), refusals 10/10, 0 loops; the retry lifts the sealed suite x2d 21->111/160 and x2 60->111/160 (x2d 0 loops); gate item 2 still short of the 7B, recorded not hidden | `artifacts/reports/retry-safety-net-2026-10-14.md`, `artifacts/reports/x2d-plan-2026-10-14.md` |
| 2026-10-14 | Second-book probe + chapter fix | second EPUB (506 chunks): refusals transfer (0 false, controls exact); citations 2/11 tagged pre-fix; `ingest._chapter_number` fix (`chapter-4` -> `4`) + retest: x2 9/11 tagged / 3 PASS, x2d 8/11 / 5 PASS, every tag verbatim | `artifacts/reports/second-book-2026-10-14.md` |
| 2026-10-14 | Unit suite | 223 tests green (4 new) | this tree |

Flake note: the local model is not bit-exact across long sequential runs. A
known cold-run flake (the multicloud probe refusing while citing the correct
chunk) appeared on cold battery runs and cleared on a warm rerun every time. A
single red battery line is treated as suspect until it repeats.

## Offline proof

Phase 7 gate, 2026-10-12, wired machine: the Ethernet cable was unplugged for
the run. The offline probe (`https://example.com`) returned `000`; the same
watermark `POST /ask` still returned `refused: false` with the same cited
answer; `netstat` showed the engine and Ollama on `127.0.0.1` only, same PIDs
online and offline, no restarts. Raw log: `artifacts/evidence/phase7-offline/phase7-offline.log`.

Disclosure: embeddings and answers are Ollama on localhost; the models are
`nomic-embed-text` and — since 2026-10-14 — the finetuned `smallbook_x2d`
(1.9 GB; a Qwen2.5-3B LoRA distilled offline from `qwen2.5:7b`; set
`ANSWER_MODEL=qwen2.5:7b` to revert); no cloud model API. The finetune
track and its evidence:
`artifacts/reports/finetune-data-prep-2026-10-13.md`,
`artifacts/reports/x2-trial-2026-10-14.md`,
`artifacts/reports/retry-safety-net-2026-10-14.md`,
`artifacts/reports/smallbook_x2-provenance-2026-10-14.md`. Latency, recorded:
7B warm asks 0.4-1.2 s; `smallbook_x2d` warm probes ~0.5-2 s (no summary
yet); the first ask after ~5 min idle pays a one-time cold model load.

## Repo layout

```
ask-this-book/
  README.md          this overview
  BUILD_PLAN.md      the locked plan: contract, phases 0-8, bake-off tables
  AGENTS.md          hard rules + dated state log + verify commands
  SETUP-MACOS.md     friend-facing Mac walkthrough (install -> test)
  server.py          stdlib HTTP: GET /, /health, /figures/{id}; POST /ask
  ingest.py          EPUB -> sentence-boundary chunks (+provenance) + figures
  preprocess.py      the one text seam: tokens/words, normalize (NFKC/fold)
  retrieve.py        Ollama embed + pure-Python cosine + embedding guards
  keywords.py        rare-word postings, anchor words, the dense band
  fusion.py          RRF of the lexical candidate into the dense set
  captions.py        seed the chunk that names a matched figure
  readings.py        the self-proving second reading for out-of-book words
  answer.py          prompt wiring, generation, quote check, citations
  prompt.py          the system prompts (ask + answer) and ANSWER_MODEL
  figures.py         attach a figure only from a passage the answer cited
  verify_index.py    read-only index audit (exit 1 when dirty)
  preflight.py       setup checker: Python, book, index, Ollama, models
  agentic.py         agentic-retrieval prototype (not wired; see Limits)
  tests/             210 unit tests + fixtures
  window/index.html  the v1 window (no build step)
  vendor/            vendored SMART stopwords + Snowball Porter2 (BSD-3)
  artifacts/         evidence + tooling: the LLM judge (judge.py), the eval
                     harness, battery logs, sweeps, audits, reports
  books/             gitignored: the EPUB (SOURCE.txt records its origin)
  data/              gitignored: index.json + extracted figures/
```

## Limits and honest notes

- **The book, figures, and index are not committed** (copyright + size; the
  index measured 10,528,929 bytes on 2026-10-13). A fresh clone must supply
  its own copy of the EPUB and rebuild; a full re-embed measured 14.5 s on
  this box.
- **One book, one embedder at a time.** The index and the test pins are bound
  to `nomic-embed-text`; changing the embedder or the quant means a rebuild
  and a fresh bake-off. A new book triggers a fresh answer-model bake-off
  under the same frozen rules — the current default was measured against this
  book's index.
- `anchor` is empty for every chunk: this EPUB's headings carry no ids. The
  field stays wired for books that do.
- Digits are not tokens ("S3" reads as "s") — a documented limit, kept because
  the rare-word gate rides on the document frequencies.
- **France is the honesty canary**: "What is the capital of France?" must
  refuse exactly. The lexical boost can only promote a chunk inside the dense
  top 20% band; that band is the deciding gate, not a fitted word count.
- The **agentic retrieval prototype** (`agentic.py`) is not wired into the
  routes: on the five probe questions it took 3.1 s total with no measured win
  over the 0.5-1.2 s single-shot ask. Per project rules, it stays out until a
  measured multi-hop failure set exists.
- `quiz` has no scoring; a graded second call is out of scope (see
  `BUILD_PLAN.md` "Contract").
- **Finetune default: `smallbook_x2d`** (adopted 2026-10-14): a 1.9 GB
  Qwen2.5-3B quote-or-refuse model distilled offline from the 7B, plus the
  engine's validation-gated `[Ch. ` retry. Measured: refusals exact, battery
  20/21 ×3 (best small-model run), 0 suite loops, both ETL pin targets fixed.
  The pre-registered gate's sealed-suite bar is still unmet on bare-topic /
  order-flip (bare 41/50, order 20/40 vs the 7B's 50/50, 40/40, pre-retry
  bar) — recorded, not hidden: `artifacts/reports/retry-safety-net-2026-10-14.md`.
  Revert: `ANSWER_MODEL=qwen2.5:7b` (or `=smallbook_x2`). Provenance hashes:
  `artifacts/reports/smallbook_x2-provenance-2026-10-14.md` (x2 lineage; x2d
  run artefacts in `artifacts/evidence/x2d-session-2026-10-14/`).

## Roadmap

- Frontend (direction 2026-10-13, not approved): the app gets its own reader;
  citations become links that jump to the passage and highlight it. The
  external-reader hand-off is dropped; Readest is pattern inspiration (not a
  fork), ReadAny is the UX reference, and foliate-js is the candidate
  engine. Plan, locator strategy, and the open renderer decision:
  `artifacts/reports/frontend-navigation-plan.md`.
- Post-v1 backlog (not approved): quote figure captions in prompts;
  `keep_alive` on Ollama requests to remove the ~25 s cold load (cost: ~5 GB
  VRAM held).
- Finetune track: `smallbook_x2d` is the default (adopted 2026-10-14; the
  x2c session closed the same day — not adopted, sealed-suite bar vs the 7B,
  verdict in `artifacts/reports/x2-trial-2026-10-14.md`). Next data build:
  `artifacts/datasets/training-list-2026-10-14.md` (5 sealed targets; a sixth
  list item was engine-side — the chapter-number fix — and is done).
- Next book: a first portability probe ran end to end 2026-10-14 (refusals
  transfer; citations after the chapter fix; visible targets only). Full
  adoption still re-runs Phase 0-3 plus a fresh answer-model bake-off.

## Documentation map

- `BUILD_PLAN.md` — the locked plan: the contract, phases 0-8, the smoke and
  bake-off tables, the wifi-off note. (Previously this file was `README.md`.)
- `AGENTS.md` — agent entry point: hard rules, machine facts, the dated
  current-state log, and the verify commands.
- `artifacts/reports/how-it-works.md` — the pipeline as a one-screen mental image,
  plus what each stage kills and why.
- `SETUP-MACOS.md` — the macOS walkthrough for testers: native Ollama (not
  Docker), exact commands, and the gotchas worth knowing.
- `artifacts/reports/frontend-navigation-plan.md` — the recorded direction for the
  own frontend and citation navigation (not approved; needs a yes).
- `artifacts/datasets/demo-questions.md` — the questions that demo well and the ones
  that refuse, with pins.
- `artifacts/reports/answer-model-bakeoff-results.md`, `artifacts/evidence/eval-v1/eval-v1.*`,
  `artifacts/evidence/embedding-audit/embedding-audit-2026-10-13.txt` — the deep evidence behind the
  ledger above.

## License

GPL-3.0 — see `LICENSE`. The vendored text-preprocessing tools keep their own
licenses: the Snowball stemmer ships BSD-3 in
`vendor/snowballstemmer/COPYING`.
