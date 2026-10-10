# Ask This Book — Build Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** An offline book companion that answers from the open book, quotes the passage, and shows the figure that passage explains. Nothing leaves the machine.

**Architecture:** A stdlib Python engine ingests one EPUB into a JSON index, retrieves with on-disk `nomic-embed-text`, and answers with on-disk `qwen2.5:7b`. The window is one HTML file that calls that engine. Readest is a later shell, not the way the engine gets proven.

**Tech Stack:** Python 3 stdlib only. Ollama on `127.0.0.1:11434`. No pip installs. No new model downloads. No database server.

---

## Status

AppBuildersPH Devin Hackathon 2026 closed 10:00 AM PHT on Oct 10. This plan does not chase that form, the 1-minute video, the social post, or Demo Day.

The product bet stays. Local inference, cited answers, figures on screen, wifi off.

The public event page did not state a "half the score is local AI" rubric. That does not change the product. Do not rebuild the pitch around a score weight nobody confirmed.

Two older drafts in `~/.hermes/cache/scratch/hackathon-plan.md` and `hackathon-plan-full.md` disagree with each other. This file replaces both.

## Pitch (say this, not the other one)

"Ask this book offline. The model reads the text that explains the figure. You see the figure. Nothing leaves the machine."

Do not say "knows the pictures." `qwen2.5:7b` cannot see pixels. No vision model is on disk. Do not pull one.

Preemption, if someone names a cloud product: NotebookLM and Kindle Ask This Book need a network, and they can train on the library. This one does not leave the machine. It also does not see the ink. It reads the words around the figure and puts the figure on screen so a person can check.

## What v1 is

One local EPUB. Ask a question. Get a quote with a chapter tag, then one line of gloss. If the retrieved passage points at a figure, show that image with its caption. Highlighted text can be explained. Quiz is one question whose answer is a quote in the retrieved chunk.

The engine is the product. The HTML page exists so a person can see the quote and the image. Polish is not the work.

## What v1 is not

- The model looking at image bytes.
- Fusing several chapters into one synthesized answer.
- Sparring, "argue the other side," or any mode not in the contract.
- A Readest fork on the critical path.
- A new embedding model, a finetune, Laya, Bonsai, or `deepseek-r1:7b` (on disk, wrong job: it rambles past the quote).
- A database, a package install, or a cloud API.
- Cross-chapter tracing.

## Locked stack (verified on this Mac, 2026-10-09)

| Job | Model | On disk | Use |
| --- | --- | --- | --- |
| Embed | `nomic-embed-text:latest` (274 MB) | yes | retrieval |
| Answer | `qwen2.5:7b` (4.7 GB) | yes | quote, then one line |
| Weak-machine note | `llama3.2:3b` (2.0 GB) | yes | README fallback only. Not the dev model. |
| Do not use | `deepseek-r1:7b` | yes | leave it |

Ollama is already the server. Restart it only if `ollama list` fails. Do not `ollama pull` anything. Metered-data rule still holds: zero downloads without an explicit megabyte approval. That includes the Readest clone.

Run the engine with system `python3`, not the Hermes venv. If imports look insane, the shell leaked `PYTHONPATH` from a Python 3.14 env. Run `env -u PYTHONPATH -u PYTHONHOME python3`.

## Repo

Create: `~/workspace/github.com/Skufu/ask-this-book`

```
ask-this-book/
  README.md
  server.py          # stdlib HTTP
  ingest.py          # epub zip → chunks + figure records
  retrieve.py        # ollama embed + pure-python cosine
  answer.py          # prompt + ollama generate
  prompt.py          # the only system prompt
  store.py           # one JSON file
  tests/
    test_contract.py
    test_ingest.py
    test_retrieve.py
    fixtures/ask_response.json
  window/index.html  # the v1 window
  data/              # gitignored: index + extracted images
  books/             # gitignored: the epub, or a one-line path file
```

`.gitignore`: `data/`, `books/`, `__pycache__/`.

No `requirements.txt`. If a task seems to need a package, the task is wrong.

## Contract

This is the only meeting between engine and window. Check the fixture in before the live server exists. The window builds against the fixture.

`POST /ask`

```json
{
  "book_id": "fe",
  "question": "When is Darcy-Weisbach used for head loss?",
  "selection": null,
  "mode": "ask"
}
```

`mode` is `ask`, `explain`, or `quiz`.

- `ask`: `question` required. `selection` optional.
- `explain`: `selection` required. `question` may be empty.
- `quiz`: `question` empty on the first call. Response `answer` is one question. A second call sends the user's reply as `question` plus `"grade": true` is out of scope. v1 quiz is: server returns one question and the chunk quote that is the key. The page shows the key after the person answers. No model-assigned score.

`200` response:

```json
{
  "answer": "[Ch. 7] \"...exact quote...\"\nDarcy-Weisbach is the pipe formula in that passage.",
  "citations": [
    {"chunk_id": "c7-014", "chapter": "7", "quote": "exact quote"}
  ],
  "figures": [
    {
      "id": "fig-7-3",
      "chapter": "7",
      "caption": "Figure 7-3. Moody diagram.",
      "src": "/figures/fig-7-3"
    }
  ],
  "refused": false
}
```

