# Query-coverage gaps — owner query surface (2026-10-14)

Coverage audit of the owner's hand-typed query surface against existing
artifacts, plus a proposed 30-item exploratory probe list for an engineer to
build. **No Ollama calls and no model generations were run for this report.**

Sources read for coverage: `probes/probe-fragment-2026-10-14.py` (sealed 21),
`probes/probe-trial-queries-2026-10-14.py` (visible ten),
`probes/probe-second-book-2026-10-14.py`, `probes/probe-contamination-2026-10-14.py`,
`probes/probe-engine-edges-2026-10-14.py`,
`evidence/user-query-probes-2026-10-14.md`, `reports/x2d-forms-2026-10-14.md`,
`datasets/training-list-2026-10-14.md`, `datasets/qa-questions-overnight.json`
(124 questions; styles what-is 59 / bare 32 / subject-first 13 / list 10 /
quiz 10), all of `data/finetune/quote-refuse-2026-10-13.*.jsonl` asked forms
(135 bench + up to 984 train rows per file, 1365 distinct strings deduped) and
`data/finetune/x2d-forms-2026-10-14.json` (171 forms).

Method notes, so the numbers are auditable:

- Local read-only python only. Term presence/absence was measured by
  substring search over `data/index.json` (1042 chunks). Asked-form novelty was
  measured over every `meta.question` / `meta.asked` / `Question:`-first-line
  across the finetune files plus the x2d-forms file.
- The canonical-form outputs below were computed by importing `canonical.py`
  locally for the exact item strings — deterministic, no model, no Ollama.
  Clearly marked where used.
- The sealed-items rule lives in the artifacts, not in `AGENTS.md`: the
  fragment suite header says "SEALED — never train on these items" and
  `training-list-2026-10-14.md` says "The sealed items themselves are never
  trained." (`AGENTS.md` has no such line; checked via grep.) Every proposed
  item below is new against the sealed 21 strings and against the visible ten.

## 1. Coverage table

| query-form class | what covers it today | status |
| --- | --- | --- |
| Statement forms (assertions, not questions) | Owner hand run "is Hadoop dead" works [owner observation, not in any artifact]; bench-x2d has the hybrid "Data engineers need to be pragmatic about?"; train-x2d has quiz-completion statement shapes ("batch processing remains an extremely popular way to do what", "kimball is on the opposite end of the data modeling spectrum from who"). No probe item is a free assertion. Measured: a bare assertion without a period gets double-verbed by canonicalization ("storage is the cornerstone…" -> "What is storage is the cornerstone…?"), see §3. | partial |
| Shorthands / abbreviations of book terms | "auto" for "automated" is the known false refusal [owner, this session; being trained]; book abbreviations exist only as full phrases in training ("what is total cost of ownership", "what is change data capture") and as lowercase case-mix wh-forms (PII/OLTP via x2c swaps); trailing-letter family sealed (etls/meshs/pipeliness). Bare shorthand forms "tco"/"cdc"/"scd": 0 occurrences in all 1365 asked forms. | partial |
| Contractions ("what's", "how's", "doesn't") | Nothing. 0 of 1365 asked forms contain a wh-contraction; bench/train/sealed all clean; canonicalization passes "what's" through unchanged (measured, §3). | missing |
| Possessives ("watermark's purpose") | Nothing. 0 occurrences anywhere; canonical prefixes it ("What is watermark's purpose?"), measured. | missing |
| Punctuation noise ("?", "???", trailing "...", commas) | Nothing. No item in any probe carries doubled marks, ellipsis, or a trailing comma; canonical passes all three shapes through unchanged (measured, §3). | missing |
| Degenerate input (whitespace-only, symbols-only) | Partial by hand: "what is" (zero-content) and "hey" documented in `evidence/user-query-probes-2026-10-14.md` and `probe-engine-edges-2026-10-14.py` case c; R1/R2/R3 pre-generation rules recommended, **not shipped**. Whitespace-only and symbols-only inputs never probed; no contract. | partial |
| Chapter-level questions ("what is chapter 6 about?") | Nothing. 0 "chapter" forms in bench/train/x2d-forms/suites; chapter-intro chunks exist (ch06-001, ch08-001 verified) and citations are literally `[Ch. N]`, but no route or probe covers chapter-scoped asks. | missing |
| "meaning of X" / "X means what" | Partial via the overnight sweep only: subject-first/quiz definition shapes ("crud stands for what", "togaf defines data architecture as what", "data ingestion is the process of doing what"). "meaning of" and "means what" literally: 0 occurrences in all measured files; never probed through the answer seam. | partial |
| False-premise questions ("why did HDFS shut down?") | Nothing. Out-of-book controls exist (offside rule, violin strings — sealed; capital of France — bench + second-book control) but no probe asserts a false event about an entity that IS in the book. | missing |
| Cross-book topic contamination asked against the FDE book | Nothing in this direction. The second-book probe runs the reverse (FDE controls — watermark, France, lakehouse — against the quant book); `probe-contamination-2026-10-14.py` compares train-vs-bench strings, not asks. Measured on `data/index.json`: 0 chunks contain "quantization", "gptq", "turboquant", "kv cache", "straight-through", "affine", "zero point", "accuracy cliff" (case-insensitive substring). | missing |
| "vs" pairs beyond batch/streaming and column/row | Partial: x2c trained 10 order flips (data science/engineering, internal/external facing, brownfield/greenfield, immutable/transitory, schema on read/write, etl/elt, bounded/unbounded, push/pull, olap/oltp, hashing/encryption); x2d greets added pair-topics; sealed covers only batch/streaming and column/row. Real in-book pairs with no coverage: lambda/kappa (ch03-086/087/088) and eventual/strong consistency (ch06-023) — 0 occurrences of either pair form in all measured files. | partial |
| Polite greeting+question combos | Partial: x2d trained 23 `hey can you tell me about X` forms (visible targets; the hey→they repair entanglement is documented in `x2d-forms-2026-10-14.md`); bench has 2 `hey …` items. Clause-tail variants ("hey can you tell me what X is") and modal requests ("could you explain X") never probed. | partial |
| Content-word typos (not acronyms) | Partial: sealed trailing-letter class (etls/meshs/pipeliness), trained "normailzation", bench watermark typos ("watermak", "atermark"); the reading repair (`readings.py`, CUTOFF 0.85) owns typos and the x2d report explicitly routes "observabilty" to it ("the engine's reading repair owns typos, per P2-1"). Non-watermark content-word substitutions never probed. Note: "watermerk" would be a near-string of the bench's "watermak" — deliberately not proposed. | partial |
| Topic casing | Partial: x2c swaps train case-mix probes ("what is PII", "what is an OLTP system") and several trained pairs keep caps (MAD, CRUD, RAID, ETL/ELT). All-caps topic variants ("DATA MESH") and lowercase proper nouns never probed; sealed bare topics are Title Case only. | partial |
| Compound two-part questions | Nothing. No item anywhere asks two questions in one string; overnight quiz/list styles are single-purpose. | missing |

