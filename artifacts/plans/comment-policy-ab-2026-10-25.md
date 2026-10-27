# Does the no-comment rule help? Pre-registered A/B (2026-10-25)

Claim under test (friend's practice): code carries no comments or docstrings;
reasons live in `docs/DECISIONS.md`, and a verifier subagent plus code review
enforce it.

Measured first, because it bounds the argument:

| tree | code lines sampled | comment lines | share |
| --- | ---: | ---: | ---: |
| ours (`answer.py`, `retrieve.py`, `server.py`, `intent.py`) | 6,297 | 147 | **2.3%** |
| theirs (`engine/` sample, 5 modules) | 1,489 | 0 | 0% |
| their `docs/DECISIONS.md` | — | 475 | — |

So the token saving is 2.3% of source. The real question is not cost, it is
whether an agent can find a reason when the reason is one file away.

## What "better" means — three separate measurements

### A. Comprehension, measured on the agent

Two arms, same module:

- **V1 inline** — current file with its comments, no DECISIONS entry.
- **V2 doc** — comments stripped, the same facts written as DECISIONS bullets.
- **V3 doc + rule** — V2 plus one line in `AGENTS.md`: read `docs/DECISIONS.md`
  before editing `engine/`. This is the friend's setup; the doc is only visible
  to an agent if the loop puts it in front of them.

Eight questions per arm, each with one objective answer. Same model,
temperature 0, 5 trials, order randomised, scored by exact keyword.

Also record two context numbers that decide the economics:

- tokens spent before the first correct edit (comments are paid on every file
  read; the doc is paid once per task, or never);
- whether the agent opened `DECISIONS.md` at all in V2 (prediction: rarely).

Pre-registered rule: V3 wins if it matches accuracy with fewer tokens than V1.
V1 wins if it is ahead by 2 or more questions. V2 alone is not allowed to win,
because an unread doc is not a policy.

### B. Bug fix (objective, slower)

Seed four bugs in one module, two per arm, each with a failing test as the
oracle. Agent gets the repo and the failing test.

- Metric: test passes, files touched, lines changed outside the target
  function, tokens.
- 2 arms x 2 bugs x 5 trials = 20 runs.

Pre-registered rule: adopt the winner only if it fixes at least 1 more bug out
of 4 and touches no more collateral lines. Anything closer is noise at n=5.

Honest power note: with 5 trials per cell, only large effects are detectable.
A 10-point difference cannot be resolved here; do not claim one.

### C. Drift (no model)

Apply ten realistic edits to the commented file and count comments that become
false. Apply the same ten edits to the tree with DECISIONS and count bullets
that become stale. The rule's own weakness is that a stale doc is invisible in
a diff, while a stale comment sits next to the line.

Cost: 30 minutes, no calls.

## Why agent-only changes the design

No human leg. The reviewer is the gate: tests, verifier, and the harnesses. Two
consequences:

1. **A doc nothing loads is not a policy.** V2 is the friend's tree without the
   friend's verifier; it should lose on tokens precisely because the agent
   spends them searching for a reason that is one file away.
2. **Context is paid per read.** 2.3% of a file is cheap on every read; 475
   lines of decisions is expensive per load, and free if never loaded. That
   asymmetry is the whole argument, and it is measurable.

## Third arm is the real test

Their actual setup is doc-only **plus** a verifier that reads the doc. If V2
beats V1, run V3 = V2 with one extra instruction in the verifier prompt: check
the change against `docs/DECISIONS.md`. If V3 does not beat V2, the doc is
carrying the weight and the verifier is optional.

## Decision rule, written before any run

| outcome | policy |
| --- | --- |
| V3 >= V1 on accuracy and less tokens | adopt doc-only for `engine/`, with the read rule in `AGENTS.md` |
| V1 ahead on A by >= 2 | keep inline comments; DECISIONS stays as the architecture record |
| tied | comments allowed only where DECISIONS cannot hold a line-level reason; each such comment must name a bullet |

Human review is not an input. The gate is the test suite and the verifier.

## Order of work

1. Arm A with three arms (V1, V2, V3). 60 short calls, ~20 minutes.
2. Arm C (drift). 30 minutes.
3. Arm B only if A is inconclusive.

If V3 beats V1, the policy is: no comments in `engine/`, the doc is mandatory
for the agent, and the rule lives in `AGENTS.md` where every loop reads it.
If V1 wins, comments stay and the doc is the architecture record only.

## Cost

Under an hour for A + C. B is a day, and only if A cannot decide.
