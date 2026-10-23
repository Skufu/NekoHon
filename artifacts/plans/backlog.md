# Backlog

Open and parked work. Nothing here is approved or scheduled; confirm before
starting. Each item names where it lives in the code.

## Planned directions

- **Figure understanding.** Ask about a figure ("explain figure 4.4") and get the
  figure, the book's words about it, and a reading of what it depicts. Design,
  phases and open decisions: [figure-understanding-plan-2026-10-15.md](figure-understanding-plan-2026-10-15.md).
  Cheapest first step: normalize "4.4" to "4-4" in `engine/answering/canonical.py`
  so the existing caption path (`engine/retrieval/captions.py`) fires. Vision
  belongs at ingest (`engine/ingest.py`), not in the shipped runtime.
- **Conversational clarify turn.** A bare fragment such as "how do" would get a
  clarifying question instead of answer-or-refuse. Needs a third response type, a
  change to the frozen `POST /ask` contract (`engine/server.py`,
  `tests/test_contract.py`), multi-turn training and eval data, and a rethink of
  the fragment class in the sealed forms (`artifacts/datasets/sealed-forms.json`).
  Until then a refusal means only that the book does not cover the thing.
- **Caption quoting.** The answer pipeline feeds passages only; a figure caption
  can be quoted under the figure-honesty rule but is not offered to the model as
  evidence. Lives in `engine/answering/context.py` (`retrieval_context`) and
  `engine/retrieval/captions.py`.

## Needs an owner decision

These would change engine output, delete files, or touch `vendor/` or `GOAL.md`.

- **Book-specific terms in the answer path.** `reground_alphanumeric_quote` and
  the `TYPE_2_RE`, `S3_RE`, `IOPS_RE`, `SLA_SLO_RE` patterns hard-code terms
  from the first book, which breaks the "generalize" rule. Removing them changes
  output. Lives in `engine/answering/textrules.py`, `quotecheck.py` and `answermode.py`.
- **Hard-coded default book id.** `engine/server.py` (`DEFAULT_BOOK_ID`, built
  with `"".join` to pass the generalization guard) and `engine/ingest.py`
  (`book_id == "fde"` selects `data/index.json`). Making the default configurable
  changes index paths and the catalog.
- **Held draft in answer mode.** No test checks that the real answer-mode `SYSTEM`
  draft is held back from the stream; today it streams live. Whether it should be
  held is a product decision. Lives in `engine/server.py` (`_stream_generate`).
- **Unused snowball languages in `vendor/`.** Left untouched on purpose.
- **Tailwind.** Installed only for its CSS reset; removing it edits the
  pinned-dependency test (`web/package.json`, `tests/test_frontend_rules.py`).
- **Stale default tags in a harness.** `artifacts/harnesses/probe-highlight-2026-10-16.py`
  defaults to the retired `smallbook_x2d` and `smallbook_x2f` tags; pass current
  tags on the command line or change the default.
- **Topic words in query-shape rules.** `textrules.TRAP_QUERY_RE`,
  `CODE_QUERY_RE` and `CODE_MATCH_RE` name `terraform` (and `hcl`), words from
  the first book's test set, inside a logic module. Replace them with a generic
  rule (code or install requests) or record why they stay; either way the
  cassette and batteries must stay green.
