# Data quality and retraining

Status: in progress, 2026-10-29. No new training job or model adoption yet.

Progress checked 2026-10-30: the core evaluation/FTS fixes are implemented and
the repeated HTTP FTS check passed. Independent review covered all 844 original
training targets: 529 accepted, 286 needing review, 29 rejected. Those are agent
review decisions, not a model accuracy score. Twelve new follow-ups passed
independent source review after two repairs. Candidate assembly, component
splits, and baseline response reviews are still in progress. Colab CLI access
exists, but no GPU session, upload, training, or model replacement has started.

## Outcome

Produce an auditable training candidate, source-separated development split,
and credible comparison with the shipped local model. Training uses the
owner's Colab CLI workflow. Lower training loss is not an adoption rule.

## Starting evidence

The recovered 844-row x3 corpus has LF hash
`f250db70df4e962ccf9087cab4a07930f19d01d600b033030587b8827f89fd86`.
Restoring CRLF record separators reproduces its recorded original hash
`fd06f9818114837b89b1f4d090cce5d9676cc13707fc8dd73c6fe1b98984a697`.
This verifies content equivalence, not the weights' training provenance.

The 777-row derivative is not independently clean against the new dev set:
a same-question, same-source DataOps item remains in both. The new reference
cases are development data, not an unseen test. Keep source-seen items for
diagnosis and label their exposure.

Cached FTS5 connection reuse fails across threads and fusion silently falls
back to the old scorer. An isolated reproduction exists; the served path
needs verification after a fix. Four evaluation-tool defects also remain at
the start of this phase despite the existing unit tests passing.

## Work order and completion checks

1. **Repair evaluation mechanics.** Reproduce defects at public data and
   captured-response interfaces, add failing tests, then make minimal fixes.
   Preserve valid paraphrases, short real quotations, intentional
   withheld-evidence refusals, and genuine context-only overlap. Fabricated
   attributed quotations must not pass with fresh reviews.
2. **Make retrieval repeatable.** Fix FTS5 connection ownership and stale-cache
   behaviour. Make any fallback observable. Test concurrent queries, restart
   the engine, then check repeated HTTP requests. Do not tune ranking
   constants as part of this repair.
3. **Audit authentic inputs.** Preserve originals. Account for every row with
   hashes, lineage, provided sources, target support, and a disposition.
   Distinguish passages, captions, synthetic domains, history, and withheld
   context. Literal-source checks are not semantic approval; uncertain or
   unsupported targets stay in review.
4. **Freeze source/family splits.** Group duplicate inputs, paraphrases,
   evidence sources, and history referents before partitioning. Prospective
   fine-tune-held-out claims require a fresh base checkpoint, not one that
   already learned removed rows. Do not inspect reserved cases to author
   training examples or select checkpoints.
5. **Review independently.** A different reviewer checks target meaning
   against actual provided sources. Accepted reviews bind the final content
   digest and criterion version. Automated judges must reject fabricated or
   generic answers and accept a valid paraphrase before grading candidates.
   Preserve failed calibrations; unresolved cases remain REVIEW.
6. **Capture a current baseline.** After Python changes, restart the engine
   with the same model and verify process, settings, and loaded-model state.
   Freeze prompts, shown passages, raw generation, transforms, final output,
   and source fingerprints. Grade generation and final system separately.
   Historical frozen prompts are not a test of current retrieval.
7. **Prepare Colab training.** Verify the actual CLI without exposing
   credentials. Package only approved rows and frozen split hashes. Record
   base revision, tokenizer/template, response-only masking, EOS, token
   lengths, versions, seed, and recipe. Reject silent target truncation or
   empty label masks. Do not upload or launch while checks are unresolved.
8. **Compare before adoption.** Change one experimental factor at a time.
   Retain checkpoints and artifact hashes. Compare the same questions and
   evidence under equal quantization and runtime conditions. Report failures
   and uncertainty, not the best draw. No commit or deployment is automatic.

## Ownership

Parallel workers own the data validator, response evaluator, FTS5 repair,
corpus audit and splits, follow-up review, semantic scoring validity, and
Colab readiness. Separate code/test review follows implementation.

Generated runs stay under `artifacts/runs/data-release-2026-10-29/` until
specific evidence is promoted with an index entry. No cloud runtime inference
or retrieval is introduced.
