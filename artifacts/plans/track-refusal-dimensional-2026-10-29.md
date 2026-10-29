# Track: dimensional refusal suite + leak-free corpus — 2026-10-29 (rev 9)

Status: PROPOSED (not started). Owner review required before execution.
Evidence base: `artifacts/runs/fair-eval-2026-10-28-model-nekohon_q35_2b_x3_2e-split-dev.json` and `-split-locked.json`.
Rev 9 answers an eighth adversarial review. §9 lists all eight rounds and what changed.

**Reference convention:** `answer.py` has ~1000 uncommitted working-tree lines and its numbers moved twice during this review. Every `answer.py` reference below is by **symbol plus a grep**, not by line. Other files are cited by line because they are stable.

## 1. Verified facts this plan rests on

Each line was run against the tree on 2026-10-29.

- `_is_in_book("Lindy", ddia_index)` is `True`. `lindy` appears in **0** DDIA chunks; the only corpus word within edit distance 1 is **`linda`**, so the typo branch inside `_is_in_book` (grep `def _is_in_book`) rescues the term.
- The trap guard therefore never fires for the Lindy shape: `has_unmentioned_technical_anchor` (grep `def has_unmentioned_technical_anchor`) finds the capitalised token "in book" and returns `False`. Confirmed on the real DDIA index.
- `fair-dev-59` has **two** independent causes. The model answered (trace `calls[1].raw_refused: false`, preview `[Ch. 11] "The log of all changes, the changelog …"`), and `_half_covered` (grep `def _half_covered`) then replaced the body with the immutability quote plus the hardcoded gloss `The passages do not mention {missing_name}.`, with `refused=False`. A direct call reproduces the final string and shows a refused body is rewritten, not preserved.
- `_half_covered` leaving `refused=False` records **no transform** (`outcome.transforms: []` for `fair-dev-59`), so the trace credits the model with text the engine wrote.
- `_half_covered` is intentional and test-locked: `tests/test_half_covered.py:1-5` — "A comparison the model refused still answers the covered side … refuse neither." This plan does not change its behaviour.
- `fair-locked-59` is model-side only: its recorded answer carries no "The passages do not mention" gloss, so no rewrite is evidenced there.
- `fair-dev-30` is guard-refused (`trace.query.guard_blocked: "unmentioned_technical_anchor"`) because `S=1/16` starts uppercase and enters the proper-noun branch. The question is answerable: `chapter-2-006` holds 1.5 / 24 / `0001 1000`.
- `fair-dev-34` is **not** a clean trap. `data/index.quantization.json` `chapter-7-044` states the scaling identity (Equations 7.3/7.4, "where s is a per-channel scale vector"), `chapter-7-046` explains α balancing, and `chapter-7-047` (Listing 7.10) contains `scales = act_norm.pow(alpha)` and `W_scaled = W_group * scales`. Only the phrase "salient weight protection ratio" is absent. The fair set's own audit (`tests/test_fair_set.py:333-345`) checks phrase absence only, which cannot separate a missing phrase from a supplied answer.
- `fair-locked-55` is a near miss on a different quantity: the book gives 7 ms clock uncertainty; the question asks for antenna drift bounds. Keep, subject to the audit in §4.4.
- The peek ledger has **5** locked entries, **1** on 2026-10-28 (`locked_passed 41 / 60`, `git_head 07e5c5ae`).
- `ai-engineering` is a product book (`data/books.json`, 1030 chunks, `book_id` `ai-engineering`) and is missing from `INDEX_PATHS` in `fair-eval.py:51-55`, `trace_inspect.py:32-36` and `tests/test_fair_set.py:33-37`. A fourth map exists in `artifacts/probes/tech-stack-bakeoff-2026-10-27.py`; it is out of scope and is not touched.

## 2. Measured baseline

| Metric | dev | locked |
|---|---|---|
| Items / passed | 60 / 37 (61.67%) | 60 / 41 (68.33%) |
| Answer items | 18 / 39 (46.15%) | — |
| Refusal items | 19 / 21 (90.48%) | 19 / 21 |
| Defense source | 9 anchor + 2 person + 8 model | — |
| `trap_false_answer` | `fair-dev-34`, `fair-dev-59` | `fair-locked-55`, `fair-locked-59` |
| `guard_false_refusal` | `fair-dev-30` | — |
| `missing_key_fact` / `wrong_citation` / `retrieval_miss` | 15 / 3 / 2 | — |
| Recall@1 / @5 | 20/39 / 37/39 | — |

Gate values for the current model, quoted from the current-state block in `AGENTS.md` (sealed / hard-mt / hard bench / adrian from the 2026-10-25 entry; battery 10/10 both modes from the 2026-10-24 round-2 entry): sealed **27/30**, hard-mt **12/12**, hard bench **59/60**, adrian **32/35**, battery 10/10. Re-measure before quoting them in a report.

