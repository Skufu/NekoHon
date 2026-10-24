# Elided follow-up loses its subject before retrieval (2026-10-25)

Read-only trace; no model run. Reproduction is the given measurement, row `mt-elision-03`.

## 1. Where history is used, where it is dropped
Used: `ask` clips it (`answer.py:3132`), classifies the turn (`:3137`), and passes it to
`_resolve_contextual_query` (`:3203-3206`), whose `_extract_subject_from_history`
(`:1552-1586`) yields `consistency mean inside ACID` (`:1568-1571`).

Dropped: the pre-retrieval shortcut that answers the prior citation is gated on
`SIMPLIFY_RE` (`:3139`; twin `:3583`). `SIMPLIFY_RE` (`:1473-1486`) has no gist cue; the
cue added in the working tree sits in `SIMPLE_CUES` (`:297-299`, `git diff`), read only
by `simple_words` (`:303-306`). `_is_generic_followup` is also `SIMPLIFY_RE`-based
(`:1517-1520`), so the subject-prefix guard (`:2525-2531`) is false and the resolver
returns its input unchanged (`:2585`); the subject at `:3208` only vets a citation
after generation (`:3360-3375`).

Caveat: `Regarding <subject>: ...` can only come from `:2524`/`:2531`; for `Give me the
gist.` neither fires (no deictic token `:2501`, no `SIMPLIFY_RE`/`GENERIC_FACETS_RE` hit
`:1594-1603`). The debug guard is not in this tree; the prefixed query missed the chunk too.

## 2. What `search()` receives
The resolved string: `asked_form` (`:3207`) -> `retrieval_context` (`:3209-3213`) ->
`search_fn` (`:2221`) or `rank_chunks` (`:2206-2207`). `canonical_query` is a no-op (ends
with `.`, `canonical.py:101-102`), so the embedding is the resolved string, not the original
and not subject-only (`retrieve.py:355-356` -> `:310`; `retrieve.py:75-85` folds whitespace).

## 3. Does `simple_words()` route around history?
No. In `ask` its only call is `:3394`, after the answer exists; in `respond` it selects
`_plain_body` (`:3663`, `:3872-3903`) after `retrieval_context` (`:3653-3657`). History is
skipped by `:3139`/`:3583` on `SIMPLIFY_RE`, not `simple_words` — that mismatch is the defect.

## 4. Why the history chunk never seeds retrieval
The only history-to-ranking channel is prior-quote seeding (`:2297-2347`), entered here
(`gist` is one novel word, so `_is_topic_shift_followup` returns False, `:1718-1727`).
The lookup fails: `prior_quote[:50]` (`:2314`) has single spaces, the chunk stores
`consistency\r\n refers` (`data/index.ddia.json:382106`), so `:2316`/`:2321` miss,
`target_idx` stays None and `:2340-2347` never runs. No-model proof: `_refusal` cites
`passages[:3]` (`:2054-2069`), and the measured `cited` has no chapter-7 chunk
(`artifacts/evidence/hard-mt/hard-mt-2026-10-24.model-nekohon_q35_2b_x3_2e.json:67-89`).

## Minimal fix
Normalize both sides of the lookup; no ids, thresholds, or index change (`AGENTS.md:138-151`).

```diff
--- a/answer.py  (retrieval_context, 2314-2321)
+++ b/answer.py
-            snippet = prior_quote[:50].lower()
+            snippet = re.sub(r"\s+", " ", prior_quote)[:50].lower()
             for i, c in enumerate(chunks):
-                if str(c.get("chapter")) == prior_chap and snippet in (c.get("text") or "").lower():
+                if str(c.get("chapter")) == prior_chap and snippet in re.sub(r"\s+", " ", c.get("text") or "").lower():
                     target_idx = i
-                    if snippet in (c.get("text") or "").lower():
+                    if snippet in re.sub(r"\s+", " ", c.get("text") or "").lower():
```

Test, added to `tests/test_plain_register.py` after `SimpleWordsTest` (`:70`); run `python -m unittest tests.test_plain_register` (`AGENTS.md:1334`):

```python
class ElidedPlainFollowupTest(unittest.TestCase):
    def test_gist_followup_seeds_the_prior_chunk(self):
        acid = {"chunk_id": "text00013-010", "chapter": "7",
                "text": "In the context of ACID, consistency\r\n refers to a “good state.”"}
        other = {"chunk_id": "text00008-009", "chapter": "3", "text": "Compaction …"}
        hist = [{"question": "What does consistency mean inside ACID?",
                 "answer": '[Ch. 7] "In the context of ACID, consistency refers to a “good state.”"'}]
        with mock.patch.object(A, "rare", return_value=False), \
             mock.patch.object(A, "second_reading", return_value=None), \
             mock.patch.object(A, "llm_second_reading", return_value=None):
            ctx = A.retrieval_context({"chunks": [other, acid], "figures": []},
                                      "Give me the gist.", history=hist,
                                      search_fn=lambda *a, **k: [dict(other)])
        self.assertEqual(ctx["passages"][0]["chunk_id"], "text00013-010")
```

Regressions: `:2340-2347` prepends up to four same-chapter chunks, so a whitespace-only
quote mismatch now leads with the prior chapter; `topic_shift` still gates real shifts
(`:2297`, `:1638-1646`) — re-check `mt-distraction` (3/3). Twin lookups (`:3152-3164`,
`:3596-3608`) stay CRLF-dead; cue-side `:1520` alone only prepends the subject.
