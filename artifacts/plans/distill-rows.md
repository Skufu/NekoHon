# Distill row types — small book-companion student

Sketch only. Do not train from this file. No scores claimed.

## Sources opened

- `artifacts/datasets/` filenames: `demo-questions.md`, `eval-set-plain.json`, `eval-set.json`, `owner-rated-2026-10-15.jsonl`, `qa-questions-overnight.json`, `qa-sweep-default.json`, `sealed-forms.json`, `training-list-2026-10-14.md`
- Sampled (first 40 lines): `eval-set.json`, `owner-rated-2026-10-15.jsonl`
- Distill training-row count in those files: **Not measured** (they are eval / owner-rated / sweep artifacts, not a distill corpus)
- Prompt system string **names** in `prompt.py`: `SYSTEM`, `SYSTEM_ANSWER`, `REFUSAL`, `SPELL_SYSTEM`, `PARAPHRASE_SYSTEM` (plus `ANSWER_MODEL` env default)
- Parsers: `answer.parse_completion`, `answer.parse_answered`

## Contract the student is learning

| Mode | Prompt name | Parser | Shape |
| --- | --- | --- | --- |
| quote-first + gloss | `SYSTEM` | `parse_completion` | `[Ch. N] "…passage…"`, then one plain gloss line; exact `REFUSAL` alone |
| free answer | `SYSTEM_ANSWER` | `parse_answered` | prose with `[Ch. N]` tags; quotes only when copied; exact `REFUSAL` alone |
| figures | both systems | both parsers via cited passages | name the figure in **passage text**; app attaches image — model never describes pixels |

`parse_completion`: unverified prose → contract refusal. Figure only if a **cited** passage names it.
`parse_answered`: keeps prose; strips marks the passages cannot back; uncited sentence stays uncited (hallucination is a measurement, not a forced refuse). Exact / free refusal paths still refuse.

---

## 1. Quote-first answer with a real passage span

**Teach:** start with `[Ch. N]`, copy a real span from the shown passage, nothing invented.

**Fields**

| field | type | notes |
| --- | --- | --- |
| `row_type` | `"quote_first"` | |
| `train` | `true` | |
| `mode` | `"ask"` | `SYSTEM` path |
| `question` | string | |
| `passages[]` | `{chunk_id, chapter, text}` | teacher-visible context |
| `completion` | string | teacher emit |
| `gold.citations[]` | `{chunk_id, chapter, quote}` | quote must be substring of passage text |
| `gold.refused` | `false` | |

**Fake example (5 lines of completion; watermark toy text, not the book)**

```text
Q: What is a watermark in this toy chapter?
passage ch99-001: A watermark marks the point after which late events may be dropped.
completion:
[Ch. 99] "A watermark marks the point after which late events may be dropped."
A watermark is the cut-off for late events.
```

**Parse**

- `parse_completion`: **accept** if the quoted span matches a shown passage (rebuilds contract body).
- `parse_answered`: **accept** as non-refuse prose if `[Ch. 99]` / wording overlaps a passage; may keep free shape rather than quote-first layout.

---

## 2. Short plain gloss after the quote

**Teach:** one simple-words line after the quote; definition-first when the passage defines a term; no fused multi-chapter mash.

**Fields**

| field | type | notes |
| --- | --- | --- |
| `row_type` | `"gloss_after_quote"` | |
| `train` | `true` | |
| `mode` | `"ask"` | |
| `question` | string | |
| `passages[]` | same as §1 | |
| `completion` | string | quote line(s) + single gloss line |
| `gold.gloss` | string | plain register; no new facts |
| `gold.citations[]` | as §1 | |
| `gold.refused` | `false` | |

**Fake example**

```text
Q: Explain a watermark in simple words.
passage ch99-002: The watermark is a threshold a window uses to decide lateness.
completion:
[Ch. 99] "The watermark is a threshold a window uses to decide lateness."
A watermark is a time line a window uses to call data late.
```

**Parse**

- `parse_completion`: **accept** — non-`[Ch.` lines become the gloss joined onto the contract answer.
- `parse_answered`: **accept** if tags/overlap hold; gloss is just more prose (no separate gloss field in that parser).

---

## 3. Exact refusal `Not in this book.`

**Teach:** when passages lack the answer, emit **only** `Not in this book.` (period included). No apology, no almost-quote.

**Fields**

| field | type | notes |
| --- | --- | --- |
| `row_type` | `"exact_refusal"` | |
| `train` | `true` | |
| `mode` | `"ask"` or `"answer"` | |
| `question` | string | out-of-book or empty-evidence |
| `passages[]` | may be empty or off-topic | |
| `completion` | `"Not in this book."` | must equal `REFUSAL` |
| `gold.refused` | `true` | |
| `gold.citations` | `[]` | |

**Fake example**

```text
Q: Who invented the watermark coffee brand in Paris?
passages: (none on-topic)
completion:
Not in this book.
```

**Parse**

- `parse_completion`: **accept as refusal** iff completion strips to exact `REFUSAL`.
- `parse_answered`: **accept as refusal** via `_free_refusal` / empty path (exact sentence still refuses).

Anything longer than that sentence fails the exact-refusal train target even if a parser later collapses it.

---

## 4. Figure-naming answer (attach by passage text, not pixels)