Work order follows the numbers: generation 46.2%, refusal 90.5%. Harness, then engine, then suite, then data.

## 3. Root-cause split

| Failure | Cause | Lever |
|---|---|---|
| `fair-dev-59` | typo repair rescues an absent proper noun; `_half_covered` also rewrites the body | engine guard |
| `fair-locked-59` | same guard hole, model answered | engine guard |
| `fair-dev-30` | formula token read as a proper noun | engine guard |
| `fair-dev-34` | label is a phrase-absence artefact; the book supplies the transformation | **dataset re-audit first** |
| `fair-locked-55` | book gives an adjacent quantity | data, after audit |

Two of the four trap failures are guard holes (`fair-dev-59`, `fair-locked-59`); one is a dataset label artefact (`fair-dev-34`); one is a real near-miss on a neighbouring quantity (`fair-locked-55`). Training is the last lever, not the first.

## 4. Work items

Order matters: 4.3 (harness) → equivalence proof → 4.1 (guard) → five gates → 4.2 → 4.4 → 4.5 → 4.6.

### 4.1 Engine — `has_unmentioned_technical_anchor`

Four edits across two functions (`_is_in_book`, `has_unmentioned_technical_anchor`) and two regex checks:

1. `_is_in_book(term, corpus, allow_typo=True)`. Default keeps every current caller identical, including acronym/CamelCase typo repair.
2. Phrase-anchor branch: `allow_typo=False`.
3. Proper-noun branch: skip tokens containing `[a-z][A-Z]` (mixed case belongs to the CamelCase branch), admit only tokens matching `^[A-Z][A-Za-z0-9'’.-]*$`, then call `_is_in_book` on the term and on each part with `allow_typo=False`.
4. `COMPARE_RE` branch: `allow_typo=False` on both sides. Its one-side-present early return stays, and the docstring says why: that case is the locked half-answer design.

Why the mixed-case skip is required: without it `DeadCodeEliminaton` falls through to the proper-noun branch and is refused, breaking `tests/test_technical_anchor_refusal.py:122-129`. With it, the CamelCase branch handles and typo-repairs the token as today.

Acceptance, all measured:
- `has_unmentioned_technical_anchor(ddia_index, dev-59 question)` is `True`.
- `has_unmentioned_technical_anchor(quantization_index, dev-30 question)` is `False`.
- `python -m unittest tests.test_technical_anchor_refusal tests.test_half_covered` green; three new cases (Lindy/`linda`, `S=1/16`, `DeadCodeEliminaton`).
- Dev re-run recorded item by item. Expected to change: `fair-dev-59` and `fair-dev-30`; other verdict shifts are possible and each is listed with its item id in the report rather than asserted in advance.
- `guard_false_refusal` count on dev does not rise above the pre-change count.
- **Landing is conditional on the five gates** (§5). Any regression on sealed, hard-mt, hard bench, adrian, or the battery reverts the guard change. The guard is engine code, and the constitution asks the gates, not the plan, for permission.

Revert: two functions (`_is_in_book`, `has_unmentioned_technical_anchor`) and the new tests.

### 4.2 Observability — make `_half_covered` rewrites visible

Record the rewrite **inside `_half_covered`**, not at its three call sites: compare the input `body["answer"]` with the returned body and call `observe.record_transform("half_covered_rewrote")` when the text differs. One edit covers every caller.

Acceptance: the dev re-run shows the transform on `fair-dev-59`; `tests/test_observability.py` gains a case.

### 4.3 Harness — dataset argument

Lands before §4.1 so its equivalence proof is not confounded.

- `fair-eval.py`: `--dataset PATH` (default: the frozen fair file). `DATASET_SHA256` map for `fair-2026-10-27.jsonl` (`6255b361…`) and the new suite; unknown path fails closed unless `--sha256` is given. `INDEX_PATHS` (`:51-55`) gains `ai-engineering`. Ledger target becomes `<dataset-stem>.peek-ledger.jsonl` when the dataset is not the default. The run payload records the **actual** dataset name and sha256, not `DATASET.name` (`:564-570`).
- `trace_inspect.py:32-36` and `tests/test_fair_set.py:33-37`: same `INDEX_PATHS` addition.
- No new `--split` value. `load_items` filters on `item["split"]` (`:66-76`), so the new suite uses real `dev` and `locked` splits and the harness is driven with `--split dev` (tuning) and `--split all` (verdict).
- Ledger hardening, in `fair-eval.py` (`:543-558`), because the plan's "two looks" rule must fail closed rather than be audited after the fact:
  - **Pre-check before the run.** For `--split all`/`locked`, validate the dataset sha first, then read the dataset's ledger and refuse to start (exit 3, no model call) when it already holds 2 distinct `run_id`s. The refusal is a detection point, not a mutex: this plan assumes one operator and no concurrent eval processes, and a concurrent second run is caught by the `run_id` count afterwards rather than blocked. `--dummy-baselines` is exempt because it returns before the ledger block and makes no model call.
  - **Write before the work, then mark complete.** Append one line with `run_id` (uuid4), `status: "started"`, `model`, `timestamp`, `run_path`; after the evidence file is written, append a second line with the same `run_id` and `status: "complete"`. A crash leaves a `started` line with no `complete` partner, which still counts as a look.
  - Today the entry is written after results and carries neither field, so a crashed run is indistinguishable from a finished one.
