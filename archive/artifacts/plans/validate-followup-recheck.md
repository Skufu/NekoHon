# validate-followup-recheck

Source: `web/lib/store.ts` (read-only, current file)

## 1. isFollowUp — no length <= 48; only and / what about / say that / show me

**PASS**

- Lines 69–77: `isFollowUp` returns only the four `startsWith` checks.
- No `length <= 48` (or any length heuristic) in the function.

```69:77:web/lib/store.ts
function isFollowUp(text: string): boolean {
  const lower = text.toLowerCase();
  return (
    lower.startsWith("and ") ||
    lower.startsWith("what about") ||
    lower.startsWith("say that") ||
    lower.startsWith("show me")
  );
}
```

## 2. submit returns before lastAsked = question when controller is set

**PASS**

- Lines 217–219: if `controller` is set, set `busyNote` and `return`.
- Line 239: `lastAsked = question` only runs after that early return.

```217:219:web/lib/store.ts
      if (controller) {
        set({ busyNote: "Still answering. Wait, or press Stop." });
        return;
```

```238:241:web/lib/store.ts
      const outgoing = foldFollowUp(question, priorQuestion);
      lastAsked = question;
      set({ priorQuestion, priorAnswer });
      begin({ question: outgoing, mode: state.mode }, null);
```

## 3. busyNote cleared on final, error, and abort

**PASS**

| Path | Lines | Cleared |
|------|-------|---------|
| final (`onFinal`) | 139–145 (`busyNote: ""` at 143) | yes |
| error (`onError`) | 150 (`busyNote: ""`) | yes |
| abort (`AbortError` catch) | 158–160 (`busyNote: ""` at 159) | yes |

```136:160:web/lib/store.ts
        onFinal: (body) => {
          const latency = (performance.now() - startedAt) / 1000;
          finish();
          set({
            status: body.refused ? "refused" : "done",
            body,
            streamText: "",
            busyNote: "",
            latency,
          });
        },
        onError: (message) => {
          const latency = (performance.now() - startedAt) / 1000;
          finish();
          set({ status: "error", error: message, streamText: "", busyNote: "", latency });
        },
// ...
      if (name === "AbortError") {
        set({ status: "stopped", busyNote: "", latency });
        return;
      }
```

## Summary

| # | Check | Result |
|---|--------|--------|
| 1 | isFollowUp prefixes only | PASS |
| 2 | submit early-return before lastAsked | PASS |
| 3 | busyNote cleared on final / error / abort | PASS |

All three pass. No bad lines.
