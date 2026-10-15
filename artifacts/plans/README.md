# Plans — the folder

Everything forward-looking lives here, one file per track, each with its
status. The trunk stays where it always was: `GOAL.md` (the constitution,
stable) and `BUILD_PLAN.md` (the living master plan). The dated *records* —
what actually happened — stay in `artifacts/reports/`; this folder is for
what we intend to do.

| plan | status | file |
| --- | --- | --- |
| Frontend build — the reader + chat window, following Gloss | **approved 2026-10-15; phase 1 next** | `frontend-build-plan-2026-10-15.md` |
| Frontend + citation navigation (the older direction: locator strategy, foliate-js, contract changes) | superseded in part by the build plan; the locator design still governs the later offsets phase | `frontend-navigation-plan.md` |
| Figure understanding — ask about a figure; vision at ingest, not at inference | **parked 2026-10-15** (user: "we will leave that plan") | `figure-understanding-plan-2026-10-15.md` |

Directions recorded but not yet plans (they live in `AGENTS.md`, "Post-v1
backlog"):

- Conversational companion — the companion that can ask back (parked
  2026-10-15; needs a third response type, conversation state, a contract
  change, multi-turn data, and a re-think of the sealed fragment class).
- Caption quoting (the pipeline feeds only passages today).
- `keep_alive` in the Ollama requests (kills the ~25 s cold start; holds VRAM).
- Two-step distillation (27B → 7B assistant → 3B) — the fallback ladder if a
  future student regresses.

Executed plans stay as dated records next to their verdicts: the x2e build +
pre-registered gate (`artifacts/reports/x2e-plan-2026-10-15.md`), the teacher
capture kit (`artifacts/reports/teacher-capture-colab-2026-10-15.ipynb` + the
session runbook).

Rules for this folder: one file per track, a status line at the top of each,
and when a plan is executed, its outcome goes in a dated report and the plan
file here either updates its status or points at the verdict.