- `--dummy-baselines` divides by `ans_tot` (`:517`); with twins present that denominator exists. State it in the docstring instead of patching the division.
- Equivalence proof for the default path: run `--split dev` before and after the harness change on unchanged engine code; require identical per-item verdicts and identical aggregates. Latency and timestamps differ and are excluded.

### 4.4 Suite — `artifacts/datasets/refusal-dimensional-2026-10-29.jsonl`

96 items, 4 books (`fde`, `quantization`, `ddia`, `ai-engineering`), 24 per book:

| Per book | dev | locked | total |
|---|---|---|---|
| traps | 8 | 4 | 12 |
| twins | 8 | 4 | 12 |

Suite totals: 64 dev (32 traps + 32 twins), 32 locked (16 traps + 16 twins) = 48 traps, 48 twins.

Per book, the 12 traps are balanced across all three dimensions: semantic proximity S ∈ {in-chapter near-miss, cross-book bleed, out-of-domain} 4/4/4; trap structure T ∈ {fabricated attribution, fabricated technology/flag, false premise, temporal anachronism} 3/3/3/3; register R ∈ {fact, procedural, comparative, conversational} 3/3/3/3. The 4 locked traps per book are one per T class, so dev keeps 2 per T class (dev S 2/3/3, dev R 2/2/2/2 per book). Those dev splits live in the sidecar `refusal-dimensional-2026-10-29.meta.json`, not in the JSONL: `fair-eval.load_items` parses every non-empty line as an item (`:66-76`), so a header line would become a 97th item.

Twins: same book, 12 per book (8 dev + 4 locked), gold chunks verified by term presence (the `fair_cite` rule). Register split per book: 4 fact, 4 procedural, 4 conversational (dev 3/3/2, locked 1/1/2). **No comparative twins.** A comparative answer item is unreliable under the locked half-answer design: `_side_covered` reads the *shown passages* (`answer.py`, `grep def _side_covered`), not the book, so a distractor carrying one side can still trigger `_half_covered` and rewrite the answer, while `fair_cite.judge_citation` (`fair_cite.py:50-68`) demands the question's terms in one cited chunk. Both a full answer and a half-answer would grade unpredictably. The comparative register lives only on the trap side, where both sides are absent by rule and the expected behaviour is refusal.

Pairing is **optional metadata**, not a contract: `pair_id` may name any trap in the same book, several twins may share one trap, and nothing is asserted about register or topic pairing. No part of this plan depends on which traps are paired.

Comparative-register traps are valid only when **both** sides are absent from the target book. A comparative item with one side present is neither a trap nor a twin under this plan.

Trap audit, in two layers:

1. **Mechanical** (tested): each trap carries `probes: [{"term": "...", "expect": 0}]`. Every probe must match 0 chunks in the target book across `heading + text + figure caption`, case-insensitive whole word. The probe list must name the requested quantity as the question writes it, plus one **candidate** second handle that must also turn out to be absent (never an in-book synonym: a synonym that hits means the book supplies the quantity and the trap is invalid).
2. **Human, recorded** (not claimed mechanical, but its record is checked): each trap carries `audit: {"by", "date", "adjacent_chunk", "adjacent_line", "why_not_answer", "synonym_of", "quantity_term", "probe_hits"}`, where `probe_hits` is a list of integers aligned index-for-index with `probes` (one count per probe, never a scalar). Tests assert `adjacent_chunk` exists in the target index, `adjacent_line` is a whitespace-normalised substring of that chunk's `heading + text`, and `by`, `date`, `why_not_answer`, `synonym_of` are non-empty. This is the check that catches `fair-dev-34`: `chapter-7-047`, `scales = act_norm.pow(alpha)`.

Probe composition rule, so a trap cannot pass its own mechanical layer by probing only the one phrase the book lacks:

- At least two probes are required, and `probes[0]` is always the quantity **as the question writes it**, named in `audit.quantity_term`. The test proves both halves: `audit.quantity_term` must equal `probes[0].term` after casefold, and that term's token list must be non-empty and appear unbroken in the question's. Tokenise with `re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)`. This keeps separators where they matter — `S=1/16` and `S = 1/16` are both `["s","1","16"]` and match, while `S=11/6` is `["s","11","6"]` and does not, and `Kafka 5.0` is `["kafka","5","0"]` against `Kafka 50` `["kafka","50"]`. Unicode tokens are kept, so `α` is a real token; an empty token list is a failure, never a vacuous pass. Because the tokeniser cannot separate symbol-bearing terms (`C#` and `C++` both become `["c"]`), a probe containing any character outside `[\w\s]` must **also** appear verbatim in the question after casefold and whitespace collapse.
- Every probe must hit 0 chunks in the target book. The second probe is therefore always an **absent** second handle on the quantity, never an in-book synonym — a synonym that is present means the book supplies the quantity and the trap is invalid. What that second handle is depends on the trap structure:

