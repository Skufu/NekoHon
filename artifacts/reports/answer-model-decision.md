# Answer-model decision — 2026-10-11

Source table: `artifacts/ollama-quote-model-table.md`. No pull yet.

Recommendation, 2026-10-11: pull `qwen2.5:7b` first. 4683 MB. Close Phase 4
on the model the plan locked. Do not swap models while proving the quote check.

`qwen2.5:7b` stays the plan default until a candidate passes the same live
check: three in-book questions return a quote that is a substring of the cited
chunk, and one out-of-book question returns exactly `Not in this book.`
Include the two late nomic hits (source systems, rank 7; data architecture,
rank 8). A small model drops those first.

Do not pull `granite4.1:8b` first. The researcher named it. The IFEval number
is vendor-only, the metric is not the same as qwen's, and the file is bigger
(5348 MB vs 4683 MB).

Do not pull `qwen3:4b-instruct` first either. 2497 MB, and the card says
non-thinking, but a 4B model is the one most likely to drop a quote that sits
in passage 8 of 10. That experiment comes after Phase 4 passes, not instead
of it. Pin `qwen3:4b-instruct` if it is tried later. Plain `qwen3:4b` is the
thinking model.

Second try, only if the 4B tag fails the quote check: `olmo-3:7b-instruct`,
4472 MB. Pin `-instruct`. Plain `olmo-3:7b` is the think model.

Do not try: `qwen3:8b` (thinks by default), `gemma3:4b` (vision by default),
`phi4-mini:3.8b` (verbose, high hallucination on Vectara), `command-r7b` and
`exaone3.5` (non-commercial).

Nothing in the table measured quote-or-refuse. A high IFEval score is not a win.
