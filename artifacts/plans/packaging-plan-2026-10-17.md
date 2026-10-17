# Packaging plan — 2026-10-17

Status: proposal, not approved; nothing implemented. Owner direction recorded
2026-10-17: one model per version — desktop/mac uses `nekohon_x3`; the mobile
weights stay published but **there is no mobile app yet**, so mobile packaging
is out of scope until one exists.

## Goal

One installer that gives a non-technical user the whole companion on a fresh
machine: engine + reader + model + runtime wired, one URL, no Python, no Node,
no manual `ollama` commands. Targets, in order:

1. **Windows `.exe`** (this box can build it).
2. **macOS `.dmg`** (later — needs a Mac or CI, and a signing decision).

## Decisions (owner direction 2026-10-17)

- **One model per version.** `nekohon_x3` (3.1B, Q4_K_M, 1,929,902,656 B,
  SHA-256 `92fb94df…`) is the desktop/mac model. `nekohon_x3_mobile` (1.5B,
  986,048,192 B, `c3d8492f…`) is not bundled anywhere yet; it stays on HF for
  the future mobile app and for manual weak-hardware installs
  (`python scripts/setup_models.py --install --model nekohon_x3_mobile`).
- **Windows first.** `.dmg` waits for a Mac build or a CI runner; signing is a
  separate decision (below).
- **The bundle changes nothing in the engine.** Local-only stands: the engine
  talks to Ollama on `127.0.0.1:11434` and to nothing else. The only network
  moment is install-time (or first-run) model download — the same bytes the
  current `setup_models.py --install` already fetches, SHA-256 verified.

## Open decisions

1. **Thin vs fat installer.**
   - *Thin* (recommended): installer ≈ 50 MB — engine + prebuilt `web/out` +
     launcher. First run downloads the 1.93 GB GGUF from
     `huggingface.co/Skufu1/nekohon-x3` (SHA-verified), pulls
     `nomic-embed-text`, registers the tags, probes generation. One installer
     for everyone; the model stays single-sourced on HF.
   - *Fat*: ≈ 3.1 GB — same + Ollama itself + the GGUF inside. Works offline.
     Cannot be a GitHub release asset (2 GiB per-asset cap); would be hosted on
     HF. Only worth it if the group needs offline installs.
2. **Ollama prerequisite.** Bundle Ollama (MIT — redistributable with its
   license text) for true one-click, or detect it and link its installer.
3. **macOS signing.** Unsigned `.dmg` works but shows Gatekeeper warnings;
   notarized needs an Apple Developer account (est. $99/yr). Decide when the
   Mac build becomes real.

## Wiring steps (all small, in order)

1. **Engine serves the built UI.** `web/next.config.ts` already exports
   statically (`output: "export"`, `web/out/` exists); its comment says "The
   engine does not serve it." Change: `server.py` serves `web/out` at `/`
   (it already serves `window/index.html` there today — keep that as fallback
   or move it behind a path). One process on :8000, one URL.
2. **Launcher.** Detect a running Ollama; start it if absent; start the engine;
   open the browser. Seed: `artifacts/runs/start-engine.bat`. Port rule
   carries over: exactly one listener on :8000 (restart discipline in
   `AGENTS.md`).
3. **First-run model setup inside the installer.** Reuse
   `scripts/setup_models.py` — verify SHA-256 → `ollama create` → probe — with
   a visible progress bar instead of the CLI. Its verify/register/probe
   functions already do exactly this.
4. **Installer wrapper.** Windows: Inno Setup or NSIS, producing
   `Nekohon-Setup-<version>.exe`. macOS later: `create-dmg` + codesign on a
   Mac/CI.

Estimated effort (estimates, not measured): steps 1–3 are days; step 4 thin
installer days; Mac path is its own small project.

## Verification per release (fresh machine, not this box)

1. Clean VM / fresh user profile → run the installer → double-click the app.
2. Browser opens to one URL; ask the France question → refusal exactly
   `Not in this book.`; ask one in-book question → cited answer.
3. `python scripts/setup_models.py --status` → "fully ready to serve";
   downloaded GGUF SHA-256 equals `92fb94df…`.
4. The existing gates stay as they are (battery, sealed suite, hard bench);
   packaging adds a fresh-machine probe, it does not replace them.

## Out of scope (recorded, not rejected)

- Mobile app — does not exist; the 1.5B weights wait for it.
- Auto-update.
- Windows code signing (SmartScreen warns on unsigned; decide later).
- Shipping the book — the FDE EPUB is not redistributed; users ingest their own
  (`ingest.py --epub … --book-id …`).

## Next step

Pick thin vs fat (question 1) and I start with wiring step 1 (`server.py`
serves `web/out`) as its own commit with the battery re-run, per the
tactics rule.
