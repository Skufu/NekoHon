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
     ingest, rebuild the index, re-run this probe. One change, one re-run —
     done same day; see the retest section at the end.

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

## One-change retest — the chapter-number fix (same day, 2026-10-14)

The identified one change: `ingest._chapter_number` now keeps only the number
of `chapter-4`-style spine ids (`ch(?:apter)?[\s_-]*(\d+)`, case-insensitive),
so the prompt tag reads `[Ch. 4]`; `chunk_id`s are unchanged (`chapter-4-004`,
the probe's gold ids still apply). Index rebuilt from scratch (506 chunks),
probe re-run on the same questions through the shipped `answer.respond` path
(retry included), models `smallbook_x2` (the pre-fix student) and
`smallbook_x2d` (current default; the 7B was not re-run). Evidence:
`evidence/probe-second-book/probe-second-book-2026-10-14.chapternum.{json,log}`.

| model | in_book (10) | bare_form | control (3) | non-control answers tagged |
| --- | --- | --- | --- | --- |
| smallbook_x2 | 3 PASS / 7 PARTIAL / 0 FAIL | PASS | 3/3 exact | **9/11** (pre-fix: 2/11) |
| smallbook_x2d | 5 PASS / 5 PARTIAL / 0 FAIL | PASS | 3/3 exact | **8/11** |
| qwen2.5:7b (pre-fix, for scale) | 8 PASS / 2 PARTIAL | PASS | 2/3 (France answered) | — |

Reads:

1. The tag shape was the majority cause. Same questions, same engine: uncited
   prose became `[Ch. N]` tags — x2 9 of 11 non-control answers tagged (was
   2 of 11). Every tag that came is a verbatim quote from a shown passage
   (`quote_verbatim` true on all 17 tagged rows across both models).
2. PARTIALs are not all equal. `ste`'s cited passage (chapter-5-022) is the
   real one — the pre-drafted gold set was wrong there (noted pre-fix);
   `zeropoint`'s gold set is likewise known-wrong and x2's answer cites three
   real chapter-2 chunks. Against corrected golds both in_book PASS counts
   would sit higher; the table keeps the probe's recorded numbers.
3. Remaining uncited: `cliff` and `granular` (both models), `zeropoint` (x2d
   only) — the known wart class (free prose, no tag) on unseen content, now
   rarer. Against the 7B's pre-fix 8/10 the students' 3/5 stay short on this
   visible ten; it is still not a suite, n=1 per item.
4. The France hallucination stays a teacher-only record; both students refuse
   all three controls exactly, no refusals among the in-book ten.
