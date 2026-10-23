# Spec: Deslop the codebase (`fix/deslop-codebase`)

## Objective

Give NekoHon a clean starting point for future work. A new reader (human or
agent) must be able to open the repo, understand the app in minutes, and trust
every doc they read.

Done means:

1. **Clean code.** No `#`/`//`/`/* */` comments and no docstrings in our own
   code. No dead code. No function over ~80 lines without reason. `answer.py`
   (4,811 lines) is split into cohesive modules. Duplicated logic is merged.
2. **Docs show the current state only.** No superseded plans, dated change logs,
   finished tasks, or wrong claims (stale model names, Windows-only paths,
   `file:///c:/Users/ADRIAN/...` links, wrong test counts).
3. **Historical material is archived, not deleted.** Dated reports, evidence,
   probes and plans move untouched to `archive/`.
4. **Behavior is preserved and measured.** Engine output is the same before and
   after, proven by a record/replay cassette. Speed changes show before/after
   numbers.
5. **Faster where it is free.** Remove repeated per-request work (linear chunk
   scans, double topic-shift checks, rebuilt history lists) without changing
   output.

Users: the owner and future agents working on this repo.

## Tech Stack (unchanged)

- Engine: Python 3.12 stdlib only (+ `vendor/` snowball stemmer + stopwords).
- Frontend: Next.js under `web/` (Node 22, npm, TypeScript, zustand).
- Inference: local Ollama on `127.0.0.1:11434` (`nekohon_x3`, `nomic-embed-text`).
- No new dependencies of any kind.

## Commands

```sh
# Offline gate (every checkpoint)
python3 -m unittest discover -s tests
python3 -m unittest tests.test_generalization tests.test_query_understanding
python3 verify_index.py
cd web && npx tsc --noEmit && npm run build && cd ..
python3 artifacts/harnesses/secret-scan.py

# Behavior gate (every checkpoint that touches *.py)
python3 .agents/skills/verify/cassette.py replay      # byte-identical engine output

# Live gate (each phase end; restarts server.py on :8000 first)
python3 artifacts/harnesses/step2-battery.py
BATTERY_MODE=answer python3 artifacts/harnesses/step2-battery.py
```

The whole gate is wrapped by the project skill `.agents/skills/verify/`
(created in Phase 0).

## Project Structure (target)

```
GOAL.md, README.md, AGENTS.md, GLOSSARY.md   → current-state docs
docs/ENGINEERING.md                           → architecture + why each mechanism exists
docs/DECISIONS.md                             → measured decisions and negative results, one line each
*.py (root)                                   → engine; answer.py split into cohesive modules
scripts/                                      → launch, setup_models, measure_warmup
web/                                          → Next.js reader (README, AGENTS, app/, components/, lib/)
tests/                                        → unittest suite, machine-independent
artifacts/harnesses, artifacts/datasets       → live verification tools and their data only
artifacts/plans/                              → live plans + one backlog.md
archive/                                      → untouched historical reports, evidence, probes, old plans
.agents/skills/                               → book-companion-ui, verify
vendor/                                       → untouched
```

## Code Style

The style of the existing code, with no comments. The code must say what the
comment used to say: names carry intent, small functions, early returns.

```python
def chunk_by_id(index):
    return index["_by_id"]


def prior_turn_chunk(index, history):
    quote = last_cited_quote(history)
    if not quote:
        return None
    return find_chunk_with_text(index, quote[:50])
```

- Python: snake_case, module-level constants in UPPER_CASE, no type-hint churn.
- TypeScript: keep the existing component and store naming.
- A "why" that the code cannot show (measured reason, negative result) moves to
  `docs/DECISIONS.md`, not to a comment.
- `vendor/` and `archive/` keep their comments (third-party / historical record).

## Testing Strategy

- `unittest` in `tests/`, stdlib only. The suite must be **green and
  machine-independent**: server tests use fixtures in a tempdir, never the real
  `data/`, `books/` or `data/books.json`.
- Behavior cassette (new, in the verify skill): records every Ollama generate /
  stream / embed call and every engine response for a fixed question set
  (battery questions + France refusal; `ask`, `answer`, `explain`, seeded `quiz`;
  history follow-ups; one stream). Recorded once on the pre-refactor tree.
  Replay must be byte-identical. A cassette miss = a prompt or passage set
  changed = stop and revert.
- Frontend: `tsc --noEmit` + `next build` + the existing `tests/test_frontend_*`
  rules (update a rule only when a file moves, never to weaken it).
- Live battery at each phase end, with the known multicloud cold-run flake
  re-run once before it counts as red.

## Boundaries

- **Always:** run the verify skill before every commit; commit and push only to
  `fix/deslop-codebase`; keep the frozen `POST /ask` contract and the routes;
  keep the refusal string exact; keep the GOAL.md constitution; re-export moved
  names that tests or kept harnesses import; restart `server.py` before live gates.
- **Ask first (owner asleep → skip, log in `tasks/todo.md` "Needs owner"):**
  any change that alters engine output; deleting (not archiving) anything;
  touching `vendor/`; changing `GOAL.md`; new dependencies.
- **Never:** merge to `main`; force-push; commit `data/`, `books/`, or keys;
  weaken or delete a test to get green; tune a constant to pass a gate.

## Success Criteria

- [ ] `python3 -m unittest discover -s tests` → `OK` on this Mac (today: 4 failures).
- [ ] Cassette replay byte-identical against the pre-refactor recording.
- [ ] Both live batteries PASS (flake rule applies).
- [ ] `tsc` 0 errors, `next build` passes.
- [ ] `grep` finds 0 comments/docstrings in engine `*.py`, `scripts/`, `tests/`,
      `web/{app,components,lib}` (excluding license headers and `// shortcut:`-free).
- [ ] 0 functions with zero callers (outside archive).
- [ ] `answer.py` < 800 lines; no engine function > 120 lines.
- [ ] Docs: 0 `file:///c:` links, 0 `smallbook_*` as default, 0 references to
      missing files; every doc in the target set describes the current tree.
- [ ] `artifacts/` holds only live tools/data; all history in `archive/`.
- [ ] Frontend: margin layout no longer runs `getBoundingClientRect` for every
      card on every streaming frame; ~310 lines of dead CSS and 40 unused tokens
      removed; `store.ts` and `MarginCard.tsx` split; a browser smoke (open book,
      select, Explain, stream, citation jump) passes in Chrome.
- [ ] Per-request work measured before/after on 20 asks (in-process, cassette
      replay timing) — no regression.
- [ ] `SPEC.md` and `tasks/` are moved to `archive/` in the last checkpoint.

## Open Questions

1. `reground_alphanumeric_quote` hard-codes this book's terms (3NF, SCD, S3,
   IOPS, SLA) and breaks the "generalize" hard rule. Removing it changes output.
   **Default:** keep it, log under "Needs owner".
2. `agentic.py` is a prototype wired nowhere. **Default:** archive it with its
   test.
3. `window/index.html` is the legacy fallback for `GET /` when `web/out` is not
   built. **Default:** keep (it is a live route).
4. The 30+ unused snowball languages in `vendor/`. **Default:** untouched (your
   answer: vendor stays).
5. Tailwind is installed only for its CSS reset; no component uses a utility
   class. Removing it means editing the pinned-dependency test. **Default:**
   keep (no dependency changes).
6. Frontend localStorage keys and stored shapes (`atb-*`, `nekohon-*`,
   `GlossItem`, `UserHighlight` offsets) are user data. **Default:** frozen; the
   15 dead "mirror" store fields are deleted only where they are not persisted.
