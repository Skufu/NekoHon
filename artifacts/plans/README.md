# Plans — the folder

Everything forward-looking lives here, one file per track, each with its
status. The trunk stays where it always was: `GOAL.md` (the constitution,
stable) and `BUILD_PLAN.md` (the living master plan). The dated *records* —
what actually happened — stay in `artifacts/reports/`; this folder is for
what we intend to do.

| plan | status | file |
| --- | --- | --- |
| Frontend build — the reader + chat window, following Gloss | **approved 2026-10-15; phase 1 landed 2026-10-15 (reader + ask live at `http://localhost:3100`); phase 2 v1 landed same day — the lens + a single margin card, the one-stream fix, the resizable ask pane; collision stacking + owner eyeball pending** | `frontend-build-plan-2026-10-15.md` |
| Frontend + citation navigation (the older direction: locator strategy, foliate-js, contract changes) | superseded in part by the build plan; the locator design still governs the later offsets phase | `frontend-navigation-plan.md` |
| Figure understanding — ask about a figure; vision at ingest, not at inference | **parked 2026-10-15** (owner decision) | `figure-understanding-plan-2026-10-15.md` |
| Answer-quality judge — rank the app's real answers, defect-labeled, rater-calibrated | **built 2026-10-15 — method v2 landed and measured: checkables deterministic (pins catch the false refusals), voted bits wobble 3/27 rows, persona 20/24 stable across two runs; pairwise-for-builds still to come** | `answer-quality-judge-plan-2026-10-15.md` |
| Query rewriter — intent-aware canonical form + retrieval string for vague input | **layer 0 landed 2026-10-15** (versus form + list lead-in + half-covered gloss). Layer 1 still waits on B–D | `query-rewriter-plan-2026-10-15.md` |
| Pane now — what the reader and ask pane do | **current 2026-10-15** | `pane-now.md` |
| Companion track — follow-up, refusal wrap, small model | **started 2026-10-15 — read this first** | `companion-track.md` |
| Conversation map — browser thread, optional history, quote-check bounds | **map 2026-10-15 — read before touching conversation** | `conversation-map.md` |
| What to do — refusal wrap, then false refusals, then follow-up, then distill | **decision page; step 1 started in UI** | `what-to-do.md` |
| Refusal UX — keep the sentence, warm the chrome | **option 1 started in AnswerView and window** | `refusal-ux.md` |
| Follow-up history — browser holds one turn | **first slice started in the Next store** | `follow-up-history.md` |
| Thread finetune — probe x2d before any train; 27B is the teacher | **draft 2026-10-15 — do not train from this file** | `thread-finetune.md` |
| Gap: running app vs a small companion that chats inside the reader | **draft 2026-10-15 — aim text is stale where it says follow-up is not in the goal; the sentence is in `GOAL.md` now** | `gap-to-goal.md` |
| UX moments — eight ranked companion moves | **design 2026-10-15 — no source edited** | `ux-possibilities.md` |
| Follow-up history — one client-held turn, then an optional wire field | **draft 2026-10-15 — design only** | `follow-up-history.md` |
| Reader failure moments — ranked by how broken a second turn would feel | **draft 2026-10-15 — rank assumed unless marked measured** | `reader-failure-moments.md` |
| Distill a small local answerer — five steps, train only after the owner says yes | **draft 2026-10-15 — tactic, not a gate** | `distill-small-model.md` |
| Distill row types | **sketch 2026-10-15 — do not train from the file** | `distill-rows.md` |

Directions recorded but not yet plans (they live in `AGENTS.md`, "Post-v1
backlog"):

- Clarify-back (the parked conversational companion, 2026-10-15) — a third
  response type, conversation state, a contract change, and a re-think of the
  sealed fragment class. Follow-up itself is no longer this item: `GOAL.md`
  covers a later turn (simpler words, the cited passage, the figure). Order
  and pointers: `companion-track.md`.
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
