---
name: herdr-lead
description: "Lead agent coordination skill for Herdr. Use when acting as the lead agent in a Herdr session to orchestrate, dispatch tasks to, and collect results from specialized worker terminals (scout, coder, tester, reviewer)."
---

# Herdr Lead Agent Skill

This skill defines the operating protocol and commands for a **Lead Agent** coordinating worker terminals inside Herdr.

## Worker Fleet Topology

Workers live in the `workers` tab of the current Herdr space. By default, 4 specialized workers are configured:

| Worker Role | Terminal Address | Default Agent / Model | Primary Responsibility |
| :--- | :--- | :--- | :--- |
| `scout` | `t18` | `omp` (DeepSeek Flash v4.1) | Repository research, file discovery, trace logs, citations audit, reading documentation |
| `coder` | `t19` | `omp` (DeepSeek Flash v4.1) | Code implementation, refactoring, writing functions and patches |
| `tester` | `t1b` | `omp` (DeepSeek Flash v4.1) | Executing test suites (`unittest`, pytest), running verification scripts, validating gates |
| `reviewer` | `t1c` | `omp` (DeepSeek Flash v4.1) | Code review, diff inspection, checking project constitution/invariants, secret scans |

## Quick CLI Helper

The dispatch helper CLI is located at:
`~/.agents/skills/herdr-lead/scripts/dispatch.py`

```bash
# Check status of all live workers
~/.agents/skills/herdr-lead/scripts/dispatch.py --status

# Dispatch a prompt to a worker
~/.agents/skills/herdr-lead/scripts/dispatch.py scout "Find all files defining retrieve.search in ask-this-book"

# Dispatch and wait for the turn to complete
~/.agents/skills/herdr-lead/scripts/dispatch.py tester "python3 -m unittest discover -s tests" --wait

# Read worker output screen and history
~/.agents/skills/herdr-lead/scripts/dispatch.py --read scout --lines 100
```

## Native Herdr-Core (`hc`) Commands

All Herdr terminals are managed by `herdr-core` (`hc` at `/Users/adriangabriellfrancisco/.local/bin/herdr-core`).

### 1. Inspect Workers
```bash
hc ls
hc get <target>
```
`<target>` accepts either the terminal address (`t18`, `t19`, `t1b`, `t1c`) or the registered label name (`scout`, `coder`, `tester`, `reviewer`).

### 2. Dispatch Work
```bash
# Send task and continue immediately (asynchronous dispatch)
hc send <target> "<instructions>"

# Send task and wait for completion (synchronous turn)
hc send --wait <target> "<instructions>"
```

### 3. Read Output & Collect Results
```bash
# Read recent rendered output from worker
hc read --lines 100 <target>
```

### 4. Wait & Synchronize
```bash
# Wait for a specific worker to finish working
hc wait <target>

# Wait for any child worker to finish
hc wait --children any

# Wait for all child workers to finish
hc wait --children all
```

### 5. Interrupt or Cancel
```bash
# Stop current turn without killing the process
hc interrupt <target>
```

## Rules of Engagement for Lead Agents

1. **Self-contained Tasks**: Each dispatched prompt must specify exact paths, clear instructions, and expected output formats.
2. **Read Before Proceeding**: Never assume a worker succeeded; run `hc read <target>` or `dispatch.py --read <target>` to verify the worker's output before declaring a task done.
3. **Keep Lead Responsive**: Delegate long-running searches or sub-verifications to `scout` or `tester`, leaving the lead agent free to make top-level architectural and user-facing decisions.
