# Search prompt — a small answer model we can finetune for quote-or-refuse

Hand this whole file to the researcher agent. Do not pull anything it names.
A pull still needs a yes on a size in megabytes.

## What to paste

Find the model and the recipe for a finetune: a small local LLM that can do one
constrained extraction job well enough to replace a 7B model. The end target is
a **small PC** — CPU-only or ≤ 6GB VRAM — so the finished model must ship as a
GGUF of **about 2.5GB or less at Q4/Q5**.

The job: the model receives up to 10 short passages from one book. It must

1. quote a sentence that already exists in those passages,
2. start the quote with `[Ch. N]`,
3. add one short line of plain gloss, and
4. reply exactly `Not in this book.` when the answer is absent.

Temperature is 0. The app discards any reply that does not start with `[Ch.`
and is not exactly `Not in this book.` So the finetune target is **format,
refusal, and verbatim span copying** — not world knowledge.

The baseline that must eventually be beaten at this size: `qwen2.5:7b` Q4_K_M
(4,683MB). It follows the format and passes an 18-ask battery, but it is too
big for small PCs. The existing 3B fallback (`llama3.2:3b`) is a weak-machine
stopgap, not the bar.

## Find, as of today

1. **Base models to LoRA-finetune, 2B–4B params, late 2025 or 2026.** Apache-2.0
   or MIT preferred, text-only, no built-in thinking mode, strong at *copying a
   span* rather than paraphrasing (extractive QA, grounded generation,
   long-context copying). Exact HF repo, params, license, and any measured
   extractive/grounding scores.
2. **Existing finetunes that already do quote-or-refuse, grounding, or
   citation.** If one is close enough, that beats training from scratch. Exact
   repo or Ollama tag, size, and what it was trained on.
3. **This post and its thread: https://x.com/sudoingX/status/2109579895676522946**
   The user says it shows people making good small local models. Extract the
   approach (base model, data, method, tools, cost) and find 3+ more public
   write-ups like it.
4. **Training-data prior art.** Datasets shaped as (question, passages, verbatim
   answer span) plus unanswerable cases, or published methods for generating
   verified quote data at scale — a label is only valid if the quote appears
   verbatim in the source.
5. **Tooling with a proven recipe on a single A100 (Colab):** Unsloth, Axolotl,
   torchtune, or others. Which has a working 3–4B LoRA config, with measured
   VRAM and wall-clock where published.
6. **Quantization evidence:** which llama.cpp quant (Q4_K_M, Q5_K_M, ...) keeps
   extractive-format behavior at this size, and any published small-model evals
   actually run at Q4.

## Hard constraints

- Text-only. Reject vision/audio projectors — hundreds of MB for nothing here.
- No thinking-by-default models; a leaked reasoning trace breaks the format check.
- The final artifact must run through Ollama on a small PC, CPU-only acceptable.
- The recipe must be reproducible from a public write-up, not a private claim.

## Output

One table per numbered section. Columns: candidate | exact name/tag | size |
license | measured evidence | what it gives us | what could fail | source URL.
Then a short verdict:

1. Best base model to finetune, and why.
2. Any existing finetune close enough to skip training. Yes/no + exact tag.
3. The most credible public recipe to copy (tool + config), and its measured cost.
4. One sentence: the biggest unknown only a local bake-off can settle.

Do not invent numbers. If a number is not in a source, write "not measured."
