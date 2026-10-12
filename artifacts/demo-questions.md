# Demo sheet — measured 2026-10-12

The 10 golden questions (`tests/fixtures/questions.json`) run end-to-end
through `POST /ask` on this machine, plus explain and quiz examples.
Expected answers are what the engine actually returned that day.
Engine: `python server.py`; page at `http://127.0.0.1:8000/`.
Re-measured 2026-10-12 after the sentence-boundary re-chunk: four chunk ids
moved (watermark and atermark ch08-040 -> ch08-039, batch versus streaming
ch02-018 -> ch02-019, transformations ch02-025 -> ch02-027, multicloud
ch04-038 -> ch04-037) and two answers changed their sentence, because the
boundary moved under the model. Later the same day the heading line that had
leaked into the transformations quote was dropped, and answers began attaching
only figures named by the passage they cited.

## What "Highlighted text" means

Explain mode only. Paste an exact sentence from the book there (copy it from
your reader; the page shows no book text). Explain treats that sentence as
the question and quotes from its neighborhood. "Ask the book" is ignored in
explain mode. Text that is not in the book gets `Not in this book.`

## Ask mode — 10 questions, all answered (2026-10-12, after the span fix)

| Ask this | Measured result |
| --- | --- |
| What does CRUD stand for? | ch05-019: `"CRUD, which stands for create, read, update, and delete..."` |
| What is data ingestion? | ch07-002 + `figure-7-2`: `"Data ingestion is the process of moving data..."` |
| What is a watermark? | ch08-039 + `figure-8-8` |
| When is an insert-only table useful? | ch05-020: `"The insert-only pattern retains history directly in a table..."` |
| Where does storage sit in the data engineering lifecycle? | ch06-001: `"and underlies its major stages—ingestion, transformation, and serving"` (the model dropped `(Figure 6-1)`; the kept span is the copied part) |
| What do source systems provide to the rest of the lifecycle? | ch02-005: `"A source system is the origin of the data..."` |
| How does data architecture relate to enterprise architecture? | ch03-013: `"Data architecture is a subset of enterprise architecture..."` |
| What is the difference between batch and streaming? | ch02-019: `"Batch processing remains an extremely popular way to ingest data for downstream consumption, particularly in analytics and ML"` |
| What happens to data after it is extracted in ETL? | ch07-033: `"Once data is extracted, it can either be transformed (ETL)..."` |
| What do transformations do in the data engineering lifecycle? | ch02-027: `"Logically, we treat transformation as a standalone area of the data engineering lifecycle..."` — this quote used to open with the chunk's heading line; the answer layer drops it now |

## Explain mode — example selections

| Paste into Highlighted text | Measured result |
| --- | --- |
| `Data ingestion is the process of moving data from one place to another` | ch07-002, quoted back |
| `CRUD, which stands for create, read, update, and delete, is a transactional pattern commonly used in programming and represents the four basic operations of persistent storage` | ch05-019: `"CRUD is the most common pattern for storing application state in a database"` |
| `A watermark (Figure 8-8) is a threshold used by a window to determine whether data in a window is within the established time interval or whether it’s considered late` | ch08-039 |

## Quiz mode

No fixed list: every click picks a random chunk and writes a new question.
Example (2026-10-12):

- Q: `What are the key outcomes of the modern data stack?`
- Key (ch03-088, behind "Show the key"): `Note that the notion of a modern data stack integrates nicely with the converged data platform idea from the previous section.`
- The question does not contain the key sentence (topic words may overlap — the rule is the whole sentence). A leak becomes a refusal instead.

## Edge cases seen while testing

- Small typos: retrieval keeps the right chunk at rank 1 (`CRU` -> ch05-019,
  `ET` -> ch07-033) and both now answer. `CRU` quotes `"stands for create,
  read, update, and delete"` from ch05-019 (the model drops `, which`; the
  kept span is the copied part).
- Refusals can still show nearest-miss figures (storage question above).
- Improvement ideas live in `AGENTS.md` "Post-v1 backlog".