| Trap structure | Second probe |
|---|---|
| in-chapter near-miss | nearest absent synonym for the quantity (`protection ratio` → `shrink factor`) |
| cross-book bleed | the same term spelled as it appears in the other book, plus the absent side's name |
| out-of-domain | the domain's own term for the quantity |
| fabricated technology/flag | the flag/library name and its stem (`--enable-quantum-stream`, `quantum_stream`) |
| false premise | the premise's noun phrase and its synonym |
| fabricated attribution | a name part (surname alone, then the quoted full name) — names have no synonyms |
| temporal anachronism | a date variant (year alone, then `version N.M`) — dates have no synonyms |

The examples in that table are illustrative, not a guarantee for every book: the author picks the target book so each item's probes are 0-hit, and `audit.probe_hits` records one count per probe in that book, as a list aligned with `probes` — the test recomputes those counts index-for-index and fails on any mismatch or length mismatch. `Voss` exists in DDIA, `2026` in FDE and quantization, `version 5.0` in quantization, `transitory technologies` in FDE — those pairs belong to the other books, which is exactly what a cross-book-bleed trap tests.

`audit.synonym_of` records which question term the second probe is derived from, using the word "variant" rather than "synonym" for the name and date classes. The auditor may not invent a probe the question never asks about, and may not delete a probe that does hit — a hit invalidates the trap.

Schema: fair-set fields `id, split, category, book_id, question, expect, gold_chunks, key_facts, history, notes`, plus `dims: {semantic, trap, register}`, optional `pair_id` (twin → trap, many-to-one), `probes`, `audit`. Twins use `dims.trap: null` and empty `probes`.

Re-audit before authoring: `fair-dev-34`, `fair-locked-55`, `fair-locked-59`. Outcomes recorded in the items' `notes`; if anything is reclassified the fair-set sha256 is updated in `tests/test_fair_set.py:29` and `fair-eval.py:47` (not in `test_eval_leakage.py`), and both the old and new dev baselines are reported. If `fair-dev-34` becomes an answer item it needs `key_facts` and `gold_chunks` or `tests/test_fair_set.py:266-313` fails, and the dev refusal baseline becomes **19/20**.

Statistics, fixed before the run (ceiling stated, because it decides whether the verdict is reachable):

- Tuning signal: 32 dev traps, 1 item = 3.13 points.
- Verdict: all 48 traps once, 1 item = 2.08 points. Wilson 95% at 44/48 is [80.45%, 96.71%], ±8.1 points.
- If the post-guard baseline lands at **≥43/48** (5 or fewer failures), the ≥6-discordant bar is arithmetically unreachable: a 5-0 result is p = 0.0625. The report then states "ceiling reached" and makes no adoption and no success claim; that is a finding about the suite, not a failure of the corpus.

Generator: `artifacts/probes/probe-refusal-matrix-2026-10-29.py`, seed in the docstring. `build-*` is also precedented in that zone; `probe-*` is chosen because this is a dated one-off.

### 4.5 Tests

