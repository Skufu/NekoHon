# Answer-model bake-off plan — 2026-10-12

Sources: `artifacts/ollama-quote-model-table.md` (registry bytes + HF cards, Oct 11)
and `artifacts/x-research-2026-10-12.md` (X pass, Oct 12). The X pass found **no
controlled test of exact quoting, the gloss, or the refusal string** — so it ranks
the pull order below, but `artifacts/step2-battery.py` (18 asks over HTTP) stays the
only judge.

Baseline to beat: `qwen2.5:7b` Q4_K_M, 4,683MB — battery PASS, warm asks 0.4–1.2s.
MB are 10^6 bytes, same convention as the model table; sizes marked "measured" come
from the registry manifests on 2026-10-11.

## Verdict on the X pass

- Confirms the shortlist, adds no new winner. The strongest leads are the ones
  already in the table: `qwen3:4b-instruct` (2,497MB) and `granite4.1:8b` (5,348MB).
  Granite 4.1 is the only genuinely new name, and it was already in our table.
- Re-confirms the rejects: qwen3.5 (thinking by default, loops, broken templates in
  Ollama), qwen3:8b (thinking, and one run matched passages by position instead of
  quoted ids), ministral-3 (repetition loops, vision). Vision tags stay out.
- One review lens to carry in: the qwen3:8b position-matching anecdote. Our quote
  check is structural (the quote must appear in a shown passage), so the only residue
  is quoting the wrong-but-included passage — read for it below.
- Serving path: same weights can score 0% vs 100% across runtimes. We test through
  Ollama end-to-end; no action.
- Finetune side (later, not this plan): the walkthrough that exists is Unsloth LoRA on
  Qwen3-4B-Instruct-2507 — the candidate below. A fine-tune that trained reasoning
  style never learned the output format; and no strict-format/refusal dataset exists
  publicly. We synthesize verified data from books with our own quote check.

## Pull list (needs a yes on the MB)

| order | exact tag | MB (measured) | why it might win here | known traps |
|---|---|---|---|---|
| 1 | `qwen3:4b-instruct` | 2,497 | Non-thinking-only per vendor; IFEval 83.4 (vendor); X: clean output, beat qwen3.5-4B in one local run; about half the baseline size; the natural LoRA base | Pin the exact tag — plain `qwen3:4b` is the thinking model. Only 4B: may drop a verbatim span across 10 passages |
| 2 | `granite4.1:3b` | 2,100 | Same small class; IFEval 82.30 (vendor, self-reported) | Vendor-only numbers; 3B span-holding risk is the highest here |
| 3 | `granite4.1:8b` | 5,348 | Highest IF in the band (87.06 vendor); X adds token efficiency and IBM lists extraction/RAG | Vendor-only; bigger than the baseline — a quality-ceiling check, not the small-PC path |
| — | `granite4:micro` | not measured | X's one controlled-ish test (0 filler words across 13 local models) | Granite 4.0, older than 4.1; size unverified; pull only if 1–3 disappoint |

Option A (recommended): pull 1 + 2 = **4,597MB**. Option B: pull 1 + 2 + 3 =
**9,945MB**. Nothing else on this list gets pulled without its own MB yes.
No new embedder; the nomic index is untouched.

## Step 0 — the model seam (code, no download)

`prompt.py` locks `ANSWER_MODEL = "qwen2.5:7b"`. Today the only way to test another
model is editing that line. For a bake-off the same battery must run each candidate
unchanged: read the model from an `ANSWER_MODEL` env var with the **same locked
default**, and let `artifacts/step2-battery.py` stamp its log header from the same
var so a log never lies about which model ran. Default untouched; `tests/test_answer.py`
(asserts `seen["model"] == "qwen2.5:7b"` with env unset) stays green. No route
changes, no new files in the engine, no recipe in the engine.

## Step 1 — run protocol, per candidate

1. `ollama pull <tag>` (only after the MB yes).
2. Check one listener: `netstat -ano | grep 8000 | grep LISTENING` — the stale-server
   trap has already faked one regression.
3. `ANSWER_MODEL=<tag> python server.py`.
4. `python artifacts/step2-battery.py`; copy the outputs to
   `artifacts/bakeoff-<tag>.{json,log}` before running the next candidate.

## Step 2 — screen, then read every response

Screen: the battery prints PASS on its own bar (golden 8/10, typos and probes exact,
France exact). A screen failure is not automatically a model failure: `judge()`
demands the pinned chunk, and a different-but-correct chunk fails the pin. So for
each candidate, read all 18 responses in the JSON against
`artifacts/demo-questions.md` and record per ask:

- quote verbatim, from a passage that was shown;
- cited chunk;
- gloss present, and does it define when the passage defines;
- refusal only when the text is absent.

Then diff against the baseline `step2-battery.json`, same 18 asks. Plus two known
weak asks by hand through the same server: `monolith` and `What is a storage` —
compared against their baseline outputs in `demo-questions.md`.

## Decision rule (written before results)

- France exact + typos exact + probes PASS are hard gates.
- Golden: no ask may go from answered to refused. A changed pin is allowed only with
  a written reason and an explicit battery re-pin — never quietly.
- The open weaknesses decide ties: the `monolith` definition ask, and gloss presence
  (baseline: gloss in only 2 of 17 answers).
- If a 4B or 3B holds all gates, it takes the small-PC slot and becomes the LoRA
  base. If only `granite4.1:8b` holds, it is the quality slot and the finetune path
  still targets the 4B.
- Swapping the `ANSWER_MODEL` default happens only on non-regression — and only as
  its own announced step. "As good at half the size" counts as a win for the
  small-PC goal.
- Revert rule: if a candidate fails, nothing in the live app changes; the env seam
  stays, the default stays.

## Not in this plan

New embedder, re-embedding, agentic RAG, rerankers, prompt rewrites (dead per prior
evidence), vision tags, qwen3.5, qwen3:8b, any pull over the approved MB.
