# Track A — verifier testbed, first run (2026-10-25)

Six real defects, re-applied one per tree, plus a behaviour-neutral baseline.
Same model for every run (DeepSeek V4.1 Flash, Zed default), same prompt, flag
list capped at five.

## Results

| id | defect | flagged | what the reviewer said | tests already red? |
| --- | --- | :---: | --- | :---: |
| d1 | prior-quote lookup matched raw text (CRLF in the index) | yes | "whitespace collapse removed … reverts the exact defect this function was written for" | yes |
| d2 | attribution guard in `ask` but not `respond` | yes | "guard removed from `respond`; measured `refused=False` for the Marcus Feld item" | yes |
| d3 | `plainer words` cue deleted | yes | "deleting a cue also deletes its own test, so the suite stays green" | **no** |
| d4 | import accepted any path | yes | "`is_relative_to(books/)` deleted … local file disclosure / path traversal" | yes |
| d5 | LRU cache race | yes | "`pop(key)` without a default raises `KeyError` … reverts a fix the suite pins" | yes |
| d6 | no cache clear after import | yes | "id-keyed cache keeps a ranking from the previous book … stale chunks" | yes |
| baseline | variable rename, no behaviour change | — | `NONE` | — |

Recall 6/6. False flags on the baseline: 0 of 1 run. Every extra flag was a true
observation (stale doc, red test), not noise.

## The flaw this run exposed

**Five of the six were caught by the repository's own tests.** The reviewers ran
the suite, saw red, and reported. That measures "verifier + CI", not review
skill. A green CI would have hidden them.

That is not a reason to distrust the result — a verifier that runs the tests is
a good gate. It is a reason not to call this a review-skill benchmark. The one
defect that mattered, d3, was invisible to the suite because its test is
generated from the cue list itself; the reviewer caught it by reading the code
and the docs.

## Two secondary findings

1. **The doc was used.** On the branch tree (d4-d6) the reviewer quoted
   `docs/DECISIONS.md` to prove the intended behaviour, unprompted. That is the
   first evidence that the read rule works, and it supports doc-only for
   `engine/`.
2. **Doc drift is a strong signal.** Four flags were "the docs still claim the
   old behaviour". The docs made the defect easier to see, not harder.

## Round 2, to make the test fair

Same six defects, but also update the affected tests so the suite is **green**.
That is the real-world case: a plausible PR where the change and its test agree.
The reviewer then has only code, docs, and judgment.

Also add two mutants the suite cannot see, to keep one hard item per trial:

- rename a guard to its opposite (`is_relative_to` → a no-op check that always
  passes);
- swap a constant that only one untested path uses.

Pre-registered for round 2: the same prompt, capped at five flags, and a verdict
of "gate-worthy" only at 4/6 with no false flags on the baseline.

## Cost

Seven reviewer runs, no model downloads, no Colab. Trees live under
`.delta/track-a/` and are not committed.