- `tests/test_eval_leakage.py`: add the suite to `eval_sets` (`:436-443`); add the new corpus to `TRAINING_CORPORA_FILENAMES` (`:59-70`); parameterise the passage-overlap ratchet (`:487-545`), which today loads only `TRAIN` (`:492`), so it can take r6.
- `tests/test_refusal_dimensional.py` (new, thin): `sys.path.insert(0, str(Path(__file__).resolve().parent))` then `import test_eval_leakage as L`. A package-relative import breaks under `discover -s tests`; a bare `tests.` import breaks under `-m unittest tests.…`. This form works under both. No matcher is re-implemented.
- `tests/test_fair_set.py`: skip `*.meta.json` in the dataset glob at `:169-171`, which today reads every `.json` except the fair file. Without that line the sidecar's `twin` list would be parsed as eval items and its `gold_chunks` would contaminate `eval_gold_chunks` (`:179-188`).
- Assertions: frozen sha256 of the suite; 96 unique ids; 48/48 expect split; 64 dev / 32 locked; per-book 12/12 and 8+4 split; dimension balance per book (S 4/4/4, T 3/3/3/3, R 3/3/3/3) **and** the splits recorded in the sidecar (traps dev S 2/3/3, R 2/2/2/2; twins dev 3 fact / 3 procedural / 2 conversational, locked 1/1/2, total 4/4/4); every trap has ≥2 `probes`, `probes[0]` contained in its own question as a contiguous non-empty token subsequence under `re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)`, and every probe matches 0 chunks in its book; `audit.adjacent_chunk` exists, `audit.adjacent_line` is a normalised substring of that chunk, `by`/`date`/`why_not_answer`/`synonym_of`/`quantity_term` are non-empty, `quantity_term` equals `probes[0].term` after casefold, and `probe_hits` is a list aligned with `probes`, matching the recomputed counts (all 0); every twin's `key_facts` satisfy the three-part rule at `tests/test_fair_set.py:266-313` (so a key fact may not repeat the question's own terms); twin `gold_chunks` exist in the target index; no twin is comparison-shaped; every `pair_id`, when present, names an existing trap in the same book (metadata only); `L.leaks()` returns empty against `fair-2026-10-27.jsonl` questions (near-duplicate matcher, not exact equality); `L.leaks()` empty against every corpus in `TRAINING_CORPORA_FILENAMES`; twin gold-chunk passage overlap against r6 within the measured baseline; the dataset's peek ledger satisfies all of: every line parses as JSON (a partial line is a hard failure naming the crash, not a silent skip), every `complete` line has `status: "complete"` and a `run_path` that exists on disk; at most 2 distinct `run_id`s exist; every `run_id` has exactly one `started` line and at most one `complete` line; a `started` line with no `complete` partner counts as a spent look with no `run_path` requirement. That last assertion is how §4.7's "no third look" is enforced, and it depends on the ledger hardening in §4.3.
- r6 assertions skip with a message when the file is absent (`data/` is gitignored), so 4.6 can be deferred without breaking the suite.

### 4.6 Corpus — candidate, not adopted

Base: `quote-refuse-2026-10-27.train-x3-clean.jsonl` — the decontaminated derivative of the adopted x3 corpus (844 → 777 kept, 67 stripped; `artifacts/README.md` row for `probes/decontaminate-train-2026-10-27.py`). 777 rows, 137 refusals, 17.63%. Not r5: that is a rejected candidate.

Exact counts, chosen so the arithmetic is not at a boundary by accident:

- `N_ref = 30`, `N_ans = 72` → 167/879 = **18.99%**. The 15–20% band is a constraint this plan adopts as its own ceiling for over-refusal safety; it is not a constant read from the repo. 18.99% sits on the 19% line on purpose and is inside the band; one dropped answer row moves it to 19.02%, still inside. For a ≤20% target the floor would be 28 answer rows; 72 is chosen for auditing margin, not as a tuned number. The report states the final counts, not the target.
- `N_ref` category label: `near_miss_quantity`. Mechanical boundary against the fair set's `near_miss_refusal`: a `near_miss_quantity` row must carry ≥2 probes, one of them a quantity or symbol token taken from the question, and an `audit.adjacent_line` naming the neighbouring fact in the book. A `near_miss_refusal` row carries neither. The report shows three rows from each side with their probes side by side.
- Authoring rule: the seed rows (training) and the suite's traps are question-disjoint by construction — different entities, different wording — and `tests/test_refusal_dimensional.py` proves it through `L.leaks()` rather than trusting the author.
- No new `premise_trap` rows: 12 exist (`trap-crossbook-seeds-2026-10-24.jsonl`) and were trained in r5.
- `N_ans` source: audited rows from the round-3 pool (`artifacts/probes/build-round3-rows-2026-10-24.py`, 277 rows), each re-checked for duplicate question, gold chunk carrying the question's terms (`fair_cite.py`), and leakage.
- Filename `quote-refuse-2026-10-29.train-r6.jsonl` (`r5` is the latest r-series). Freeze with sha256 the way r5 was (`584b49e1…`).
- Seeds: `data/finetune/refusal-dim-seeds-2026-10-29.jsonl`.

### 4.7 Adoption rule (pre-registered)

Baseline: on the **post-§4.1, pre-corpus** model and engine, one `--split dev` run (tuning signal) and **one `--split all` run** (the paired baseline for all 48 traps). No pre-guard baseline is used — it would mix engine and corpus effects.

The reserve is spent **twice**, and the plan says so: once by the baseline `--split all`, once by the candidate verdict. `fair-eval.py:543-558` appends a ledger entry on every `all`/`locked` run, so both appear in `refusal-dimensional-2026-10-29.peek-ledger.jsonl`. A third `--split all` is not permitted by this plan: a second candidate is a new decision record, not a silent re-look.

Adopt only if all four hold:

1. **Traps, total:** net ≥6 discordant traps in the improving direction **and** exact McNemar p < 0.05 across all 48. A net of 4 gives p = 0.125 and cannot qualify; 6-0 gives p = 0.031. If the post-guard baseline is ≥43/48, the verdict is "ceiling reached": no adoption, no success claim.
2. **Twins:** pass count ≥ baseline. One more twin refused is a regression; twins are the control.
3. **Gates:** sealed ≥27/30, hard-mt =12/12, hard bench ≥59/60, adrian ≥32/35, battery 10/10 in both modes, pins green.
4. **Locked net ≥ +1 (a gate, not a report line):** the candidate must pass strictly more of the 16 locked traps than the baseline. Equal locked scores are not enough: with the total-48 McNemar, a 6-0 gain on dev alone would otherwise be adopted as if it generalized. If the baseline locked score is already 16/16, this gate cannot be met, which makes the verdict "ceiling reached on the held-out traps — not adopted"; that is stated in the report, not papered over.