`refused: true` means the passages do not contain the answer. `answer` is then exactly `Not in this book.` Citations may still list the nearest misses. Figures empty unless a miss is itself a figure cite. Do not gloss a refusal.

`GET /figures/{id}` returns the extracted image bytes. `GET /health` returns `{"ok": true, "ollama": true}` after a localhost probe to Ollama. No other routes.

Errors: `400` for a bad mode or missing field. Body: `{"error": "short reason"}`. No stack traces.

## Ingest rules

EPUB is a zip. Read `META-INF/container.xml`, then the OPF spine. One record per spine document.

Text chunks:

- Split on headings first. Do not split a table. If a table is longer than the chunk cap, it is still one chunk.
- Target ~300 tokens. Overlap ~40 tokens only when a section is longer than the cap.
- Keep the heading text at the start of each chunk from that section.
- Store `{chunk_id, chapter, heading, text}`.

Figures:

- Extract every image the chapter file references.
- Store `{id, chapter, caption, referencing_paragraph, file}`.
- Caption is the caption element if present, else the alt text, else empty string. Do not invent a caption.
- Referencing paragraph is the nearest paragraph that mentions the figure id, "Fig.", or "Figure". If none, store empty string.

Write `data/index.json` and images under `data/figures/`. The index must be reloadable with `json` from the stdlib. No pickle.

## Retrieval rules

Embed each chunk's `heading + text` with `nomic-embed-text` via Ollama. Embed each figure's `caption + referencing_paragraph` the same way. Store the vectors in the JSON index. 300 chunks fit in memory. Pure-Python cosine. Top 10 text chunks.

Attach a figure when either:

- a top-5 chunk's text cites that figure's id, or
- the figure's own embedding is in the top 5 figure hits and its score clears a floor set after the smoke test, not before.

Wide net is the mitigation for a small general embedder. Do not raise top-k past 10 to hide a bad question. Change the question.

## Generation rules

The model is a literate parrot with the book open. It quotes, then it glosses in one line. It does not merge chapters into a new essay.

System prompt, verbatim, in `prompt.py`:

```
You answer only from the passages below. If the passages do not contain the answer, reply with exactly: Not in this book.
Quote first. Start the quote with [Ch. N] using the chapter on that passage. After the quote, one line of gloss in simple words. Definition first if the passage defines a term.
Do not use a passage from a different chapter to fill a gap. If more than one passage applies, list one quote per passage. Do not fuse them.
Do not describe an image. You cannot see images. If a passage names a figure, quote that passage. The app will show the image.
```

User message is the question, then the top passages as plain text blocks with chapter and chunk id. For `explain`, the selection is the question and the retrieved neighborhood is the passages. For `quiz`, the prompt addition is: write one question a person could answer with a quote from the single best passage. Do not include the quote in that question.

Temperature 0. Do not sample a creative answer.

If the model does not start with `[Ch.` or `Not in this book.`, discard the completion and return `refused: true`. Do not show a free answer.

## Figure honesty

Showing the image is a window job. Discussing it is a text job. The answer may quote the caption and the citing paragraph. It may not claim it read the chart.

Before any figure is used in a rehearsal, open that figure's stored caption and referencing paragraph. If both are empty or the caption is only "Figure N", do not demo that figure. Pick another one that has a paragraph. Do not OCR a way out in v1. macOS Vision is on the machine and costs no download, and it still cannot read a Moody curve. Leave it out.

## Window

`window/index.html`. No build step. No npm.

- Question box, mode select (`ask`, `explain`, `quiz`), optional selection box.
- `fetch` `POST /ask` on the engine origin.
- Render `answer`, each citation quote, and each figure as an `img` whose `src` is the returned path.
- A checkbox or button that does not exist for DevTools theater. The proof is wifi off, documented in the README.

Serve the file from `server.py` at `GET /` so the page and the API share an origin. No second server.

## Proof it is local

Wifi off. Then `POST /ask`. A cited answer still returns.

Confirm the engine process has no established TCP connection except localhost. DevTools on the page only shows that the page is quiet. Ollama is a different process. Do not call a quiet network panel the proof.

README states: embeddings and answers are Ollama on localhost; models used are `nomic-embed-text` and `qwen2.5:7b`; no cloud model API; base models, no training.

## Roles

- Engine (Adrian): ingest, index, retrieve, answer, the HTTP contract.
- Window (teammate): `window/index.html` against `tests/fixtures/ask_response.json` first, then against the live `POST /ask`.
- Readest is nobody's job until the wifi-off gate passes, and only on unmetered wifi.

## Phase 0 — Book file, no download

**Done when:** `books/SOURCE.txt` contains one absolute path to an EPUB that is already on disk, and `unzip -t` on that path exits 0.

Look for the Fundamentals of Engineering EPUB on this machine. Do not search by walking the whole home directory. Check known project folders and ask only if it is not in the working set. If that file is not on disk, use another EPUB that is already local. Do not download a book. Do not buy one. Record the path and the title in `books/SOURCE.txt`.

