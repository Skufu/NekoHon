# artifacts/ — where things go

Evidence, harnesses, datasets and dated records. It is not a dump: a file is
here because a zone owns it, and its name carries its date.

There is **no hand-maintained index**. A dated name is the index, and
`ls artifacts/reports` is the listing. The only table kept here is the rolling
claim list at the bottom, and rows leave it after seven days.

## Zones

| Kind | Zone | Naming | Example |
| --- | --- | --- | --- |
| Gate + rules (the only authored top-level files) | `artifacts/` | stable names | `artifacts/prune.py` |
| Stable runners (reused across sessions) | `artifacts/harnesses/` | stable undated name | `artifacts/harnesses/eval.py` |
| One-off probes | `artifacts/probes/` | `probe-*-YYYY-MM-DD.py`, outputs beside it | `artifacts/probes/probe-foo-2026-10-15.py` |
| Capture series (screenshots, traces) | `artifacts/probes/<capture>-YYYY-MM-DD/` | `family-YYYY-MM-DD[-label].ext` | `artifacts/probes/ui-iterations-2026-10-21/` |
| Datasets, question lists | `artifacts/datasets/` | `family-YYYY-MM-DD[-label].json[l]` | `artifacts/datasets/definitional-2026-11-01.jsonl` |
| Findings, decisions, dated records, open plans | `artifacts/reports/` | `family-YYYY-MM-DD[-label].md` | `artifacts/reports/hard-mt-2026-10-24.md` |
| Notebooks (training, capture runs) | `artifacts/reports/` | `family-YYYY-MM-DD[-label].ipynb` | `artifacts/reports/finetune-colab-2026-10-13.ipynb` |
| HTML fixtures and static reports | `artifacts/validate/` (fixture) or `artifacts/reports/` (report) | `*-fixture.html` / `family-YYYY-MM-DD[-label].html` | `artifacts/validate/refusal-fixture.html` |
| Run outputs (json/log/txt, named images) | `artifacts/evidence/<family>/` | `family-YYYY-MM-DD[-label].ext`, one live twin | `artifacts/evidence/eval-plain/` |
| Colab / remote runners | `artifacts/colab/` | `family-YYYY-MM-DD.py`; stable name once reused | `artifacts/colab/install_train_deps.py` |
| Live validation probes + fixtures | `artifacts/validate/` | `probe-*-YYYY-MM-DD.py`, `*-fixture.html` | `artifacts/validate/thread-probe.py` |
| Runs (live server, start scripts) | `artifacts/runs/` | anything; gitignored, never indexed | `artifacts/runs/traces.jsonl` |
| Scratch | `artifacts/scratch/` | anything; gitignored | `artifacts/scratch/` |

New scripts resolve paths as `ROOT / "artifacts" / "<zone>" / <name>`, never a
bare `artifacts/` string, and any `sys.path` insert points at the zone
directory.

## Decision list — where does this new file go?

Ask in order; stop at the first yes.

1. Throwaway (server output, dump, browser profile)? → `runs/` or `scratch/`; do not index it.
2. Reusable code another session will call? → `harnesses/`, stable undated name.
3. A one-off probe script? → `probes/probe-*-YYYY-MM-DD.py`; write its output beside it under the same family name.
4. A capture series worth keeping? → `probes/<capture>-YYYY-MM-DD/`, one dated name per file.
5. A Colab or remote-training runner? → `colab/`, dated unless it is a stable installed dependency.
6. A dataset or question list? → `datasets/family-YYYY-MM-DD[-label].json[l]`.
7. A finding, verdict, dated record, or a plan whose decision is still open? → `reports/family-YYYY-MM-DD[-label].md`.
8. A live-contract validation probe or fixture? → `validate/`.
9. A run output a doc or commit names? → `evidence/<family>/family-YYYY-MM-DD[-label].ext`, one live twin.
10. Did no doc or commit name it? → leave it in `runs/` or `scratch/`. Promotion is the exception.

## Rules

1. **Scratch vs evidence.** Run outputs go to `runs/` (gitignored). A run is
   promoted only when a document or commit references it by name.
2. **Names carry a date.** Any new doc or benchmark output is
   `family-YYYY-MM-DD[-label].ext`. Historical files keep their names.
3. **One live twin per family.** Keep the latest run plus any run a document
   names; superseding means deleting the old one in the same commit, numbers
   folded into the doc first.
4. **The zone rules are the gate.** A tracked file that fits no zone above is
   prunable. Moving a file means fixing every reference in the same commit.
5. **Staleness gate.** A benchmark or doc dated two or more days ago is stale:
   do not treat it as current, do not build on its numbers, do not change code
   to match it. Re-run it, or ask first.
6. **Pre-2026-10-31 records describe JSON indexes** (`data/index.json`), which
   no longer exist; storage moved to SQLite FTS5. Those probes and reports are
   records, not instructions. Do not re-run an old probe until its index load
   is replaced.
7. **Prune before docs commits.** `python artifacts/prune.py --plan` reports
   unindexed, unreferenced, over-versioned and stale files. It walks the Colab
   runs, so it takes minutes.
8. **Deletion is recoverable.** Git history keeps everything.

## Live claims (rolling 7 days)

Rows here point at the record that backs a behaviour shipping today. Anything
older than a week is dropped — the report itself remains in `reports/`.

| Family | What it backs | Status |
| --- | --- | --- |
| `reports/import-long-name-and-progress-2026-11-01.md`, `tests/test_ingest.py`, `tests/test_store.py`, `tests/test_stream_contract.py` | EPUB import: a 226-char Anna's Archive id failed the index write at SQLite's journal name (261 bytes > `NAME_MAX` 255); the id is now `ingest.book_id_for` (capped 64, digest suffix) and `store.write_index` uses a length-independent temp name; `mode:"import"` `stream:1` frames `book` / `progress {done,total}` / `final` and the shelf card draws the real jacket and batch counts (274-chunk book: jacket 0.2 s, final 11.8 s) | LIVE (2026-11-01) |
| `reports/system-map-2026-11-01.{md,mmd,svg,html}` | end-to-end architecture map: SQLite FTS5 index, vocabulary guard, RRF ranking, citation gate, streaming server, Next.js UI | kept (2026-11-01) |
