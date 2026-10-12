# How ask-this-book works — mental image (2026-10-12)

## The pipeline, end to end

```
             your question (typos and all)
                        |
                        v
    +--- INGEST: the book is cut on sentence boundaries ---------------+
    |    373 of 1013 chunks used to start mid-sentence; now 0          |
    |    every chunk carries doc, section, heading and its figures      |
    +---------------------------+---------------------------------------+
                                |
    +--- SEARCH: the question through nomic vectors -------------------+
    |    the 5 closest passages + scores                                |
    +---------------------------+---------------------------------------+
                                |
   (A) second reading?          |  (B) rare-word boost?
   a word not in the book       |  the question holds a word that is
   and one clear close book     |  rare in the book -> the best-overlap
   word -> the reading becomes  |  chunk replaces the weakest passage,
   the question, kept only if   |  but only if it sits inside the dense
   it scores strictly better;   |  top 20% of the corpus (pragmatic)
   the answer discloses it as   |  (C) caption seed: a caption that beats
   `Read as: ...` (CRU,         |  the best chunk seeds the chunk naming
   atermark)                    |  that figure (MAD data landscape)
                                v
    +--- QWEN: writes ONE sentence + one gloss line -------------------+
    |    prompt untouched; five steering experiments are dead           |
    +---------------------------+---------------------------------------+
                                |
                                v
    +--- QUOTE CHECK (the honesty gate) -------------------------------+
    |  exact substring of an attached passage?          -> keep         |
    |  chapter tag slipped? try every attached passage  -> keep         |
    |  near-verbatim with an edit? keep the longest                     |
    |  word-for-word run >= 40 chars                    -> keep         |
    |  the model dropped a "(Figure N-N)"? match without it -> keep     |
    |  nothing holds                                    -> Not in this book. |
    +---------------------------+---------------------------------------+
                                |
                                v
    +--- ANCHOR EXPANSION (no model) -----------------------------------+
    |  a question word rare in the book (df <= 80) that lives in the    |
    |  paragraph but NOT in the quote -> show the whole paragraph       |
    |  (multicloud -> every disadvantage in one answer)                 |
    +---------------------------+---------------------------------------+
                                |
                                v
    +--- CLEANUP (no model) --------------------------------------------+
    |  a quote that opens with the chunk's heading line drops it        |
    |  a figure attaches only from the passage the answer cited         |
    +---------------------------+---------------------------------------+
                                |
                                v
        window: quoted answer + gloss + figures
        (refusal figures are labeled "nearby, not an answer")
```

## What each part kills

| Failure seen in the wild | Slayer | Pinned by |
| --- | --- | --- |
| Typo, chunk found but the model refuses (CRU) | second reading becomes the question, disclosed as the `Read as:` line | battery typos |
| Typo breaks the search itself (atermark) | second reading, kept only when the score strictly improves | battery typos |
| A figure is in the index but never retrieved (MAD: figure-4-1 at dense rank 35) | caption seed | battery MAD probe |
| The lexical boost dragging a tail chunk into an answer (France) | dense band: a promoted chunk must sit in the dense top 20% | unit tests + France |
| Model edits its quote, or tags the wrong chapter | span-keep + any-attached-passage match | unit tests + battery |
| An answer opening mid-sentence ("of unknown consequences with…") | sentence-boundary chunking at ingest | chunking tests + the boundary audit |
| A quote opening with the chunk's heading line | heading trim in the answer layer | unit tests |
| Figures from passages the answer never used | attach only from cited passages | unit tests |
| Search drowns a rare word (pragmatic); list answers thin (multicloud) | rare-word boost + anchor paragraph expansion | battery probes |

## The constitution (never changes)

- Every quoted word comes from the book's passages. Repairs move *which*
  passage text is shown; they never invent text. A refusal is exactly
  `Not in this book.`
- Stdlib only, local models only (nomic + qwen through Ollama). No new
  models, no word lists, no cloud.
- Metadata never enters `chunk["text"]`. The text is canonical and is what
  gets cited; that is why adding provenance moved no vector and no pin.
- Prompt changes are stop-and-say; five experiments are dead (typo line,
  multi-quote line, definition verbs, a spelling note, a labelled gloss).
  Behavior fixes live outside the prompt.
- France is the honesty canary. The battery — 18 asks over HTTP: golden
  10/10, typos, probes, France exact — and 83 unit tests must stay green;
  every fix earns its own pinned case. A single red line is suspect until it
  repeats: the local model is not bit-exact under a 17-request run.

## How it grew (one line each)

1. Record what the model really said (raw captures) — the model edits quotes.
2. Repair the question word (spelling) — CRU answers. Superseded by 8.
3. Rescue edited quotes (span keep) — golden #5/#10 and CRU answer.
4. Retry broken searches (atermark) — the proof is the better score. Folded into 8.
5. Bring back missed chunks (boost) — "pragmatic" finds ch04-012.
6. Widen list answers (anchor expansion) — multicloud shows every disadvantage.
7. Forgive tag slips (any-passage match) — the user's own phrasing fixed.
8. One self-proving reading replaces both spelling paths — the question is
   never rewritten, and the answer discloses the reading (CRU, atermark).
9. Caption seed — MAD data landscape finds figure-4-1 at dense rank 35.
10. Dense band on the boost — the France refusal stops resting on a fitted
    df cutoff and rests on a measured rank gap instead.
11. Figure-reference normalizer — a quote keeps its subject when the model
    drops "(Figure N-N)".
12. Sentence-boundary chunking — 373 mid-sentence starts to 0; four pins
    re-derived and the battery re-run over HTTP.
13. Chunk provenance — `doc`, `section`, `anchor`, `figures`; ids and
    vectors unchanged, which is the point of metadata that stays out of text.
14. Heading trim and cited-only figures — two warts the pins could not see.

Measured state: battery PASS on all four lines (golden 10/10, typos, probes,
France exact), warm asks ~0.4–1.2 s, 83 unit tests. `anchor` is empty for
every chunk because this EPUB's headings carry no id.
