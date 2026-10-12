# Demo sheet — measured 2026-10-12

The 10 golden questions (`tests/fixtures/questions.json`) run end-to-end
through `POST /ask` on this machine, plus explain and quiz examples.
Expected answers are what the engine actually returned that day.
Engine: `python server.py`; page at `http://127.0.0.1:8000/`.

## What "Highlighted text" means

Explain mode only. Paste an exact sentence from the book there (copy it from
your reader; the page shows no book text). Explain treats that sentence as
the question and quotes from its neighborhood. "Ask the book" is ignored in
explain mode. Text that is not in the book gets `Not in this book.`

## Ask mode — 10 questions, 8 answered, 2 refused

| Ask this | Measured result |
| --- | --- |
| What does CRUD stand for? | ch05-019: `"CRUD, which stands for create, read, update, and delete..."` |
| What is data ingestion? | ch07-002 + `figure-7-2`: `"Data ingestion is the process of moving data..."` |
| What is a watermark? | ch08-040 + `figure-8-8` |
| When is an insert-only table useful? | ch05-020: `"The insert-only pattern retains history directly in a table..."` |
| Where does storage sit in the data engineering lifecycle? | REFUSED: `Not in this book.` (2 nearest-miss figures shown) |
| What do source systems provide to the rest of the lifecycle? | ch02-005: `"A source system is the origin of the data..."` |
| How does data architecture relate to enterprise architecture? | ch03-013: `"Data architecture is a subset of enterprise architecture..."` |
| What is the difference between batch and streaming? | ch02-018: `"Batch ingestion is a one-way door..."` |
| What happens to data after it is extracted in ETL? | ch07-033: `"Once data is extracted, it can either be transformed (ETL)..."` |
| What do transformations do in the data engineering lifecycle? | REFUSED: `Not in this book.` |

## Explain mode — example selections

| Paste into Highlighted text | Measured result |
| --- | --- |
| `Data ingestion is the process of moving data from one place to another` | ch07-002, quoted back |
| `CRUD, which stands for create, read, update, and delete, is a transactional pattern commonly used in programming and represents the four basic operations of persistent storage` | ch05-019: `"CRUD is the most common pattern for storing application state in a database"` |
| `A watermark (Figure 8-8) is a threshold used by a window to determine whether data in a window is within the established time interval or whether it’s considered late` | ch08-040 |

## Quiz mode

No fixed list: every click picks a random chunk and writes a new question.
Example (2026-10-12):

- Q: `What are the key outcomes of the modern data stack?`
- Key (ch03-088, behind "Show the key"): `Note that the notion of a modern data stack integrates nicely with the converged data platform idea from the previous section.`
- The question does not contain the key sentence (topic words may overlap — the rule is the whole sentence). A leak becomes a refusal instead.

## Edge cases seen while testing

- Small typos: retrieval keeps the right chunk at rank 1 (`CRU` -> ch05-019,
  `ET` -> ch07-033) but the answer layer may refuse (`What does CRU stand
  for?` refused). Spell terms correctly for demos.
- Refusals can still show nearest-miss figures (storage question above).
- Improvement ideas live in `AGENTS.md` "Post-v1 backlog".