If no local EPUB exists, stop. A download is a separate approval.

## Phase 1 — Fixture and empty server

**Done when:** `python3 -m unittest tests.test_contract -v` passes, and `GET /health` returns `ollama: true` with wifi on (Ollama is local; this check is the server, not the product proof).

Files:

- Create `tests/fixtures/ask_response.json` with the sample object in the contract section.
- Create `tests/test_contract.py`. It loads the fixture and asserts the keys `answer`, `citations`, `figures`, `refused`.
- Create `server.py` with `GET /health` and `POST /ask` returning the fixture unchanged. Real retrieval comes later. The route shape does not change later.

Verify:

```bash
cd ~/workspace/github.com/Skufu/ask-this-book
env -u PYTHONPATH -u PYTHONHOME python3 -m unittest tests.test_contract -v
```

Expected: pass.

## Phase 2 — Ingest

**Done when:** ingest writes `data/index.json`, chunk count is greater than 0, every figure record has `id`, `chapter`, `caption`, `referencing_paragraph`, `file`, and a sample chapter's text contains a heading you can see in the EPUB.

Test: `tests/test_ingest.py` uses a tiny fake EPUB built in the test with `zipfile` (one chapter, one heading, one table, one image, one caption). Assert the table is one chunk. Assert the image record has the caption and the citing paragraph. Do not use the real book as the unit fixture.

Then run ingest on the real book and print chunk count, figure count, and three captions. Read those captions. That printout is the evidence, not a feeling that ingest worked.

## Phase 3 — Retrieval smoke test, before any demo question is locked

**Done when:** 10 questions with known chapter answers are written in `tests/fixtures/questions.json` as `{"q", "chapter", "must_contain"}`, and a script prints hit or miss at top-10. At least 8 of 10 hit. Misses get a new question or a chunking fix. They do not get a higher top-k.

Include at least three kinds:

- A definition that lives in one section.
- A formula whose name and its "when to use" sentence are in the same section. If they are not in the same section, that question is illegal in v1. Do not ask the model to fuse.
- A figure question whose citing paragraph is non-empty. If the Moody chart's citing paragraph is empty, that chart is not a test question.

`tests/test_retrieve.py` can stay on the tiny fixture (one embedded vector mocked, or a fake embed function). The 10-question run is a manual script against Ollama, `python3 retrieve.py --smoke tests/fixtures/questions.json`. Save the printed hit/miss list in the README. Do not invent a hit.

## Phase 4 — Quote-first answers

**Done when:** for 3 smoke-test hits, `POST /ask` returns a quote that is a substring of the cited chunk, the answer starts with `[Ch.`, and a question whose answer is not in the book returns exactly `Not in this book.`

Wire `retrieve.py` and `answer.py` into `POST /ask`. Delete the fixture return from that route. Keep the fixture file for the window.

Reject completions that do not start with `[Ch.` or `Not in this book.`

## Phase 5 — Figures on the page

**Done when:** a question whose top passage cites a figure returns that figure in `figures`, `GET /figures/{id}` returns image bytes, and the HTML page shows the image under the quote. The answer text still does not describe the pixels.

## Phase 6 — Explain and quiz

**Done when:** `explain` with a selection returns a quote from the neighborhood of that selection, and `quiz` returns one question plus the key quote from a single chunk. No score. No sparring.

Do not start this phase if phase 3 is under 8/10.

## Phase 7 — Wifi-off gate

**Done when:** wifi is off, `POST /ask` still returns a cited answer, and the engine's established TCP sockets are localhost only.

Write the command and the result in the README. That note is the disclosure. No Cognition tag. No hackathon form.

## Phase 8 — Readest, only after phase 7

Not scheduled until the gate passes.

Clone Readest on unmetered wifi only. Side panel calls the same `POST /ask`. The engine stays a separate process. AGPL stays on the fork. The engine repo does not become AGPL by being imported into the Tauri app.

If `cargo tauri` is missing, stop. The HTML window remains the product shell. Do not spend a day on the toolchain.

## Risks

| Risk | What to do |
| --- | --- |
| Small embedder misses a technical phrase | Top-10, small chunks, section splits. Then change the question. |
| 7B writes a essay instead of a quote | Discard the completion. Temperature 0. The format check is the product. |
| Equations or tables split mid-row | Split on sections. Tables stay whole. |
| Figure demo is an empty caption | Read the stored caption first. Pick a different figure. |
| Readest eats the week | It is phase 8. The HTML page is the shell. |
| Someone pulls a vision model "just to try" | No. Metered data. And it would change the pitch. Do not change the pitch. |
| Metered-data download of the book or the clone | Stop. Approval is a number of megabytes, before the transfer. |

## Done

v1 is done when phases 0 through 7 pass on the book in `books/SOURCE.txt`, the README has the smoke-test hit list and the wifi-off note, and the page can ask, explain a selection, show a figure that has a real citing paragraph, and quiz from one chunk.

Phase 8 is a sequel. It is not required for the product to be real.
