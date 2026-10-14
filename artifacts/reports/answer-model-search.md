# Search prompt — a better local answer model than qwen2.5:7b

Hand this whole file to the researcher agent. Do not pull anything it names.
A pull still needs a yes on a size in megabytes.

## What to paste

Find a local Ollama answer model for a book companion. The job is not
"the smartest model." The job is a constrained extraction.

The model receives up to 10 passages from one book. It must:

1. Quote a sentence that is already in one of those passages.
2. Start that quote with `[Ch. N]`.
3. Add one short line of plain gloss. Definition first if the passage defines a term.
4. If the passages do not contain the answer, reply with exactly
   `Not in this book.`
   That sentence, period included, and nothing after it.
5. Not merge two chapters into one answer.
6. Not describe an image. It cannot see pixels.

Temperature is 0. If the reply does not start with `[Ch.` and is not exactly
`Not in this book.`, the app throws it away.

Current locked model: `qwen2.5:7b`, Q4_K_M, about 4.7GB, Ollama tag, not pulled
on this Windows box yet. Do not treat it as best. It was picked because it is
on the plan and it follows a format. `deepseek-r1:7b` is already rejected: it
thinks out loud and writes past the quote. `llama3.2:3b` is a weak-machine
fallback only, not the bar.

Search for models that exist as an Ollama tag, or as a GGUF a person can
import, as of today. Prefer Apache-2.0 or a license that allows local
inference. Prefer models that stay under about 8GB at Q4 or Q5. Note the
exact tag, parameter count, quantization, and file size in MB.

Look for small instruct models with a high instruction-following score, not
reasoning models. Reject anything whose default behavior is chain-of-thought,
visible thinking, or long answers. Reject vision models for this job. This
job is text only.

Compare against `qwen2.5:7b` on these public checks if the numbers exist:
IFEval or a similar instruction-following score, format-exact / JSON or
schema adherence, and whether the model tends to add text after a short
required answer. Also name newer small instruct models in the same size band
(about 3B to 9B) released after Qwen2.5, including later Qwen, Gemma, Phi,
and anything less famous that scores higher on instruction following.

Return a table, not a recommendation essay:

| model tag | size MB | license | instruction-following evidence | why it might beat qwen2.5:7b on a quote-or-refuse task | why it might fail that task | source URL |

Then one line: the single best candidate to try, and the megabytes a pull
would cost. If nothing beats qwen2.5:7b on this job, say that. Do not invent
a score. If a number is not in a source, write "not measured."
