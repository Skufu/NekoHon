# Forced-keyword probe (2026-10-13)

Follow-up to `multihop-report.md`: the loop never picked keyword (26/26
decisions chose semantic) even though hand-written keyword queries reach every
missed chunk at rank 1-5. This probe asks the narrower question: if the second
step is *forced* to keyword, can the model's own query reach the chunk dense
search missed?

Method: one semantic step with the original question (the loop's opener), then
the decision prompt with one forced line ("The next step must use the keyword
tool. Reply with exactly two lines..."). The parsed query runs through the real
`agentic.KeywordTool`. 4 questions, one sample each, temperature 0. Raw:
`multihop-forced-keyword.txt`.

| question | missed chunk(s) | model's keyword query | rank | verdict |
|---|---|---|---|---|
| CDC mechanism | ch05-018 / ch02-023 | question echoed verbatim | not in top-10 | fail |
| PII access control | ch10-011 | near-verbatim reword | rank 10 | partial (top-10, not top-5) |
| MDM / governance | ch02-013 | "What is master data management, data governance connection book" | **rank 2** | win |
| streaming preserves | ch07-007 / ch02-020 | question echoed verbatim | none / rank 2 | half |

Reading: forcing the tool does not force a *keyword-shaped* query. In 2 of 4
cases the model echoed the question, which keyword search dilutes; the one
compressed query ("...governance connection book") reached the missed chunk at
rank 2. The bottleneck is query shape, not tool choice — a next iteration would
be a decision prompt that asks for the rare content words explicitly, and this
single sample does not measure that.

No wiring conclusion changes: still no measured end-to-end win, still parked
pending the user's call (night report, decision 3).
