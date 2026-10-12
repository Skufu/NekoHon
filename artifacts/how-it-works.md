# How ask-this-book works — mental image (2026-10-12)

## The pipeline, end to end

```
             your question (typos and all)
                        |
                        v
    +--- SEARCH 1: the raw question through nomic vectors ---+
    |        returns the 5 closest passages + scores          |
    +--------------------------+------------------------------+
                               |
     (A) typo repair?          |          (B) rare-word boost?
     word not in the book      |          question has a word rare
     + one clear close word    |          in the book -> best-overlap
     -> SEARCH 2 (repaired)    |          chunk replaces the weakest
     kept only if it scores    |          passage  (pragmatic)
     strictly better (atermark)|          (C) caption seed (step 5, in flight)
                               v
    +--- QWEN: writes ONE sentence + one gloss line ----------+
    |     prompt untouched; prompt-steering tried twice, dead  |
    +--------------------------+------------------------------+
                               |
                               v
    +--- QUOTE CHECK (the honesty gate) -----------------------+
    |  exact substring of an attached passage?      -> keep     |
    |  chapter tag slipped? try every attached passage -> keep  |
    |  near-verbatim with an edit? keep the longest             |
    |  word-for-word run >= 40 chars                -> keep     |
    |  nothing holds                                -> Not in this book. |
    +--------------------------+------------------------------+
                               |
                               v
    +--- ANCHOR EXPANSION (no model involved) ------------------+
    |  a question word rare in the book (df <= 80) that lives   |
    |  in the paragraph but NOT in the quote -> show the whole  |
    |  paragraph  (multicloud -> all disadvantages in one answer)|
    +--------------------------+------------------------------+
                               |
                               v
        window: quoted answer + gloss + figures
        (refusal figures are labeled "nearby, not an answer")
```

## What each part kills

| Failure seen in the wild | Slayer | Pinned by |
| --- | --- | --- |
| Typo, chunk still found (CRU, ET) | question repair (spelling.py) | battery typos |
| Typo breaks the search itself (atermark) | retry search, kept only if score improves | battery typos |
| Model edits its quote, or tags the wrong chapter | span-keep + any-attached-passage match | unit tests + battery |
| Search drowns a rare word (pragmatic); list answers thin (multicloud) | rare-word boost + anchor paragraph expansion | battery probes |

## The constitution (never changes)

- Every quoted word comes from the book's passages. Repairs move *which*
  passage text is shown; they never invent text. A refusal is exactly
  `Not in this book.`
- Stdlib only, local models only (nomic + qwen through Ollama). No new
  models, no word lists, no cloud.
- Prompt changes are stop-and-say; two prompt experiments are dead
  (typo line, multi-quote line). Behavior fixes live outside the prompt.
- France is the honesty canary. The battery — 18 asks over HTTP + 52 unit
  tests — must stay green; every fix earns its own pinned case.

## How it grew (one line each)

1. Record what the model really said (raw captures) — the model edits quotes.
2. Repair the question word (spelling) — CRU answers.
3. Rescue edited quotes (span keep) — golden #5/#10 and CRU answer.
4. Retry broken searches (atermark) — the proof is the better score.
5. Bring back missed chunks (boost) — "pragmatic" finds ch04-012.
6. Widen list answers (anchor expansion) — multicloud shows every disadvantage.
7. Forgive tag slips (any-passage match) — user's own phrasing fixed.

Measured state: battery 18/18, warm asks ~0.5–1.3 s, France exact refusal.
