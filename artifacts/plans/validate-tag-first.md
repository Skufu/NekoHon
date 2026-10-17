# Tag-first citation fix — source review

Date: 2026-10-15.
Scope: `answer.py` `_sentence_claims` / `_claim_after_tag` / `parse_answered`, and the new tests in `tests/test_answer.py`.
This turn did not run unittest. No live book run.

| # | required | verdict | test |
| --- | --- | --- | --- |
| 1 | Tag-first quote that is in the passage gets a citation in `parse_answered` | **pass** | `AnswerTests.test_tag_first_quote_in_the_passage_is_cited` |
| 2 | Invented tag-first quote does not become a refusal | **pass** | `AnswerTests.test_tag_first_invented_quote_is_uncited_not_refused` |
| 3 | End-tagged sentences still cite the text before the tag | **pass** | `AnswerTests.test_end_tagged_sentence_is_still_cited` |
| 4 | Bare `[Ch. 5]` with no quote and no prior text produces no claim | **untested** | none |

## 1. In-passage tag-first quote — pass

`test_tag_first_quote_in_the_passage_is_cited` feeds `parse_answered` a `[Ch. 5]` line whose quoted sentence is the `ch05-019` passage, then a gloss line.

Asserts: not refused, `citations[0]["chunk_id"] == "ch05-019"`, answer text unchanged.

Source: pending text is empty at the tag, so `_claim_after_tag` takes the quote on that line; `_best_passage` overlaps that claim with the shown chapter-5 passage.

## 2. Invented tag-first quote — pass

`test_tag_first_invented_quote_is_uncited_not_refused` feeds `[Ch. 5] "purple zebra constellations dance at midnight"` plus a gloss line.

Asserts: `refused` is false, `citations == []`.

Source: `_free_refusal` only matches the exact refusal sentence on the first line. A zero-overlap claim is skipped in `parse_answered`, not turned into a refusal.

## 3. End-tagged sentence — pass

`test_end_tagged_sentence_is_still_cited` feeds `"CRUD is a transactional pattern. [Ch. 5]"`.

Asserts: not refused, `citations[0]["chunk_id"] == "ch05-019"`.

Source: pending text accumulates until the tag, then that pending string is the claim.

## 4. Bare `[Ch. 5]` — untested

No test in `tests/test_answer.py` (or elsewhere under `tests/`) calls `parse_answered` or `_sentence_claims` with a standalone `[Ch. 5]`.

Docstrings on `_claim_after_tag` and `_sentence_claims` say a stand-alone tag with no pending text yields no claim. That path is not pinned.

Next check: add `test_bare_tag_with_no_quote_produces_no_claim`, or run `python -m unittest tests.test_answer.AnswerTests.test_tag_first_quote_in_the_passage_is_cited tests.test_answer.AnswerTests.test_tag_first_invented_quote_is_uncited_not_refused tests.test_answer.AnswerTests.test_end_tagged_sentence_is_still_cited`.