Tuning uses `--split dev` only, as many times as the candidate needs. The `--split all` look happens twice in total (baseline, verdict) and both append to `refusal-dimensional-2026-10-29.peek-ledger.jsonl`. Five fair-set locked runs are already ledgered, so no fair locked run is spent on this work.

If the rule fails: keep the guard fixes, keep the candidate on disk, write the negative result. Round 3 (277 teacher rows) and round 5 (12 traps) both moved failures instead of removing them; the point of this rule is that a corpus which fails it gets recorded, not merged.

## 5. Verification commands

Valid today:

```
python -c "import json,answer as A; idx=json.load(open('data/index.ddia.json',encoding='utf-8')); print(A.has_unmentioned_technical_anchor(idx,'How does the Lindy effect help data engineers distinguish immutable from transitory technologies?'))"
python -c "import json,answer as A; idx=json.load(open('data/index.quantization.json',encoding='utf-8')); print(A.has_unmentioned_technical_anchor(idx,'What integer value and binary pattern represent 1.5 when quantized with scale S=1/16?'))"
python -m unittest tests.test_technical_anchor_refusal tests.test_half_covered
python -m unittest discover -s tests
python artifacts/harnesses/fair-eval.py --split dev
python artifacts/harnesses/sealed-eval.py <model>
python artifacts/harnesses/hard-mt-eval.py <model>
python artifacts/harnesses/hard-bench.py --model <model>
python artifacts/harnesses/adrian-eval.py --direct
BATTERY_MODE=ask python artifacts/harnesses/step2-battery.py
BATTERY_MODE=answer python artifacts/harnesses/step2-battery.py
python -m unittest tests.test_harness_fairness
```

`step2-battery.py` defaults to `BATTERY_MODE=ask` (`:28`) and talks to the server on :8000, so both modes and a single running listener are preconditions for the battery gate. `tests/test_harness_fairness.py` is the pins check.

`run-gate.py` runs only `fragment, battery, refuse, trial, sweep` (`run-gate.py:60`); it is not the five-gate command and is not used for the adoption verdict.

Valid only after §4.3 (`--dataset` does not exist today):

```
python artifacts/harnesses/fair-eval.py --dataset artifacts/datasets/refusal-dimensional-2026-10-29.jsonl --split all --dummy-baselines
python artifacts/harnesses/fair-eval.py --dataset artifacts/datasets/refusal-dimensional-2026-10-29.jsonl --split dev
python artifacts/harnesses/fair-eval.py --dataset artifacts/datasets/refusal-dimensional-2026-10-29.jsonl --split all
```

Expected, written before the run: on `--split all`, `always_refuse` scores 48/48 traps and 0/48 twins; `question_echo` and the two echo baselines score 0/48 on traps and stay under the 15% answer ceiling. The model's trap score is not predicted here; it is the first measurement of a new set.

## 6. Files this track creates (index rows required)

| Path | Zone |
|---|---|
| `artifacts/plans/track-refusal-dimensional-2026-10-29.md` | plan (dated, stable-named precedent: `reranking-odp-2026-10-23.md`) |
| `artifacts/datasets/refusal-dimensional-2026-10-29.jsonl` | dataset |
| `artifacts/datasets/refusal-dimensional-2026-10-29.meta.json` | suite sidecar: dev/locked dimension counts, twin swaps |
| `artifacts/datasets/refusal-dimensional-2026-10-29.peek-ledger.jsonl` | run output named by §4.3 |
| `artifacts/probes/probe-refusal-matrix-2026-10-29.py` | one-off probe |
| `artifacts/probes/probe-refusal-corpus-2026-10-29.py` | one-off probe |
| `artifacts/reports/refusal-dimensional-2026-10-29.md` | dated report, after the run |

One index row per file in `artifacts/README.md`, same commit; rule 4 makes unindexed files prunable. The existing `plans/refusal-surface.md` and `plans/refusal-ux.md` cover how `Not in this book.` reaches the screen; this track is model and data only and does not supersede them.

## 7. Definition of done

- Harness change landed with an equivalence proof against the 2026-10-28 dev run.
- Guard change landed only if the five gates hold; three new anchor tests; dev re-run cited item by item with `guard_false_refusal` before/after.
- `_half_covered` rewrites visible in the trace for `fair-dev-59`.
- Suite frozen, leakage-registered, probes mechanical, audits recorded; dummy baselines fail their half (always_refuse on twins, echoes on traps).
- `fair-dev-34` / `fair-locked-55` / `fair-locked-59` re-audit verdicts recorded; fair-set sha updated in the two places that hold it if anything changed.
- Corpus candidate at 167/879 and frozen, or the reason it was not built recorded.
- One report: dev, the new suite (dev and all), the five gates, the re-audit, the McNemar result, the ceiling statement, and the verdict.
- If adopted: revert tag documented (`ANSWER_MODEL=nekohon_q35_2b_x3_2e`).

