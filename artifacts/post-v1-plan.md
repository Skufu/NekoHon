# Post-v1 plan — 2026-10-12

v1 is done. Do not start Phase 8. `cargo` is missing. The plan already says stop.

Do these in order. Each step must pass the battery in `artifacts/planning-context.md` before the next step starts. A prompt-line change is not step 1. That was tried, it failed, and one wording regressed golden #6. Do not repeat it.

## 1. Look at the raw reply before changing the model

The two golden refusals and the two typos are different bugs.

| Case | Retrieval | Answer | What that means |
| --- | --- | --- | --- |
| storage question, transformations question | 10/10, right chapter in top-10 | refused | The model saw the right passage and still did not return a kept quote. |
| `CRU`, `ET` | right chunk at rank 1 | refused | Search is fine. The question word does not match the passage word. |

Save the raw completion for those four calls before any code change. If the raw text already contains a sentence from the passage, the parser is the bug. If the raw text is a paraphrase or a bare refusal, the model is the bug. Do not guess.

## 2. Typo tolerance, only after step 1

Do not correct the question before search. Search already finds the chunk.

Correct a word in the question text sent to qwen only when all of these are true:

- The word is not already in the book.
- `difflib` finds one book word within a tight cutoff (start at 0.85, not 0.6).
- That book word appears in the top retrieved passage.

Do not correct "France". Do not correct a word that is a real book word. If two book words are equally close, correct nothing.

Battery: the two typos answer from ch05-019 and ch07-033. The 10 golden questions stay at least 8/10, same chunks where possible. France is still exactly `Not in this book.`

## 3. Label refusal figures

The attach rule stays. A nearby figure on a refusal is already allowed. The page must say "nearby, not an answer" on those images, and must not say that on a real answer. France still refuses. The storage refusal may still show figures. They must be labeled.

## 4. `keep_alive`, only if the cold start matters

Set `keep_alive` on the embed and generate calls. Warm asks are about 1 second. Idle asks are about 25 seconds. Cost is about 5 GB of VRAM held. Skip this if the machine needs that memory.

## 5. Caption quoting, after 2 and 3

A caption may be quoted. The chart may not be described. Feed the caption as text next to an already-attached figure. The quote check must accept that caption string. Do not add a vision model. Do not pull EmbeddingGemma vision.

## Not in this plan

Phase 8. A new answer model. A nomic requant. An embedder finetune. A prompt rewrite as the first move.
