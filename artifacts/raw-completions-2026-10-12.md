# Raw completions — four failing asks (post-v1 step 1)

Captured 2026-10-12, before any code change. Model tag `qwen2.5:7b` via Ollama on 127.0.0.1:11434; index `data/index.json` (embedder `nomic-embed-text`, 768 dims, 1065 chunks).
Prompts came from the real modules (`answer.user_message`, `prompt.SYSTEM`).
Fragment rule: a whole passage sentence (or 80-char window) of at least
40 chars inside the raw completion. Longest run: difflib over folded text.
Full passages and prompts: `artifacts/raw-completions-2026-10-12.json`.

| id | question | verdict |
| --- | --- | --- |
| golden-05 | Where does storage sit in the data engineering lifecycle? | MODEL (near-verbatim copy: longest run 71 chars from ch06-001; the model edited the copy, so the exact-substring check refused) |
| golden-10 | What do transformations do in the data engineering lifecycle? | MODEL (near-verbatim copy: longest run 96 chars from ch02-025; the model edited the copy, so the exact-substring check refused) |
| typo-cru | What does CRU stand for? | MODEL (bare refusal in raw text) |
| typo-et | What happens to data after it is extracted in ET? | answered; not failing in this capture |

Repeat check (same session): each typo ask was sent three times in total — `typo-cru` refused 3/3, `typo-et` answered 3/3 with the ch07-033 quote. The `planning-context.md` claim that both typos refuse did not reproduce for `ET`; the earlier ET wording was never recorded verbatim, so this capture uses golden #9 with `ETL` -> `ET`.

## golden-05 — Where does storage sit in the data engineering lifecycle?

- kind: golden refusal
- retrieval (top 5):
  - rank 1 score 0.8698 ch06-001 ch6 "Chapter 6. Storage"
  - rank 2 score 0.8223 ch02-002 ch2 "What Is the Data Engineering Lifecycle?"
  - rank 3 score 0.8217 ch06-130 ch6 "Conclusion"
  - rank 4 score 0.8095 ch01-006 ch1 "The Data Engineering Lifecycle"
  - rank 5 score 0.8072 ch02-096 ch2 "Conclusion"
- seconds: search 0.11, generate 0.47

Raw completion:

```text
[Ch. 6] "Storage is the cornerstone of the data engineering lifecycle and underlies its major stages—ingestion, transformation, and serving."
```

- parse_completion: refused=True
- [Ch.] line checks (quote vs retrieved passages):
  - tag ch6 -> NO MATCH: "Storage is the cornerstone of the data engineering lifecycle and underlies its major stages—ingestio..."
- whole-sentence fragments found in raw completion:
  - none
- longest verbatim run: 71 chars (ch06-001): " and underlies its major stages—ingestion, transformation, and serving."
- difflib opcode check: the one edit is the deleted ` (Figure 6-1)`; the edited sentence occurs nowhere else in the index.
- verdict: MODEL (near-verbatim copy: longest run 71 chars from ch06-001; the model edited the copy, so the exact-substring check refused)

## golden-10 — What do transformations do in the data engineering lifecycle?

- kind: golden refusal
- retrieval (top 5):
  - rank 1 score 0.829 ch02-025 ch2 "Transformation"
  - rank 2 score 0.8184 ch08-164 ch8 "Conclusion"
  - rank 3 score 0.8174 ch08-001 ch8 "Chapter 8. Queries, Modeling, and Transformation"
  - rank 4 score 0.816 ch02-026 ch2 "Key considerations for the transformation phase"
  - rank 5 score 0.8124 ch02-027 ch2 "Key considerations for the transformation phase"
- seconds: search 0.07, generate 0.59

Raw completion:

```text
[Ch. 2] "Transformation means data needs to be changed from its original form into something useful for downstream use cases." Transformation involves altering data to make it useful for further processing or analysis.
```

- parse_completion: refused=True
- [Ch.] line checks (quote vs retrieved passages):
  - tag ch2 -> NO MATCH: "Transformation means data needs to be changed from its original form into something useful for downs..."
- whole-sentence fragments found in raw completion:
  - none
- longest verbatim run: 96 chars (ch02-025): " data needs to be changed from its original form into something useful for downstream use cases."
- difflib opcode check: lead-in rewritten (`The next stage of the data engineering lifecycle is transformation, meaning` -> `Transformation means`); the rest is verbatim. The edited sentence occurs nowhere else in the index.
- verdict: MODEL (near-verbatim copy: longest run 96 chars from ch02-025; the model edited the copy, so the exact-substring check refused)

## typo-cru — What does CRU stand for?

- kind: typo
- retrieval (top 5):
  - rank 1 score 0.6754 ch05-019 ch5 "CRUD"
  - rank 2 score 0.6069 ch01-066 ch1 "Chief information officer"
  - rank 3 score 0.5611 ch01-069 ch1 "Chief analytics officer"
  - rank 4 score 0.5562 ch01-067 ch1 "Chief technology officer"
  - rank 5 score 0.5553 ch01-068 ch1 "Chief data officer"
- seconds: search 0.07, generate 0.13

Raw completion:

```text
Not in this book.
```

- parse_completion: refused=True
- [Ch.] line checks (quote vs retrieved passages):
  - none (no line starts with [Ch.])
- whole-sentence fragments found in raw completion:
  - none
- longest verbatim run: 6 chars (ch01-069): " this "
- verdict: MODEL (bare refusal in raw text)

## typo-et — What happens to data after it is extracted in ET?

- kind: typo
- retrieval (top 5):
  - rank 1 score 0.7109 ch07-033 ch7 "ETL Versus ELT"
  - rank 2 score 0.6946 ch02-022 ch2 "Push versus pull"
  - rank 3 score 0.6865 ch07-031 ch7 "Snapshot or Differential Extraction"
  - rank 4 score 0.6791 ch02-024 ch2 "Push versus pull"
  - rank 5 score 0.6785 ch02-023 ch2 "Push versus pull"
- seconds: search 0.07, generate 0.55

Raw completion:

```text
[Ch. 7] "Once data is extracted, it can either be transformed (ETL) before loading it into a storage destination or simply loaded into storage for future transformation."
```

- parse_completion: refused=False
- [Ch.] line checks (quote vs retrieved passages):
  - tag ch7 -> ch07-033: "Once data is extracted, it can either be transformed (ETL) before loading it into a storage destinat..."
- whole-sentence fragments found in raw completion:
  - ch07-033 (160 chars): "Once data is extracted, it can either be transformed (ETL) before loading it into a storage destination or simply loaded into storage for fu..."
- longest verbatim run: 160 chars (ch07-033): "once data is extracted, it can either be transformed (etl) before loading it into a storage destination or simply loaded into storage for future transformation."
- verdict: answered; not failing in this capture