## 8. Explicit non-goals

- No refusal-only benchmark (an always-refuse model would score 100% on traps).
- No second leak matcher, no second copy of 0.85 / 0.70.
- No change to `_half_covered`'s half-answer design.
- No claim of improvement from a 1–3 item move on 48 traps, and no success claim when the baseline leaves no headroom.
- No training on a trap that has not passed both audit layers.

## 9. Review history

Rev 8 → rev 9 (eighth adversarial review, score 6/10). Fixed:

- The ledger assertion contradicted itself on a killed run: `complete` lines now need `status` and an existing `run_path`, while `started`-only lines count as spent looks with no `run_path` requirement.
- "Third look impossible" was not true of a non-atomic pre-check; the claim is now "refused at start under a single-operator assumption, detected afterwards otherwise", the sha is validated before any `started` line, and `--dummy-baselines` is explicitly exempt.
- `probes[0]` being "the quantity" was prose only; `audit.quantity_term` is now a field and the test asserts it equals `probes[0].term` and that the term is contained in the question.
- Symbol-bearing probes (`C#` / `C++`, which share the token `c`) now also require a verbatim match against the question.
- `audit.probe_hits` is a field, and the test recomputes every count instead of trusting the audit narrative.
- A duplicated "at least two probes" sentence was removed.

Rev 7 → rev 8 (seventh adversarial review, score 6/10). Fixed:

- §4.5 still carried the old character-stripping regex while §4.4 had moved to token containment; both now use the same Unicode token list, and `probes[0]` is asserted to be the quantity the question asks.
- The ledger could still miss a look that wrote evidence and crashed before appending. The harness now refuses to start a third look *before* any model call (fail closed), writes a `started` line with a `run_id` before the work and a `complete` line after, and the test counts distinct `run_id`s — so a crash is a spent look, not an invisible one.
- The tokenizer was ASCII-only, so `α` produced an empty list that is trivially a subsequence of anything; it is now `re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)` with an explicit non-empty requirement.
- The probe table is now labelled illustrative rather than per-book; the author chooses the target book and records the counts.
- The unenforced "comparative traps are unpaired" sentence is gone; `pair_id` is metadata only.

Rev 6 → rev 7 (sixth adversarial review, score 6/10). Fixed:

- The last "in-book synonym" sentence survived in the mechanical layer and contradicted the absent-probe rule; it now reads "candidate second handle, which must turn out to be absent".
- The ledger cap could still be gamed: the harness now writes evidence first and appends a line with `status` and `run_path`, and the test parses every line (a partial line fails loudly) and checks each `run_path` exists. "No third look" is now auditable rather than aspirational, and the change is a listed §4.3 work item.
- The probe-in-question check moves from character stripping to contiguous **token subsequence**, so `S=1/16` matches `S = 1/16` but not `S=11/6`, and `Kafka 5.0` does not match `Kafka 50`.
- `pair_id` is now stated as optional metadata; the unenforced "same topic family" and "comparative traps are unpaired by construction" claims are gone, and the test asserts existence and book only.

Rev 5 → rev 6 (fifth adversarial review, score 7/10). Fixed:

- The second probe was specified as a "synonym", which fabricated attribution and temporal anachronism cannot supply. The rule now gives a per-structure table: name parts for attribution, date and version variants for anachronism, absent synonyms for the quantity classes.
- `pair_id` implied one-to-one pairing while 3 comparative traps have no twin; it is now optional and many-to-one, and the test checks only that a present id names an existing trap in the same book.
- The ledger cap was not crash-safe: it now counts **parseable** entries only, ignores a trailing partial line, and requires a crashed run's entry to be reported rather than dropped. (The partial-line rule was superseded in rev 7, where a partial line became a hard failure and `started`/`complete` lines replaced entry counting.)
- The probe-in-question check moved to an explicit regex (`re.sub(r"[^0-9a-z]+", "", text.lower())`); superseded in rev 8 by token containment, because character stripping collapsed `S=1/16` with `S=11/6` and `Kafka 5.0` with `Kafka 50`.
- Twinned registers were asserted for dev only; dev 3/3/2, locked 1/1/2 and total 4/4/4 are now all asserted.
- The 15–20% band is now labelled as this plan's own constraint, not a repo constant.

Rev 4 → rev 5 (fourth adversarial review, score 6/10). Fixed:

