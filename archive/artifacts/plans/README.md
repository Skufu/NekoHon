# Plans — the folder

Everything forward-looking lives here, one file per track, each with its
status. The trunk stays where it always was: `GOAL.md` (the constitution,
stable) and `BUILD_PLAN.md` (the living master plan). The dated *records* —
what actually happened — stay in `artifacts/reports/`; this folder is for
what we intend to do.

| plan | status | file |
| --- | --- | --- |
| Frontend build — the reader + chat window, following Gloss | **shipped 2026-10-18** (NekoHon Start Menu, wooden bookshelf view, cover grid, 3D BookOpen Ex Libris modal, 60/120fps direct-DOM margin physics, live SVG leader line, figure dedupe toggle) | `frontend-build-plan-2026-10-15.md` |
| Pane now — what the reader and ask pane do | **current 2026-10-18** (authoritative live architecture record) | `pane-now.md` |
| Companion track — follow-up, refusal wrap, small model | **shipped 2026-10-18** (multi-turn follow-ups, chapter-neighborhood priority, 7-layer distillation to `nekohon_x3`, adversarial evals) | `companion-track.md` |
| Conversation map — browser thread, optional history, quote-check bounds | **current 2026-10-18** (Zustand thread, chapter-neighborhood bias, simplification fast-path) | `conversation-map.md` |
| Packaging plan — Modelfile recipes and local offline setup | **shipped 2026-10-17** (`models/smallbook_x3/Modelfile`, `models/smallbook_x3_mobile/Modelfile`, `scripts/setup_models.py`) | `packaging-plan-2026-10-17.md` |
| Answer-quality judge — rank the app's real answers, defect-labeled, rater-calibrated | **built 2026-10-15** (method v2 checkables deterministic, voted bits, persona rating) | `answer-quality-judge-plan-2026-10-15.md` |
| Figure understanding — ask about a figure; vision at ingest, not at inference | **parked 2026-10-15** (owner decision: pre-describe at ingest, runtime stays text-only) | `figure-understanding-plan-2026-10-15.md` |
| Frontend navigation (older locator strategy direction) | superseded in part by the build plan; locator design governed offset integration | `frontend-navigation-plan.md` |
| Query rewriter — intent-aware canonical form + retrieval string for vague input | layer 0 landed 2026-10-15 (`canonical_query` + intent classes) | `query-rewriter-plan-2026-10-15.md` |
| What to do — refusal wrap, then false refusals, then follow-up, then distill | executed milestones completed; results in dated reports | `what-to-do.md` |
| Refusal UX — keep the sentence, warm the chrome | executed in AnswerView, MarginCard, and window | `refusal-ux.md` |
| Follow-up history — browser holds one turn | executed: up to 6 turns in store, 2 sent to wire | `follow-up-history.md` |
| Thread finetune — probe x2d before any train; 27B is the teacher | executed via x3 7-layer distillation pipeline | `thread-finetune.md` |
| Gap: running app vs a small companion that chats inside the reader | executed; multi-turn follow-up and multi-book library shipped | `gap-to-goal.md` |
| UX moments — eight ranked companion moves | executed across MarginCard, Lens, Rail, and LibraryView | `ux-possibilities.md` |
| Reader failure moments — ranked by how broken a second turn would feel | mitigated via coherence checks, chapter prioritization, and list synthesis | `reader-failure-moments.md` |
| Distill a small local answerer — five steps, train only after the owner says yes | executed: `nekohon_x3` (3B) and `nekohon_x3_mobile` (1.5B) | `distill-small-model.md` |
| Distill row types | executed: 844 training rows in x3 dataset | `distill-rows.md` |

Directions recorded but not yet plans (they live in `AGENTS.md`, "Post-v1
backlog"):

- Clarify-back (the parked conversational companion) — a third response type,
  conversation state, and contract change.
- Ingest-time figure pre-description (VL model at build-time, runtime stays text-only).

Executed plans stay as dated records next to their verdicts in `artifacts/reports/`.