**Teach:** if the passage names a figure, quote/mention that naming line; never describe image pixels. App attaches from cited passage metadata.

**Fields**

| field | type | notes |
| --- | --- | --- |
| `row_type` | `"figure_naming"` | |
| `train` | `true` | |
| `mode` | `"ask"` preferred | |
| `question` | string | |
| `passages[]` | text **includes** figure name, e.g. `Figure 99-1` | |
| `figures[]` | catalog ids/names for the app | not model input pixels |
| `completion` | string | quote/mention the naming span |
| `gold.citations[]` | must include the naming passage | |
| `gold.figure_names[]` | from passage text only | |
| `gold.refused` | `false` | |

**Fake example**

```text
Q: Where does the book show a watermark timeline?
passage ch99-003: Figure 99-1 sketches a watermark moving across event time.
completion:
[Ch. 99] "Figure 99-1 sketches a watermark moving across event time."
The passage names Figure 99-1 for the watermark sketch.
```

**Parse**

- `parse_completion`: **accept** when quote matches; `figures_for` only on **cited** passages (not every retrieved hit).
- `parse_answered`: **accept** with tags/overlap; figures still follow cited passages only.
- Reject train target if completion describes colors/layout of pixels instead of the naming sentence.

---

## 5. Follow-up that must re-retrieve ("what about the next chapter")

**Teach:** prior turn context is not a license to reuse an old quote for a new chapter scope. Student must treat follow-up as a **new retrieval + new completion**; cross-chapter fill is wrong under `SYSTEM`.

**Fields**

| field | type | notes |
| --- | --- | --- |
| `row_type` | `"followup_rereetrieve"` | |
| `train` | `true` | |
| `mode` | `"ask"` | |
| `turn` | `2` (or `n`) | |
| `prior_question` | string | |
| `prior_chunk_ids[]` | ids used last turn | supervision only |
| `question` | string | e.g. next-chapter ask |
| `passages[]` | **new** retrieval for this turn | teacher must not paste turn-1 only |
| `completion` | string | cites only new turn passages |
| `gold.must_not_cite` | chunk ids from prior turn if off-scope | |
| `gold.citations[]` | from current passages | |
| `gold.refused` | `false` or `true` | true if new passages lack answer |

**Fake example**

```text
prior Q: What is a watermark?
prior cite: ch99-001
Q: What about the next chapter — how is watermark delay set?
passages this turn: ch100-010 only — "Chapter 100 sets watermark delay from max out-of-order gap."
completion:
[Ch. 100] "Chapter 100 sets watermark delay from max out-of-order gap."
Watermark delay follows the largest out-of-order gap in that chapter.
```

**Parse**

- Parsers see **one** completion + **current** `passages` only (no session memory inside `parse_*`).
- `parse_completion`: **accept** if Ch. 100 quote is in **this** call's passages; **refuse** if teacher re-emits ch99 text not in current passages.
- `parse_answered`: same grounding rule against the passages argument you pass in.
- Train label should mark rows that reuse prior-chapter quotes without re-retrieval as **fail targets**, not positives.

---

## 6. Reject row: teacher essay with no quote — `do-not-train`

**Teach nothing from these.** Hard-negative / filter label so a harvest pipeline drops ungrounded teacher essays.

**Fields**

| field | type | notes |
| --- | --- | --- |
| `row_type` | `"reject_unguarded_essay"` | |
| `train` | `false` | **do-not-train** |
| `label` | `"do-not-train"` | required |
| `question` | string | |
| `passages[]` | optional | |
| `completion` | string | multi-sentence essay, no usable quote / no exact refusal |
| `reject_reason` | `"no_quote"` / `"invented_gloss"` / … | |

**Fake example**

```text
Q: What is a watermark?
passages: ch99-001 present but ignored
completion:
A watermark is a clever streaming idea I will explain at length without citing
any sentence. It usually improves quality and is best practice worldwide today.
(do-not-train)
```

**Parse**

- `parse_completion`: **refuse** (no `[Ch.` / no verified span / not exact `REFUSAL`) — contract body is refusal, but the **raw teacher text must not enter the train set**.
- `parse_answered`: may **keep prose with empty citations** (uncited ≠ auto-refuse). That is exactly why this row is labeled `do-not-train`: parser acceptance is not permission to distill.

---

## Suggested shared envelope (all row types)

```json
{
  "id": "distill-watermark-001",
  "row_type": "quote_first",
  "train": true,
  "mode": "ask",
  "prompt_system": "SYSTEM",
  "question": "...",
  "passages": [{"chunk_id": "ch99-001", "chapter": "99", "text": "..."}],
  "completion": "...",
  "gold": {"refused": false, "citations": [], "gloss": null, "figure_names": []},
  "parse_expect": {"parse_completion": "accept|refuse", "parse_answered": "accept|refuse|uncited"},
  "source": "teacher-sketch",
  "book_text": "fake-watermark-toy"
}
```

## Out of scope here

- No training run, no loss, no token counts, no quality scores.
- No edits to `GOAL.md`, engine source, or datasets.
- Next check: when building a real distill harvest, filter `train:false` / `do-not-train` before any finetune file is written; verify each kept row with `parse_completion` (ask mode) or `parse_answered` (answer mode) against the same `passages` list stored on the row.