- Gate 4 allowed equal locked scores, so a dev-only gain could still be adopted. It now requires locked **+1**, and says what happens when the locked baseline is already perfect.
- Comparative twins are removed rather than patched: `_side_covered` reads shown passages, so no gold-chunk rule can stop a distractor from triggering the locked half-answer path. The comparative register now exists only on the trap side. Twin registers are stated per split (4/4/4 per book, dev 3/3/2, locked 1/1/2) and asserted.
- "Nearest in-book synonym" contradicted "every probe matches 0 chunks". The second probe must now be a synonym that is **absent**; a present synonym invalidates the trap.
- The sidecar `.meta.json` would have been swallowed by `tests/test_fair_set.py:169-171` as eval items; excluding `*.meta.json` is now a listed test edit.
- The probe-in-question check is punctuation-normalised, so `S = 1/16` matches the probe `S=1/16`.
- "No third look" is now mechanically enforced: the dataset's peek ledger is asserted to hold at most 2 entries.
- The `artifacts/README.md` row said rev 2 and mixed item and trap counts; it now states rev 5, 64 dev / 32 locked items, and the 32/16 trap split.

Rev 3 → rev 4 (third adversarial review, score 6/10). Fixed:

- The baseline and the verdict each need one `--split all` observation, so the locked reserve is spent twice; the plan now says two, not "one", and forbids a third.
- The ceiling threshold was off by one: at 43/48 a 5-0 result is p = 0.0625, so "unreachable" starts at 43, not 44.
- Locked generalization was a report line while "all four hold" implied a gate; it is now gate 4, a non-inferiority check on the 16 locked traps.
- `audit.adjacent_line` was unverified: it is now asserted as a normalised substring of the named chunk, with `by`/`date`/`why_not_answer`/`synonym_of` non-empty, and probes must include a term the question itself contains so a trap cannot be self-certified by probing a phrase nobody asked for.
- A JSONL "header" would have been parsed as a 97th item; the dev splits moved to the sidecar `.meta.json`, which is now a listed artifact.
- Comparative twins could still hit `_half_covered`, which reads shown passages, and failed `fair_cite` on two-chunk comparisons; both sides must now live in the same gold chunk.
- The battery gate only ran ask mode and needs the server; both modes and the pins test are now listed with their preconditions.
- §3's "three of four" count was off by one; the corpus boundary wording was misleading; `near_miss_quantity` now has a mechanical boundary; seeds are question-disjoint by rule and checked by `leaks()`.

Rev 2 → rev 3 (second adversarial review, score 4/10). Fixed:

- Locked reserve was 24 **items**, not 24 traps; split is now per-book 8 dev + 4 locked traps and 8 + 4 twins, so the suite has 32 dev traps, 16 locked traps, 48 total.
- Statistics now separate the tuning signal (32 traps, 3.13 points) from the verdict (48 traps, 2.08 points), with the ceiling problem stated.
- The ≥4-item adoption floor was unsatisfiable alongside McNemar p<0.05 (4-0 is p=0.125). Now ≥6 net discordant.
- `--split test` would have selected 0 items because every item carries `dev`/`locked` and `load_items` filters on that field; the flag is dropped and the verdict uses `--split all`.
- `_half_covered` call sites are three, not two, and their line numbers drift; the transform is now recorded inside the function.
- The trap audit rule is split into a mechanically tested `probes` layer and a human `audit` layer that names the adjacent chunk and line — and is no longer called mechanical.
- The fair-set sha256 lives in `tests/test_fair_set.py:29` and `fair-eval.py:47`, not `test_eval_leakage.py`.
- `fair-dev-34` reclassification moves the dev refusal baseline to 19/20, not 18/20.
- The corpus clause no longer both requires near-miss rows and forbids near-miss categories; the rows are `near_miss_quantity`.
- Adoption baseline is now post-guard, pre-corpus; the harness equivalence proof runs before the guard change.
- Gate verification lists the five harnesses instead of `run-gate.py`, which only runs fragment/battery/refuse/trial/sweep.
- Guard landing is conditional on the five gates; revert scope corrected to two functions.
- Corpus base moved from the rejected r5 to `x3-clean`; counts are exact (30 + 72 = 167/879).
- r6 assertions skip when `data/` is absent; `--dummy-baselines` wording corrected per half; `leaks()` used instead of exact-equality overlap; balance counts asserted; run payload records the real dataset name.

Rev 1 → rev 2 (first adversarial review, score 4/10): proper-noun branch would have broken `DeadCodeEliminaton`; gate baselines were three models' numbers; `--split` was at 495 with default `dev`; ledger had 5 entries, 1 yesterday; dev-59 has both causes; `fair-dev-34` was labelled a clean trap; "commands checked to parse" was false for the post-change commands; dummy-baseline and adoption-threshold claims were one-sided or inside the noise band; the new test's import failed under `-m unittest`; the passage-overlap ratchet only read `x3`; missing `ai-engineering` maps, r6 freeze, ledger index row, `dims.trap`, key-fact rule, and rewrite visibility.
