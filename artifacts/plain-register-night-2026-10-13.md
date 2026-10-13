# Night run 2026-10-13: plain register wired, measured, probed

Front-loaded: the plain register is wired, unit-tested, committed (`4c79dc1`),
and the live app serves it. Its honest quality bar is **5 stable passes,
1 stable fail, 4 borderline flippers out of 10** — the earlier 8/10 was the
top of a noisy range. The release judge flips verdicts on borderline items:
three consecutive calls on one frozen prompt returned
`supported, supported, unsupported`. The agentic loop measured **no win**
(do not wire). The edge probe found two refusal-class failures that are the
answer mode's existing seam, not the wiring.

## 1. What landed (commit `4c79dc1`)

- `answer.py`: cue detection (`SIMPLE_CUES`) + `_plain_body` — draft selects
  evidence sentences, each rewritten one-in-one-out, citations keep the book
  sentences; `PARAPHRASE_LIMIT = 5`; empty rewrites fall back to the draft.
- `prompt.py`: `PARAPHRASE_SYSTEM` (the measured paraphrase instruction).
- `tests/test_plain_register.py`: 17 hermetic tests. Suite: 188 green.
- Docs: AGENTS.md state + Verify entries, README paragraph.

Live checks on a fresh server (kill + restart, one listener):
`"explain data engineering in simple words"` answers in the register
(`artifacts/plain-http-check.json`); `"What is the MAD data landscape?"`
stays ordinary (`artifacts/plain-http-control.json`). Both batteries PASS
(ask PASS after the known cold-start multicloud flake, preserved as
`step2-battery-flaked.*`; answer battery coherence PASS).

## 2. The wired path under the release judge — three draws

| draw | file | pass | book_supported fails |
|---|---|---|---|
| probe assembly (before wiring) | `eval-plain-v6-*` | 8/10 | 2 |
| wired | `eval-plain-wired-*` | 6/10 | 4 |
| wired replay | `eval-plain-wired-replay-*` | 7/10 | 3 |

Diffed per question (all three runs):

- **5 stable pass**: watermark, transformations, data mesh, endpoint, MAD.
- **1 stable fail**: batch/streaming — 3/3 unsupported; the rewrite loses
  meaning (rewriter failure, see the closing experiments below).
- **4 flippers**: data engineering, data ingestion, CRUD, insert-only.
  `same_shown` was true for all 10 wired rows; `reading` null for all 10 —
  the wiring showed identical passages.

The wired vs probe delta is **not the wiring**: rewrites differ draw-to-draw
at temperature 0 (the recorded flake class), and at least one identical
answer text drew `supported` once and `unsupported` twice.

Closing experiments:

- Rewriter determinism: the same paraphrase call repeated 5x in one process
  returned identical text 5/5. The cross-run rewrite differences are not
  reproducible in-process; they remain the recorded temperature-0 flake
  class (model reload / scheduling), unexplained.
- The stable failure's shipped answer names itself: "Batch **ingestion**
  processes data in large groups at once." (the book says batch
  *processing*) and "Storage and computing are kept separate **in m.**" —
  the documented "in m." truncation. Grounding 0.0, judge 3/3 unsupported.
  The one stable fail is rewriter-defect text, visible in the artifact, not
  a judge artifact. Fixing it is rewriter work (the known frontier), not
  wiring work.

Stable, objective gates across draws: answered 10/10, fake quotes 0,
unmatched tags 0, FK 6.9–7.4 (0 grade fails), cited share 0.40–0.44. Only the
judge's `book_supported` gate swings.

## 3. The judge finding (the night's most important result)

Frozen-prompt probe — identical question, passages, and answer text; three
consecutive `judge_book_fidelity` calls to Muse:

```
ingestion    -> ['supported', 'supported', 'unsupported']   stable: False
batch/streaming -> ['unsupported', 'unsupported', 'unsupported']  stable: True
```

The judge sends `temperature: 0` on both wires (`artifacts/judge.py`
`_cloud_payload`), so the flip is server-side (or relay) nondeterminism on a
borderline item — roughly a third of that item's draws. Repeatable probe:
`artifacts/judge-stability.py`.

What this means:

- Single-draw scorecards carry ±1–2 questions of noise on borderline items.
  Any A/B that differs by one or two questions needs repeated draws before a
  winner is claimed; tonight's 6-vs-8-vs-7 is exactly that situation.
- It does not overturn earlier large-gap calls: 2/10 prompt iterations vs 8/10
  paraphrase is far beyond this noise; the granite-vs-Muse agreement (86/105)
  is large-n. It sharpens the language around all single-draw numbers.

## 4. Agentic multi-hop hunt (separate agent, read-only)

`artifacts/multihop-report.md` (+ `multihop-probe.py`, `multihop-results.json`,
`multihop-explore.py`). 10 hand-built two-evidence questions, ground truth by
index grep.

- Full-set surfaced: single-shot 6/10, loop 7/10 (any position) — but the
  loop's first five merged passages match single-shot exactly; its two extra
  halves arrived at merge positions 9 and 6.
- Cost: 26 decision calls, 2.2x merged passages; all 26 decisions chose
  `semantic`; keyword/regex never picked.
- Hand-written queries show every missed chunk is reachable (rank 1–5) with
  keyword or semantic — a decision-policy failure, not tool reach.
- **Verdict: no wiring justified.** Next test, if pursued: a decision policy
  forced to try keyword/regex, and a merge cut that preserves extras.

## 5. Plain-register edge probes (separate agent, live HTTP)

`artifacts/plain-edge-findings.md` + 20 raw responses + `plain-edge-check.py`
(exit 0: all contract checks pass).

- All 10 cues route the plain register; explain/quiz unchanged; figures only
  from cited passages; contract exactness holds.
- NOTE: cue is a substring test, so "not in simple words" routes plain.
- **FAIL class 1**: "explain quantum field theory in simple words" answers
  confidently from a junk ch06 passage, `refused:false`, 2/2 — the draft's
  refusal decision, no guard on the cue path.
- **FAIL class 2**: the no-cue control emits "Not in this book." after a
  preamble — `refused:false` per the frozen first-line rule (by-contract,
  but the text reads like a refusal).

Both are the pre-existing answer-mode refusal seam (documented in
`answer-mode-overnight.md`); the register makes them more visible. Changing
that is a product policy call, not a wiring bug — left as-is tonight.

## 6. Decisions for the morning

1. **Refusal guardrail in answer mode?** (edge FAIL class 1, reproducible).
   A shown-set score floor or a citation-required rule for fresh questions;
   both alter refusal behavior app-wide — needs your yes.
2. **Plain register bar**: accept "5 stable + 1 fail + 4 borderline", or push
   the rewriter (prompt steering is exhausted; next tactic would be
   two rewrites + pick, or a stronger local model). Note `book_supported`
   is the only gate that swings.
3. **Agentic**: park it, or fund the tool-diversity policy test (§4).
4. **Judge-loop hygiene**: adopt `judge-stability.py` into A/B procedure
   (repeat borderline questions before declaring a winner). No engine change.

## 7. Evidence files (all committed in this run)

- Wired scorecards: `eval-plain-wired-*`, `eval-plain-wired-replay-*`,
  `eval-plain-wired-smoke-*`; probe baseline `eval-plain-v6-*`.
- Agent A: `multihop-*`. Agent B: `plain-edge-*`, `plain-edge-findings.md`.
- Probes: `judge-stability.py`, `plain-http-check.json`,
  `plain-http-control.json`, both batteries (incl. `step2-battery-flaked.*`).
