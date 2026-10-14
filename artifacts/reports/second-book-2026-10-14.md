# Second-book portability probe — 2026-10-14

`GOAL.md` says the companion "should hold for other books, not only this one."
This is the first measurement of that claim: the same engine, a book it has
never seen.

**Book:** "Quantization and Fast Inference" (Vivek Kalyanarangan) — Anna's
Archive copy, local only at `books/quantbook.epub` (gitignored; not
redistributed). 506 chunks, **0 figures** — the figure path is untested on a
second book. Index: `data/index.quantbook.json` (nomic-embed-text), built by
the unchanged `ingest.py` + `retrieve.embed_index`. First index ever built
from a second book. Ingest note: the chapter strings are `chapter-4`, not
`4` (`_chapter_number` found no number in this EPUB's doc ids) — this matters
in finding 2.

**Pre-registered read** (in the probe docstring, written before the run):
in-book questions pass across the board -> behavior transfers; in-book
refusals -> the finetune is FDE-shaped; controls answered -> contamination.
**Pass rule:** control = refused AND answer exactly `Not in this book.`;
in_book / bare_form: FAIL = refused; PASS = not refused AND a gold chunk
cited; PARTIAL = not refused, no gold cited. The 10 in-book questions are
**visible targets** — same rule as the x2 trial: they are not a suite and
cannot gate anything.

**Run:** `python artifacts/probes/probe-second-book-2026-10-14.py` (answer
mode through `answer.respond`, temperature 0, one run per question; models
`smallbook_x2` and `qwen2.5:7b`). Evidence:
`evidence/probe-second-book/probe-second-book-2026-10-14.{json,log}`.

## Results

| model | in_book (10) | bare_form (1) | control (3) |
| --- | --- | --- | --- |
| smallbook_x2 | 0 PASS / 10 PARTIAL / 0 FAIL | PARTIAL (answered, uncited) | 3/3 PASS, exact |
| qwen2.5:7b | 8 PASS / 2 PARTIAL / 0 FAIL | PASS | 2/3 PASS — France answered |

Warm asks: x2 0.8–1.2 s; 7B 1.7–4.5 s (longer answers). Cold first asks:
4.2 s (x2), 16.7 s (7B).

## Findings

1. **The refusal boundary transfers.** x2 refused zero of ten in-book
   questions on a book it has never seen and refused all three controls
   exactly. The x2-trial wart class (Codd / Location / DE Lifecycle) did not
   reproduce here. n=1 per item.

2. **Citations do not transfer — the real finding.** x2 tagged 2 of 11
   non-control answers; the other 9 answered substantively from the book with
   no `[Ch.` tag at all (verified on the full ptq answer, 357 chars, and by a
   tag scan across rows in the evidence). For ptq the gold chunk was shown at
   rank 2 of 5 and the answer kept its facts ("minutes to hours, not days") —
   no tag came. In the app contract an untagged answer is uncited: no passage
   link, no figure. Where tags did come (`ste` -> chapter-5-022 with the
   Bengio attribution; `zeropoint` -> chapter-2-074 with the Z formula), the
   citations were real and correct — the pre-drafted gold sets were wrong
   there, not the model.
   - **Hypothesis (recorded, not fixed):** the prompt shows `[Ch. chapter-4]`,
     not `[Ch. 4]` — off-distribution from the tag shape the FDE training
     rows taught. One change to test it: extract the chapter number in
     ingest, rebuild the index, re-run this probe. One change, one re-run.

3. **The teacher hallucinated on the new book.** "What is the capital of
   France?" -> `The capital of France is Paris. [Ch. 4]` — answered, and the
   fabricated citation pinned to chapter-4-022, which contains the literal
   string "What is the capital of France?" as a calibration-prompt example
   (`short_factual`, Listing 4.2). The student refused; the teacher did not.
   The student-vs-teacher ranking from the FDE trial is not safe to assume
   across books.

4. **The bare-form wart did not reproduce:** `post-training quantization`
   (bare) answered by both models.

## What this changes

- The engine is book-agnostic end to end: ingest -> embed -> search -> answer
  ran on a foreign EPUB with zero code changes, warm asks ~1 s.
- "Hold for other books" is now measured once: refusal behavior travels;
  citation behavior is the first measured portability gap, with a
  one-change retest already identified.
- Figure path: untested (this EPUB has no figures).

Caveats: visible targets; n=1 per question; gold sets were grep-drafted
pre-run and wrong in two known places (ste, zeropoint); the source EPUB is
not redistributed and stays gitignored with the FDE book.
