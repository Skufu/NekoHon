# Reader failure moments — code-backed

Moments a book-companion user can feel the app is broken.
Source: live code paths named below, plus `artifacts/pipeline-audit.md` (bugs) and `artifacts/ui-review.md` (failures section). Taste is out.

Rank is **assumed** unless marked measured. Cap 12. No product pitch.

How to read each row: what they see → code cause → does another chat make it worse → smallest fix class.

---

## Ranked moments

### 1. Answer mode sits on “Looking…” with no words

- **What the user sees:** Default mode is `answer`. The pane shows `Looking… N s` (and after 8 s the cold-load note). No tokens until the whole body lands. Owner rated a blank pane **bad** on a live sample (`artifacts/evidence/answer-quality/*`, note on micro-partitioning).
- **Code cause:** `server.py` `Handler._stream_ask` → nested `generate`: `live` is false for mode `"answer"` without prefill, so `on_token=None`. The first `respond` draft is held because a later `_retry_uncited` may discard it. `web/components/AskPane.tsx` only leaves `status === "loading"` when no `streamText` has arrived.
- **Follow-up chat:** Worse. Another ask pays the same hold again; cold model reload can add ~25 s.
- **Fix class:** Contract change (stream a held draft with an honest reset, or show structured progress). Copy change alone does not shorten the wait.
- **How often:** **High** (default mode). Hold itself is **measured** in frontend phase-1 stream checks; blank-pane owner hit is **measured**. Frequency of “feels broken” is assumed high.

### 2. Tag-first answer comes back with no citations (or only after a silent redo)

- **What the user sees:** An answer that looks quote-shaped (`[Ch. N] "…"`) but chips are empty, or the text vanishes and rebuilds under “Re-checking the quote…”.
- **Code cause:** `answer.py` `parse_answered` → `_sentence_claims`: claims are only text **before** a `[Ch.` tag. A completion that is only `[Ch. 5] "quote"` + gloss yields **zero** claims, so `citations == []` and `refused` stays false. `respond` then calls `_retry_uncited` (prefill `[Ch. `). Audit bug #1; tests pin the empty-citation shape.
- **Follow-up chat:** Can get worse. Retry is one-shot; a second user rephrase may draw another uncited draft and another held wait.
- **Fix class:** Contract change (parser must accept tag-first ask shape without needing the retry). Model change reduces how often the draft is uncited.
- **How often:** **High** for anything that starts with `[Ch.` in answer mode. Parser gap is code-certain; how often the retry saves it is **measured** historically (x2d Turn-1 vs retry-rescued suite), not re-measured this pass.

### 3. Retry fails — uncited prose is kept as a “real” answer

- **What the user sees:** A fluent answer with no usable citation chips (or chips that don’t match the words). Looks like the book spoke; it didn’t bind a passage.
- **Code cause:** `answer.py` `_retry_uncited`: kept only when a candidate parse has citations and every `quote` passes `_quote_in_passage`. Any failure returns `None`; `respond` keeps the original uncited body. Same monotone rule when the generator rejects prefill (`except Exception: return None`).
- **Follow-up chat:** Worse if the user trusts the prose and asks a narrower follow-up that builds on it.
- **Fix class:** Contract change (refuse or re-ask when still uncited after retry). Model change (cite on Turn-1).
- **How often:** **Medium** on fragments, order-flips, bare topics (suite history). Assumed for a casual reader; suite miss rates were **measured** on older draws, not this pass.

### 4. “Not in this book.” when the book does have it (ask mode)