## 2. Proposed items (30)

Legend — expectation: `answered+cited` = not refused, >= 1 citation;
`exact refusal` = refusal and answer is exactly `Not in this book.`;
`either-record` = no contract, record both outcomes. Gold: chunk id only when
its text was located in `data/index.json` on 2026-10-14 (quoted fragment in
rationale); otherwise `unverified`. Role: `target` = future training target
(visible, teacher-passable, clean of the bench); `probe` = pure probe (no
contract, near-bench, or engine-domain — see §3).

| id | class | exact query string | expectation | candidate gold | rationale (role) |
| --- | --- | --- | --- | --- | --- |
| stmt-storage | statement | `storage is the cornerstone of the data engineering lifecycle` | answered+cited | ch06-001 | ch06-001 verified: "Storage is the cornerstone of the data engineering lifecycle (Figure 6-1)". First free assertion probe; **canonical double-verbs it** (§3). (target) |
| stmt-kafka | statement | `kafka is a message queue.` | answered+cited | ch03-086; ch05-022 | ch03-086 verified: "the emergence of Kafka as a highly scalable message queue"; ch05-022 verified: "…used interchangeably are message queue and streaming platform, but a subtle but essential difference exists between the two". Trailing period -> canonical passthrough (§3). (target) |
| short-tco | shorthand | `tco` | answered+cited | ch04-010 | ch04-010 verified: "Total cost of ownership (TCO) is the total estimated cost of an initiative…". Book's own acronym, never asked as the abbreviation; 0 hits in 1365 asked forms. (target) |
| short-cdc | shorthand | `cdc` | answered+cited | ch05-013 | ch05-013 verified: "Change data capture (CDC) is a method for extracting each change event…". Lowercase acronym form (the "auto"-family risk); trained only as "what is change data capture" / "explain change data capture". (target) |
| contr-watermark | contraction | `what's a watermark?` | answered+cited | ch08-039 | ch08-039 verified: "A watermark (Figure 8-8) is a threshold used by a window…". Highest-likelihood owner contraction; near-bench of "What is a watermark?" so it CANNOT enter training while the bench stays the exam — engine-side contraction fix candidate. (probe) |
| contr-kafka | contraction | `why's kafka so popular?` | answered+cited | ch03-086 | Same gold as stmt-kafka ("popularity … exploded with the emergence of Kafka"); contraction on a theme with no bench collision. 0 contraction forms measured anywhere. (target) |
| poss-watermark | possessive | `watermark's purpose` | answered+cited | ch08-039 | Task's example; ch08-039 defines what the watermark is for ("determine whether data in a window … is late"). 0 possessive forms measured anywhere. (target) |
| poss-mesh | possessive | `the data mesh's core idea` | answered+cited | ch03-099 | ch03-099 verified: "The data mesh attempts to invert the challenges of centralized data architecture…". Second possessive word shape (article+noun). (target) |
| punc-marks | punctuation | `watermark???` | answered+cited | ch08-039 | Doubled/tripled question marks, never probed; canonical passes "?" forms through unchanged (§3). Not near-bench (token overlap with "What is a watermark?" is just `watermark`). (target) |
| punc-dots | punctuation | `batch processing...` | answered+cited | ch02-019 | ch02-019 verified: "Batch processing remains an extremely popular way to ingest data…". Trailing ellipsis; canonical passthrough because the text ends with "." (§3). (target) |
| punc-comma | punctuation | `what is a watermark,` | answered+cited | ch08-039 | Trailing comma after a full question; canonical unchanged. Near-bench of "what is a watermark" -> probe only. (probe) |
| deg-space | degenerate | ` ` (single space) | either-record | — | Whitespace-only, no contract; R1 proposal (refuse pre-generation when no content word survives) is NOT shipped. Record refusal or exception shape; never train on it. (probe) |
| deg-symbols | degenerate | `???` | either-record | — | Symbols-only; canonical returns it unchanged (§3). Adjacent to the shipped "what is" degenerate behavior (answered from an arbitrary passage per engine-edges case c); no rule exists. (probe) |
| chap6 | chapter-level | `what is chapter 6 about?` | answered+cited | ch06-001 | First chapter-scoped ask anywhere (0 "chapter" forms in all measured files); ch06-001 is the chapter intro ("Chapter 6. Storage …"). No contract for chapter asks — record whatever comes back. (probe) |
| chap8 | chapter-level | `what does chapter 8 cover?` | answered+cited | ch08-001 | ch08-001 verified: "In this chapter, you'll learn how to make data useful." Second chapter number + different verb ("cover") to check routing generality. (probe) |
| mean-mesh | meaning-of | `meaning of data mesh` | answered+cited | ch03-099 | "meaning of" literally 0 hits in bench/train/x2d-forms; sweep has adjacent definition shapes only. Canonical prefixes to "What is meaning of data mesh?" (§3). (target) |
| mean-cdc | meaning-of | `change data capture means what` | answered+cited | ch05-013 | "X means what" subject-first shape (0 hits anywhere); canonical passthrough (contains "what"). Same gold as the trained "what is change data capture" card, new shape. (target) |
| fp-hdfs | false-premise | `why did HDFS shut down?` | either-record | ch06-062 (contradiction source) | HDFS is in-book (9 chunks); ch06-062 verified: "HDFS remains widely used in various applications and organizations." The shutdown event is not in the book — refusal is the faithful outcome, a cited contradiction is a recordable near-miss. (probe) |
| fp-lake | false-premise | `why did the data lake replace the data warehouse?` | either-record | unverified | Causal premise never asserted in the book (searched "replaced"/"versus" contexts; no lake-replaces-warehouse claim found — absence check only, no contradiction chunk verified). (probe) |
| cont-gptq | contamination-control | `What is GPTQ?` | exact refusal | — | Second-book topic; "gptq" 0 chunks in `data/index.json` (measured). Reverse direction of `probe-second-book` (which asked it against the quant book). (probe) |
| cont-turbo | contamination-control | `What is TurboQuant?` | exact refusal | — | "turboquant" 0 chunks in the FDE index (measured). (probe) |
| cont-ptq | contamination-control | `What is post-training quantization?` | exact refusal | — | "quantization" 0 chunks in the FDE index (measured), so the whole phrase is absent. (probe) |
| vs-lambda | vs-pair | `lambda vs kappa` | answered+cited | ch03-088 | Task-suggested pair; real sections: ch03-086/087 (Lambda), ch03-088 verified: "As a response to the shortcomings of Lambda architecture, Jay Kreps proposed an alternative called Kappa architecture". 0 hits for either word as a pair in 1365 asked forms. (target) |
| vs-eventual | vs-pair | `eventual vs strong consistency` | answered+cited | ch06-023 | ch06-023 verified heading "Eventual Versus Strong Consistency" (body: "A challenge with distributed systems…"). Dedicated section pair, never covered; x2c swaps don't include it. (target) |
| pol-watermark | polite-combo | `hey can you tell me what a watermark is?` | answered+cited | ch08-039 | Task's example; x2d trained `hey can you tell me about X` (about-tail) but never a wh-clause tail; bench/anchor content for watermark exists. Near bench greets -> probe only (and the hey→they repair applies). (probe) |
| pol-cdc | polite-combo | `could you explain change data capture?` | answered+cited | ch05-013 | Modal politeness ("could you") over a form trained bare ("explain change data capture"); new wrapper, trained content. Near-train, not near-bench. (probe) |
| typo-warehouse | typo | `warehosue` | answered+cited | ch03-071 | ch03-071 verified: "A data warehouse is a central data hub used for reporting and analysis." Transposition typo on a trained/bench topic; repair path is engine-side (x2d's "observabilty" precedent), never trained. (probe) |
| typo-serial | typo | `serializaton` | answered+cited | ch06-016 | ch06-016 verified: "Serialization is another raw storage ingredient and a critical element of database design." Second content-word typo on a non-watermark target (bench already owns "watermak"/"atermark"). (probe) |
| case-mesh | casing | `DATA MESH` | answered+cited | ch03-099 | All-caps topic casing; canonical -> "What is DATA MESH?" (§3). Case-mix swaps exist for PII/OLTP, none for topic caps. (target) |
| comp-cdc | compound | `what is change data capture and how is it used?` | answered+cited | ch05-013 | First two-part question anywhere; both halves answerable from ch05-013 ("CDC is frequently leveraged to replicate between databases in near real time or create an event stream…"). Near-train of "what is change data capture" (shape only). (target) |

## 3. Recommended probe shape

- **Type:** exploratory, 1 draw per item (single temperature-0 run; no rates,
  no pass/fail gate). This probe is NOT a gate and must not be cited as one.
  A single draw is enough to record behavior; items worth a rate get promoted
  later.
- **Seam:** answer mode via `answer.respond(index, item, model=…,
  generate_fn=…)` in-process, same as `probe-fragment-2026-10-14.py`; model
  `smallbook_x2d` (the current app default, `AGENTS.md` machine facts), passed
  explicitly rather than relying on the default. Do NOT call Ollama while
  authoring; the engineer runs it when the box is free.
- **Evidence:** `artifacts/evidence/probe-user-forms/probe-user-forms-2026-10-14.model-<model>.{json,log}`
  (as built; new family directory; dated names; one live twin per the artifacts policy).
  Record per item: `refused`, exactness vs `Not in this book.`, citations
  (ids + chapter), quote-verbatim where cheap, `Asked as:`/`Read as:` lines,
  seconds, and per-item exceptions (do not let `deg-space`/`deg-symbols` crash
  the run — wrap each item).
- **Roles:** the table above marks 15 items `target` (realistic owner input,
  in-book content, teacher-passable, bench-clean — these are visible by
  construction if a future build uses them) and 15 `probe` (no contract,
  near-bench, or engine-domain; e.g. `contr-watermark`/`punc-comma`/
  `pol-watermark` sit near bench strings and must NOT enter training while the
  bench stays the exam; typos stay engine-side per the P2-1 precedent).
- **Newness:** every string checked against the sealed 21 (no duplicates) and
  vs all 1365 asked forms; `cont-*` reuse second-book topic strings
  deliberately, as FDE-side refusal controls (task-sanctioned).
- **Do not** merge any item into the sealed suite; if this probe advances, its
  items and the sealed suite stay separate files.

### Canonical forms the engine will see (measured, local, no model)

Items whose asked form transforms before retrieval (import of `canonical.py`,
exact outputs):

| typed | asked (canonical) |
| --- | --- |
| `storage is the cornerstone of the data engineering lifecycle` | `What is storage is the cornerstone of the data engineering lifecycle?` (double-verb — statement gap) |
| `kafka is a message queue.` | unchanged (trailing period) |
| `tco` / `cdc` | `What is tco?` / `What is cdc?` |
| `watermark's purpose` | `What is watermark's purpose?` |
| `meaning of data mesh` | `What is meaning of data mesh?` |
| `lambda vs kappa` / `eventual vs strong consistency` | `What is lambda vs kappa?` / `What is eventual vs strong consistency?` |
| `DATA MESH` / `warehosue` / `serializaton` | `What is DATA MESH?` / `What is warehosue?` / `What is serializaton?` |
| `what's a watermark?`, `watermark???`, `batch processing...`, `what is a watermark,`, ` `, `???` | unchanged |

Scope: read-only; no engine file touched; no `artifacts/README.md` index row
added — this request froze the deliverable to one file.
