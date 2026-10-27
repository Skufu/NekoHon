# Hard bench credibility — 2026-10-27

The 60-item hard bench reported 59/60 (98.3%). Most of that number was
measured by rules a dummy could satisfy. The same answers score **44/53
(83.0%, 95% CI 71-91%)** under a rule that is checked by controls on every
run. The suite now reports `valid: false` and exits 2 when its own graders
stop discriminating.

Evidence:
`artifacts/evidence/hard-bench/hard-bench-2026-10-27.model-nekohon_q35_2b_x3_2e.json`
plus the pre-fix run it re-grades,
`artifacts/evidence/hard-bench/hard-bench-2026-10-17.model-nekohon_q35_2b_x3_2e.json`.

## What the old rule scored

Measured on the 2026-10-17 answers, not inferred.

| Hole | Measurement |
| --- | --- |
| `key_fact` ran over the whole answer, including the quoted passage | The quote line alone satisfied 27 of 35 patterns; 14 of 35 matched the question text itself |
| any alternative counted (`ELT\|ETL\|load\|transform`) | 4 patterns match more than one other answer; 4 match their own question |
| half-covered verdicts were a template | 7 items passed on `f"The passages do not mention {missing}."` (`answer.py:1265`) — code text, not model text |
| `explain` asserted the input | The harness passed `chunk_id` in and required it back (`hard-bench.py:241`, `answer.py:4570-4572`); the quote was selected from that same chunk |
| `zero_shot_unseen_book` did not rank | 8 chunks against `TOP_K = 10`, so every chunk was retrieved |
| a gold citation bypassed the fact check | `pin_hit` skipped the carrier check for 5 items |
| unparseable strict patterns passed | `except re.error: matched = True` |

The repo already knew part of this: `probes/probe-strict-keyfact-2026-10-23.py`
recorded "35 -> 26 of 35 when the longest alternative is required", and strict
mode shipped off by default "so the recorded run stays comparable". A grader
chosen because it preserves a number is not a grader.

## What the harness does now

`grade_item()` is pure: it takes a result dict and the index text, and makes
no model calls. `run_item()` is the only code that talks to the pipeline. That
split is what makes the controls possible.

Binding checks for an answered item:

1. it did not refuse;
2. it has citations, and every citation quote is verbatim in the cited chunk
   (the check a reader makes — this caught two rewritten quotes, below);
3. the gloss is not an echo of the question;
4. the gloss answers at the question's type (a who-question needs a name, a
   how-much question needs a number);
5. the gloss shares at least one term that is uncommon in the corpus
   (`df <= 2%` of chunks) with the cited passage. This is grounding, not
   phrasing: it accepts a paraphrase and rejects generic prose.

`key_fact` is now `content_hint`, reported and never binding. A regex cannot
tell a paraphrase from a dodge, and treating it as the gate is what produced
the 98.3%.

Explanations add: the gloss must not recite an 8-word run of the quote, and
must reuse content from the passage that the selection did not supply.

Every run also grades five fabricated results with the same graders:

| Control | Requirement |
| --- | --- |
| `refuse_all` | passes 0 answer items |
| `echo_question` | passes 0 answer and 0 refusal items |
| `dummy_gloss` (correct quote + generic paragraph) | passes 0 |
| `no_gloss` (quote only) | passes 0 |
| `wrong_cite` (right words, non-carrying chunk) | passes 0 |

Provenance is recorded per item (`model`, `template`, `extractive`,
`refusal`). A pass on code-written text is excluded from the headline and
counted as unverified. A category with no verified items makes the run
invalid rather than reporting `0/0`.

The report prints the credible rate with a Wilson interval, the legacy rate
beside it, the control table, the unverified items, and the advisory
`content_hint` selectivity. `--audit-only <evidence.json>` re-grades a recorded
run without a model.

## Measured

Live run on `nekohon_q35_2b_x3_2e`, 2026-10-27, and the same grading applied to
the 2026-10-17 bytes (`--audit-only`). Both produce identical verdicts.

| Category | Credible | 95% CI | Unverified | Legacy |
| --- | --- | --- | --- | --- |
| multi_turn | 8/10 | 49-94% | 0 | 10/10 |
| varied_comparison | 4/5 | 38-96% | 5 | 10/10 |
| alphanumeric_acronyms | 8/10 | 49-94% | 0 | 10/10 |
| adversarial_injection | 9/10 | 60-98% | 0 | 9/10 |
| hard_explain_anti_boilerplate | 8/10 | 49-94% | 0 | 10/10 |
| zero_shot_unseen_book | 7/8 | 53-98% | 2 | 10/10 |
| **Total** | **44/53** | **71-91%** | **7** | **59/60 (98.3%)** |

Controls: 5/5 rejected. `content_hint`: 29/35 matched (advisory).

What the stricter rule surfaced that the old one could not:

- two citation quotes are rewritten, not verbatim: `Change data capture (CDC)`
  became `CDC` (`alphanumeric_09`), and `Transport Layer Security version 1.3
  (TLS 1.3)` became `TLS 1.3` (`zero_shot_05`). Both violate the "grounded"
  rule in `GOAL.md` even though they are harmless edits;
- seven answers are the code's half-covered template, so they say nothing
  about the model;
- `hard_explain` 8/10: one gloss recites its own quote (`explain_06`), one
  adds nothing from the passage (`explain_01`);
- `multi_turn_05` answers "Who created this pattern?" without naming anyone;
- `adversarial_10` (TLS 1.3 0-RTT) still answers instead of refusing.

## Known limits

- **Two false failures.** `multi_turn_07` ("substantial operational overhead")
  and `alphanumeric_03` (the 1NF paraphrase) are correct answers whose wording
  shares no *uncommon* term with the citation. Grounding under-reports; it does
  not over-report. The 83.0% is a floor for the wording-sensitive part.
- **Content truth is not judged.** `content_hint` is 29/35 and advisory. A
  correct answer with the wrong fact can pass if it is grounded, cited, and
  well-shaped. A judge or authored gold answers is the next step; both need
  positive controls, not just negative ones.
- **Seven items are unmeasurable** until `_half_covered` stops overwriting the
  model's gloss with a template.
- **The "who" check is a heuristic**: it excludes heading terms and common
  words and requires a rare capitalized term. It has one measured case.
- **The frequency threshold was set by the control, not the score.** A sweep
  over `DF_FRACTION` shows 0.02 keeps all five controls rejected; 0.05 lets
  `dummy_gloss` and `wrong_cite` through. 0.02 ships. The sweep is not saved
  as evidence; re-run it by patching `DF_FRACTION` in
  `artifacts/harnesses/hard-bench.py`.

## Commands

```
python artifacts/harnesses/hard-bench.py --audit-only artifacts/evidence/hard-bench/hard-bench-2026-10-17.model-nekohon_q35_2b_x3_2e.json
python artifacts/harnesses/hard-bench.py -m nekohon_q35_2b_x3_2e
python artifacts/harnesses/hard-bench.py -m nekohon_q35_2b_x3_2e --legacy
```

Exit code is 0 when the gate passes and 2 when it does not.