- **What the user sees:** Exact refusal, often with “nearest misses” chips and sometimes “nearby, not an answer” figures.
- **Code cause:** `answer.py` `ask` → `parse_completion`. Failed quote / span match returns `_refusal` (`refused: True`, answer exactly `Not in this book.`). Also fires when the model is gloss-first (audit bug #2: anything not starting with `[Ch.` goes through `_tagless_citation`, else refuse). Truncation under `num_predict: 512` in `ollama_generate` can cut a quote and fail the gate (audit latency trap).
- **Follow-up chat:** Sometimes better (rephrase / full sentence), sometimes same wall on ceiling forms (`why does`, `why's …` — **measured** as shared teacher/student ceilings in probe reports).
- **Fix class:** Model change for ceiling forms. Contract change for gloss-first and short-quote false refusals. Copy change cannot make a refusal true.
- **How often:** **Medium** day-to-day; **high** on causal / contracted “why” forms (**measured** on sealed/owner probes).

### 5. Answer mode invents wording and still looks grounded

- **What the user sees:** Full prose, `refused: false`, maybe chapter chips from overlap — but sentences the page never said. Or a good quote line plus a second line of unchecked gloss.
- **Code cause:**
  - Audit bug #4: `parse_answered` always sets `refused: False` for non-empty non-refusal text; zero-overlap sentences stay uncited rather than refused.
  - Audit bug #3: `parse_completion` keeps `gloss` lines with no book check (`test_the_gloss_line_rides_beside_the_quote`). `web/lib/answer.ts` `splitAnswer` then prefers gloss-first layout, so invented gloss can lead the card.
- **Follow-up chat:** Worse — the next turn treats the gloss as shared fact.
- **Fix class:** Contract change (gate or mark unchecked gloss; optional refuse-on-zero-citation in answer mode — product decision, audit says do not “fix” without one). Model change reduces invention rate.
- **How often:** **Medium** (every ask-mode gloss line is unchecked by design; free-prose miss rate assumed).

### 6. Engine down / stream drop — error text, or a silent half-state

- **What the user sees:** “Engine unreachable — start it on :8000…”, “answer model unavailable”, “The connection dropped before the answer finished — ask again.”, or a partial stream with an error.
- **Code cause:**
  - `web/lib/store.ts` `useAsk` `onError`: sets `status: "error"`, **clears** `streamText` (ui-review’s “does not clear streamText” is **stale** vs current code).
  - Same file’s `.catch` on `askStream` for non-abort errors sets the unreachable copy but **does not** clear `streamText` (edge if anything was already appended).
  - `web/lib/engine.ts` `askStream`: EOF without `final`/`error` → `onError`.
  - `server.py` `_stream_ask` / `do_POST`: model/url failures → error frame or HTTP 500 `"answer model unavailable"`.
- **Follow-up chat:** Better only after the engine is up; rapid re-asks while `controller` is set are dropped (`begin` early-return, no message) — feels dead.
- **Fix class:** Copy change (busy/ignore message). Contract change (clear `streamText` on every error path; queue or reject-with-reason).
- **How often:** **Low** once setup works; **high** on first-run / Ollama stopped. Assumed.

### 7. Window UI long silent wait (and empty body edge)

- **What the user sees:** At `http://127.0.0.1:8000` (`window/index.html`), the box shows `Looking...` until a single JSON body returns (no token stream). Network/JSON failures now map to explicit strings (ui-review “stuck on Looking...” without try/catch is **stale**). An OK body with empty `answer` and no `error` still lands as a blank string: `body.answer || body.error || ""`.
- **Code cause:** `window/index.html` submit handler (non-stream `POST /ask`). Engine still does full retrieval + generate before respond.
- **Follow-up chat:** Same wait each time; dual homepage means Next fixes at :3100 do not change what :8000 shows (`ui-review` dead-UI note).
- **Fix class:** Contract change (stream=1 client). Copy change for empty-body terminal state.
- **How often:** **Medium** if the reader uses the engine homepage; **low** if they only use :3100. Assumed which surface wins.

### 8. Plain-words ask feels frozen longer than a normal ask

- **What the user sees:** “in simple words” (and other `SIMPLE_CUES`) → long `Looking…`, then a rewritten answer, or the draft if rewrites come back empty.
- **Code cause:** `answer.py` `respond` → `simple_words` → `_plain_body`: one `SYSTEM_ANSWER` draft plus up to `PARAPHRASE_LIMIT` (5) rewrite calls, all held from the token stream (audit: plain register draft/rewrites held).
- **Follow-up chat:** Worse latency if they keep the cue on every turn.
- **Fix class:** Contract change (stream rewrite progress or cap calls with visible budget). Copy change (“rewriting N sentences…”).
- **How often:** **Low–medium** (only cued questions). Assumed.

### 9. Degenerate or almost-empty input gets a real-looking quote

- **What the user sees:** Whitespace-only, or thin prompts like `what is`, answered with some grounded quote as if they asked a topic. Owner: WRONG.
- **Code cause:** `server.py` `do_POST` only rejects missing/`falsy` `question` (a space is truthy). `respond`/`ask` retrieve on that string and generate. **Measured** on owner-style probe / training-list notes: whitespace-only → arbitrary grounded quote. Pre-generation refuse rule called out, not shipped.
- **Follow-up chat:** Confuses the reader about what “Not in this book.” means; next real ask may still work.
- **Fix class:** Contract change (refuse when no content word survives). Not a model problem.
- **How often:** **Low** for careful readers; **medium** for fat-finger / opener typos. Whitespace case **measured**.

### 10. Closing the ask pane mid-flight — answer disappears, Stop gone

- **What the user sees:** Sidebar toggle unmounts `AskPane`. In-flight work continues (`controller` still set). No Stop. No stream unless a margin card is up. Later `begin` no-ops while busy.
- **Code cause:** `web/app/page.tsx` `{sidebarOpen ? <AskPane /> : null}`; `web/lib/store.ts` module-level `controller`; `ui-review` loading/error gaps.
- **Follow-up chat:** Worse — reopen can show a finished body, or ignore submit while the old controller lives.
- **Fix class:** Contract change (keep Stop mounted, or abort on unmount — pick one). Copy change is not enough.
- **How often:** **Medium** on narrow layouts / toggle habit. Assumed.

### 11. Highlight “ask about this passage” ignores the passage

- **What the user sees:** Lens copy implies the selection matters. Typed question sends only `{ mode: "ask", question }` — engine never receives `selection`. Answer can drift off the marked paragraph.
- **Code cause:** `web/lib/store.ts` `askSelection` typed branch; `server.py` ask path only reads `request["question"]`. `ui-review` API mismatch #2.
- **Follow-up chat:** Worse if they tighten the question without re-selecting; explain-without-typing does send `selection`.
- **Fix class:** Contract change (pass selection into retrieval, or change the lens copy). Copy change alone if product keeps question-only ask.
- **How often:** **Medium** among selection users; **low** overall. Assumed.

### 12. Citation chips / reader-first layout don’t match what they read

- **What the user sees:** Verbatim block instead of gloss-first card; or chips jump to a sentence that is evidence-overlap, not the words on screen. Quote click can miss once (`content-visibility` + delayed `scrollIntoView`).
- **Code cause:** `web/lib/answer.ts` `splitAnswer` returns `ok: false` when any citation quote is missing from the answer string — common when `parse_answered` built `quote` via `_evidence_quote` (passage sentence) rather than a span present in the model text. `AskPane` / `AnswerView` fall back to verbatim + chips. Reader jump: `ChunkBlock` scroll retry (ui-review).
- **Follow-up chat:** Neutral to slightly worse (user re-asks “where is that?”).
- **Fix class:** Contract change (citation quote must be a substring of `answer`, or UI must not require it). Copy change for “couldn’t mark the quote”.
- **How often:** **Medium** in answer mode after retry/evidence-quote. Assumed; matcher 3/3 check in phase-1 was on real quotes that *did* appear in blocks, not on this split failure.

---

## Named five — confirmation snapshot

| Named path | Confirmed in code? | Reader-facing failure? |
| --- | --- | --- |
| `answer.py` `parse_answered` / `_sentence_claims` | Yes — tag-first → empty claims | Yes (moments 2–3, 5) |
| `answer.py` `_retry_uncited` | Yes — monotone drop-back to uncited draft | Yes (2–3) |
| `server.py` `_stream_ask` hold | Yes — `live` false for answer draft | Yes (1, 8) |
| `window/index.html` Looking | Partially — try/catch **present** now; non-stream wait + empty `answer` remain | Yes as long wait / blank edge (7); “stuck Looking forever on throw” is outdated |
| `web` store `onError` | Partially — `onError` **clears** `streamText`; unreachable `.catch` does not; silent busy `begin` remains | Yes as engine-down / half-state (6); dual partial+error render claim is outdated |

---

## Out of the twelve (still real, rarer)

- Figure number forms (`4.4` vs `4-4`) and “what’s in the figure” — plan parked; not a daily chat path.
- Letter-prefixed / table figure attach — audit #6; fixed letter path exists in `figures.number_from_id` today; tables still not matched by `Figure`/`Fig.` only.
- Quiz leak / dual homepage / missing quiz on Next — operator surfaces, not the main reader loop.

---

## Method notes

- No product proposal. No `GOAL.md` edit. No source edits this pass.
- Rank labels are **assumed** unless a line says **measured**.
- ui-review items contradicted by current `window/index.html` and `store.ts` are marked stale above rather than repeated as live bugs.
