# Figure understanding — plan (2026-10-15; direction recorded, not approved)

## The want

Ask about a figure: "what is figure 4.4" / "explain figure 4.4" → today:
`Not in this book.` (the user's two live screenshots). The reader should get the
figure shown, the book's own words about it, and a reading of what it depicts.

## What exists today (measured)

- **111 figures** (`data/figures/fode_*.png`), indexed as
  `{id: figure-4-4, chapter, caption, referencing_paragraph}`.
- Retrieval has a **caption-seed path** (`captions.py`): a caption matching the
  question better than the best chunk leads the passage set; the figure then
  attaches by its naming rule (Phase 5). This works — the "MAD data landscape"
  measurement in `captions.py` is the proof.
- Gaps, in order of cost:
  1. **No figure-number normalization.** `canonical_query("explain figure 4.4")`
     returns it unchanged; `"figure 4-4"` becomes a question. The book writes
     "Figure 4-4"; the user typed "4.4" — the naming chunk never matches.
  2. **Captions are short** ("A social network graph") and the figure's
     *content* is nowhere in the index — "what does it show" is unanswerable
     by design today.
  3. The window shows a nearby figure on refusal but no explanation of it.

## Verdict on the proposal

- **Right**: pre-describe figures **at ingest**, store text, keep the runtime
  local and small. This is the same shape as the teacher capture: expensive
  work done once at build time, nothing heavy ships.
- **Wrong**: moving the shipped runtime to a vision model (Qwen2.5-VL). If the
  description is precomputed text, vision at inference buys nothing and costs
  the footprint promise (small stock-GGUF models; phones later).
  **Vision belongs at ingest, not at inference.**

## The pipeline

1. **Ingest-time figure reading** (build-time, once per book): each PNG →
   a VL description (nodes, labels, arrows, layout, colors) + OCR of the
   in-figure text (exact strings). Stored as
   `figures[i].description`, `figures[i].labels[]`, `source: "read@ingest"`.
2. **Retrieval**: figure descriptions become an evidence class. A question
   that names a figure (normalized) or matches a caption pulls the description
   into the passage set as `[Fig. 4-4]` evidence.
3. **Answer policy** (a decision, see below): the description is
   **machine-generated, not book text**. The constitution says every quoted
   word comes from the book.
4. **Later**: "why does this figure matter" → the book's own surrounding text
   (chapter context around the referencing paragraph), not the machine.

## Phases

- **Phase 0 (cheap, independent, today-able):** figure-number normalization in
  `canonical.py` — "figure 4.4" / "fig 4.4" → "Figure 4-4". Then the existing
  caption/naming path can fire for the screenshots' queries. Measured by:
  the two screenshots' queries answered with the referencing paragraph quoted
  + the figure attached.
- **Phase 1:** the ingest-time reader (build-time script; model choice below;
  validation: every OCR label appears in the description; 10 figures
  spot-checked by eye).
- **Phase 2:** retrieval wiring + the window shows the description as a
  labeled block under the answer.
- **Phase 3:** policy + tests + docs.

## What we will not do

- No VL model in the shipped runtime.
- No on-the-fly figure description at inference (non-deterministic, slow, and
  it would invent).
- No unlabeled generated text presented as book text.

## Costs

Build-time only: 111 figures × one VL call ≈ minutes on Colab (or a local VL
model). Storage: a few KB of text per figure. Runtime: unchanged.

## Open decisions

1. **Citation policy for generated descriptions**: (a) book text (caption +
   referencing paragraph) is quoted, the description is shown as a labeled
   "figure read" block, never quoted; or (b) a distinct `[Fig. N]` citation
   class for descriptions, visually labeled as generated at ingest.
   *Recommendation: (b)* — honest attribution, and the reader still gets
   "what the figure shows".
2. **The ingest model**: a local VL model (Ollama, once), Colab, or a cloud
   API under the existing build-time exception.
3. **Ship Phase 0 now?** It is independent of everything else and fixes the
   screenshots' exact queries.
