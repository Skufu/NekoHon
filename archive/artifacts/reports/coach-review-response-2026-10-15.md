# Response to the external review — teacher capture (2026-10-15)

The review below is answered point by point. Everything marked *measured* has
an evidence file in this repo; everything else is marked as plan or estimate.
The review body itself was sent as `coach-handoff-2026-10-15.md` (that
document is frozen as sent; where it is now stale it says so at the top).

## The four questions, answered with measurements

1. **Citation position.** All 328 train targets start with `[Ch.` at token 0
   (274 answers) or the refusal sentence (54); zero other shapes (measured on
   `data/finetune/quote-refuse-2026-10-13.train-x2d.jsonl`). The engine's
   `[Ch. ` prefill retry is in-distribution — it is not forcing the student
   out of distribution on retries.

2. **column/row, directionally.** Flipping the words does **not** change
   retrieval: both directions return the same chunks in the same order
   (`ch06-066`, `ch08-019`, `ch04-087`, measured today through the frozen
   prompt builder). The student fails **both** directions 0/10 while the 7B
   answers **both** 10/10 *on that same retrieval* (gate evidence). So this is
   a student shape failure, not a retrieval/ranking miss. Also: `ch06-067`
   (never retrieved) is not the gold chunk — `ch06-066` is, and it is shown.

3. **`what about` anomaly.** From the recorded draws: the 7B never refused it
   and never cited it (10 draws: 0 refusals, 0 cited → uncited prose). The
   student's 10/10 pass is post-retry — the engine's `[Ch. ` prefill kept
   only because a citation validates (shipped 2026-10-14). Not training
   leakage, not a 7B false refusal.

4. **Mode contract.** The capture is built from `answer.respond` only. answer
   mode = free prose + tag parsing + verbatim-checked retry; ask mode = the
   quote-enforced path (`answer.ask`, highlight/explain) and is **not** in
   the capture. The "writes freely" vs "verbatim quote + gloss" tension is
   fair on wording: the frozen contract describes the *target shape*; answer
   mode is parser-mediated free prose whose unsupported quotes are stripped.
   Training targets are authored in the target shape deliberately.

## Turn-1 vs retry split, measured (the review asked)

x2d sealed gate, 160 answered-class draws: **Turn-1 pass 21 (13.1%)**,
**retry-rescued 90**, final **111 (69.4%)** — the review's 87% first-turn
failure rate is this number. The pre-retry twin is preserved
(`…model-smallbook_x2d.gate.json`, generated 21:11:42). The 7B: **140/160,
0 rescued** (run 14:35:20 and re-run 23:07:59, identical). Adopted: every
future gate report carries both columns. Whether turn-1 becomes a hard pass
requirement is a **pre-registration decision for the next adoption gate**,
not a retroactive edit to x2d's recorded verdict.

## Adopted into the kit (v3) and the builds

| item | decision |
| --- | --- |
| Teacher quant | `Qwen3.8-27B-UD-Q4_K_XL` becomes the default (~16 GB; filename verified against the HF file API 2026-10-15). Saluki 2-bit demoted to a fallback flag — kept because a 7.9 GB fallback beats a wasted session if the big download fails. |
| Serving | `-c 16384 --parallel 4 --cache-reuse 256 -fa on`; capture at 4 workers; max_tokens **250** (contract answers fit well under 200; `finish_reason=length` is now a loop signal). |
| Pre-gate | 9 probe items + 5 capture rows before the big run (~1 min). Hard stops: thinking leak, empty reply, cap-hit, broken controls. Ceiling items (`why does`, kafka pair) are **printed, not gated** — a persistent ceiling is a measurement for the repo, not a reason to burn a paid session. |
| Resume | keyed by row id; a torn trailing line is dropped, not misread. |
| Loop metric | word-5-gram repeats (`repeat5`) added to the probe, alongside cap-stops (additive — old evidence untouched). |
| Epochs | the finetune notebook derives epochs from the row count to hold total presentations near x2d's 328×6 = 1968; per-epoch checkpoints saved in-session. |
| Refusal mix | final-mix target 16–18%; the capture keeps 23.1% (119/515) as evidence and downsamples at build time. |
| Variant explosion | already cut before this review landed: v2 forms = max 3 gold-pinned forms per deficit card + 30 bare topics + 16 order flips + **32 causal rows** (the review's ceiling-class catch) + 20 fragments + 65 refusals. |
| ddr4 vs ddr5 | **Owner decision 2026-10-15: cite the covered side + boundary gloss** ("the book does not mention DDR4"). The 3 ddr4 capture rows carry the rule in their note; the local build rejects or repairs targets that invent a DDR4 figure. A live test the same day caught exactly that: the current model turned the book's "roughly 1,000 times faster than SSD" into "DDR4 ... 1000 ns" (the string `1000 ns` occurs 0 times in the book). |

## Rejected, with reasons

- **"Temperature 0 makes 10 draws deterministic — a 21-item test wearing a
  210-draw costume."** Our draws are not deterministic at temperature 0
  (bare `Time Series` scores 1/10; loop counts differ run to run; the two 7B
  runs differ in controls). GPU reduction-order flips near-tie logits; the
  10-draw protocol is a stability-weighted pass rate and is identical across
  models, which is what a comparison gate needs. Expanding the sealed suite
  beyond 21 items is recorded backlog, not a blocker for this capture.
- **"Re-capture is renting an A100 to solve problems the 7B already
  passes."** The re-capture is about target *quality* (the whole base was
  captured at temperature 0 from a 7B), not teacher capability. The deficit
  rows failed on 7B-teacher targets; uniform recapture on the same prompts is
  the point, and it costs nothing extra once the teacher is loaded.
- **"1.5–3 h is inflated; it is 15–25 min."** Both are estimates, neither
  measured on this setup. Moot: the kit is 4-way concurrent, prints per-row
  progress, and resumes by id.
- **"Drop Saluki entirely."** Kept as fallback only (see table).

## Backlog recorded (deliberately not this capture)

- sealed suite 21 → 60+ distinct items; an optional temperature-0.2 stability
  run;
- post-capture local build: class-flip diff vs the 7B targets, gloss-length
  filter, `[Ch.` placement census, refusal downsampling — spelled out in the
  kit's post-session cell.

## What changed in the repo with this review

- capture rebuilt at **515 rows** (396 cited / 119 refusal) from the v2 forms
  (`build-teacher-capture-2026-10-15.py`);
- `teacher-capture-colab-2026-10-15.ipynb` **v3** (all rows above);
- `probe-fragment-2026-10-14.py` gained `repeat5`;
- finetune notebook: derived epochs + in-session checkpoints
  (`patch-finetune-epochs-2026-10-15.py` re-applies the patch);
- `coach-handoff-2026-10-15.md` marked superseded where stale (555 rows,
  `-c 32768`).
