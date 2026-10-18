# Fix wave — verification status (interrupted) — 2026-10-18

State: committed 2026-10-18 together with this record, per owner direction,
with verification incomplete. The fix/review round was cut short when an
agent hit its quota; the Final End-to-End Verifier brief did not start.
Everything below is labeled by how it is known: independently reported,
locally re-measured, or unverified author claim.

## Verified independently (wave 1, as reported by the working agent)

- Retrieval: rankings identical on 50 of 50 questions, no score differences.
- Answers: the 60-question stub comparison is identical; the live battery
  matches; refusals stay exact; lowercase citation tags never turned a
  refusal into an answer.
- Call count: LLM calls 48 -> 29 across 22 queries (the optimizer's own A/B,
  possibly contaminated by concurrent retrieval and warm-up changes; not
  independently confirmed).
- Routes and startup: no new routes; the startup race and parallel asks were
  clean.
- Frontend: first contentful paint 76 -> 36 ms; chunk re-renders during
  streaming fell to 0.
- Not reproduced: the "8 dropped frames before" figure measured 0 in the
  baseline.

## Locally re-measured for this record

- `python -m unittest discover -s tests`: **407 tests OK in 4.325 s**
  (2026-10-18). This is the only number here measured in this commit's
  session.

## Fixed, not independently re-verified

- `postings()` immutability (the wrapper costs ~0.03 us per call per the
  author; the ~945,000x speedup figure compares a cache hit to a rebuild and
  must not be quoted as a performance claim).
- Launcher: no longer kills non-`server.py` processes (the dry-run killed
  nothing).
- `/health`: an unreachable engine no longer leaves the input disabled.
- Reading position flushed on page close
  (pagehide/visibilitychange/beforeunload).
- `web/out` served at `GET /` — static-serving path-traversal protection
  unverified.
- Ollama environment in `scripts/launch.py`: `OLLAMA_NUM_PARALLEL=1` and
  `OLLAMA_FLASH_ATTENTION=1` (the VRAM/TTFT numbers in its comment block are
  author-measured, not re-verified here).
- The "Warming up…" fix unverified.

## Still open

- True cold start not proven: the only measured gain was about 1 s, not the
  claimed ~25 s, with the files already in the OS disk cache.
- The final interleaved performance A/B against a baseline worktree has not
  run.
- Waiting on: Frontend Defect and Packaging Engineer.

## Next step

Re-run the Final End-to-End Verifier brief on this tree: true cold start,
interleaved A/B against the baseline worktree, battery and retrieval
equivalence, frontend and static-serving checks, and a launcher review.
Until that passes, treat the fixed-but-unverified items above as open.
