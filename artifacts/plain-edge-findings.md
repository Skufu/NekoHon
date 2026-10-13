# Plain-register edge probes (live HTTP, 2026-10-13)

An adversarial probe of the wired plain register, run by a separate agent
against the live server on `127.0.0.1:8000` after the wiring commit
(`4c79dc1`). Every raw response is saved; no tracked file was modified by the
run. Contract checker: `plain-edge-check.py` (re-runs the tag/citation/quote
invariants over all 20 saved responses; exit 0 = all pass).

Method note: all 10 cues were exercised, not a sample. Latency is recorded in
`plain-edge-timing.txt` and is explicitly unreliable (other processes shared
Ollama during the run); it is not used for any verdict.

## Case table

| # | Case (question, mode) | Expected | Observed | Verdict |
|---|---|---|---|---|
| 1a | "what is batch processing in simple words" | plain register: short rewritten sentences, tags kept | 1 sentence, 62 chars, tag `[Ch. 7]`, rewrite ≠ book sentence | PASS |
| 1b–1j | one question per remaining cue (`in simple terms`, `in plain words`, `for a beginner`, `for beginners`, `simply explain`, `explain simply`, `like i'm five`, `eli5`, `keep it simple`) | plain shape | all 9 routed plain (62–226 chars vs control 651) | PASS (all 10 cues run) |
| 2 | "what is batch processing" (no cue) | ordinary path | 651-char, 5-sentence answer, 3 citations | PASS |
| 3 | "explain batch processing, but not in simple words" | routes plain anyway (substring test, negation-blind) | routed plain | NOTE — confirmed; a user negating the phrase gets the register. Minor; not blocking |
| 4 | "explain quantum field theory in simple words" | `refused: true`, answer exactly `Not in this book.` | **answered** from a junk ch06-086 passage, `refused:false`, 2/2 runs | **FAIL** (refusal class) |
| 5 | "explain a watermerk in simple words" | `Read as:` disclosure + coherent answer | disclosure present, on-topic, figure-8-8 attached; summary lost detail | PASS (quality note) |
| 6 | cue under `mode:"explain"` (two variants) and `mode:"quiz"` | unchanged: explain = checked quote; quiz = question+key | both unchanged; cue had no effect | PASS |
| 7 | "explain what a watermark is in simple words" | figure only from cited passage | figure-8-8 attached; cited ch08-039 names it | PASS |
| 8 | contract exactness on plain replies | tags ⊆ citations; non-empty; quotes in book; figures from cited passages | checker over 19 responses: all pass | PASS |
| 9 | latency shape | plain = 1 draft + N rewrite calls | control 3.06 s; plain 1.7–23.9 s; **unreliable, shared Ollama** | NOTE |
| +a | "explain quantum field theory" (no cue) | refuse | answer text contains the refusal sentence after a preamble; `refused:false`, `citations:[]` | **FAIL vs expectation; by-contract** — the frozen rule is "first line must be exactly the refusal", so this is the documented free-generation class, not a new wiring bug |
| +b | evidence quotes on plain path | citations keep original book sentences | 2 of 19 quotes are fragments (inherited from the draft's `_evidence_quote`); fragment rewrites go vague | NOTE — inherited, more visible on this register |

## Most serious finding

Case 4: cue + cleanly out-of-book question answers confidently from an
unrelated passage, reproducibly. The refusal decision is the draft model's,
over whatever retrieval returned — the cue router adds no guard. The no-cue
control fails the same underlying gate differently (preamble + refusal
sentence, `refused:false`). This is the pre-existing answer-mode refusal
class (`artifacts/answer-mode-overnight.md` documents paraphrase-refusals
printing as answers); the plain register makes it more visible because
one-liners read as definitive. Open decision, not fixed here: a shown-set or
refusal guardrail in answer mode, or keep free generation model-driven.

## Judgment

Cue routing holds up: all 10 cues take the plain path, the register is
unmistakable in the raw files, tags/citations/figures keep the frozen
contract, and explain/quiz are untouched. The refusal side does not hold for
out-of-book asks — but that is the answer mode's existing seam, not the
wiring, and changing it is a product policy call.

## Files (all new; raw evidence)

- Responses: `plain-edge-01-*` … `plain-edge-17-*` (20 JSON files, listed in
  `git status` at commit time)
- `plain-edge-check.py` — read-only contract checker over the saved files
- `plain-edge-timing.txt` — raw wall clocks (unreliable, labeled)
