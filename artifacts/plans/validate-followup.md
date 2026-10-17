# validate-followup — measured bugs

**Not a ship-blocker on prior assignment.** `priorQuestion` / `priorAnswer` **are** assigned in `submit()` before `begin()` clears `body`. Quote of the only assignment site:

```ts
// web/lib/store.ts submit() — lines 226–234
} else if (
  (state.status === "done" || state.status === "refused") &&
  state.body
) {
  // Promote the finished turn before begin() clears body.
  priorQuestion = lastAsked || question;
  priorAnswer = state.body.answer;
}
// ...
set({ priorQuestion, priorAnswer });
begin({ question: outgoing, mode: state.mode }, null);
```

Initial empty values (not an assignment after a turn):

```ts
// web/lib/store.ts — lines 184–185
priorQuestion: "",
priorAnswer: "",
```

AskPane only **reads** them (no write path in the pane):

```ts
// web/components/AskPane.tsx — lines 29–36
const priorQuestion = useAsk((s) => s.priorQuestion);
const priorAnswer = useAsk((s) => s.priorAnswer);
const prior =
  !beside && priorQuestion && priorAnswer
    ? { question: priorQuestion, answer: priorAnswer }
    : null;
```

Engine payload **does not** gain a `history` field. Measured send shape:

```ts
// web/lib/store.ts — line 235
begin({ question: outgoing, mode: state.mode }, null);

// web/lib/engine.ts — lines 58–67
export async function askStream(
  payload: { mode: string; question?: string; selection?: string },
  ...
) {
  ...
  body: JSON.stringify({ ...payload, stream: 1 }),
```

---

## Bugs (from files, smallest fix)

### 1. Follow-up fold changes a normal one-shot question — **ship quality bug**

**File:** `web/lib/store.ts`  
**Lines:** 69–75 (`isFollowUp`), 79–82 (`foldFollowUp`), 232 (call site)

```ts
function isFollowUp(text: string): boolean {
  const lower = text.toLowerCase();
  if (lower.startsWith("and ")) return true;
  if (lower.startsWith("what about")) return true;
  if (lower.startsWith("say that")) return true;
  if (lower.startsWith("show me")) return true;
  return text.length <= 48;   // <-- any short standalone Q after a prior
}

function foldFollowUp(question: string, priorQuestion: string): string {
  if (!priorQuestion || !isFollowUp(question)) return question;
  const folded = `${priorQuestion}\nFollow-up: ${question}`;
  ...
}
```

Once any prior is set (and status never returns to `idle` after the first turn), every question ≤48 chars — e.g. "What is a data lake?" — is rewritten into `prior\nFollow-up: …` and sent as `question`. Prefix rules also misfire on standalone "Show me …" / "What about …".

**Smallest fix:** Drop the length ≤48 rule. Keep only explicit short markers, or gate fold on an explicit UI “follow up” affordance. Optionally clear prior when the new question is clearly standalone (long, or no markers).

---

### 2. Double-submit overwrites `lastAsked` while the first stream still runs

**File:** `web/lib/store.ts`  
**Lines:** 211–235 (`submit`), 93–95 (`begin` busy guard)

```ts
// submit always mutates lastAsked + set(prior…) then calls begin:
const outgoing = foldFollowUp(question, priorQuestion);
lastAsked = question;                 // line 233 — runs even if busy
set({ priorQuestion, priorAnswer });  // line 234
begin({ question: outgoing, mode: state.mode }, null);

// begin only refuses the request; it does not roll back lastAsked:
if (controller) {
  set({ busyNote: "Still answering. Wait, or press Stop." });
  return;
}
```

Second Ask/Enter while loading: prior may be promoted from an unfinished body path incorrectly on a later finish, and `lastAsked` already points at the rejected second question. After the first stream’s `onFinal`, the next submit can promote **wrong question + old answer**.

**Smallest fix:** At the top of `submit()`, if `controller` is set, only `set({ busyNote: "…" })` and `return` — do not touch `lastAsked`, prior, or call `begin`. Mirror the same guard in `askSelection` if needed.

---

### 3. `busyNote` not cleared when the in-flight turn ends

**File:** `web/lib/store.ts`  
**Lines:** 94 (set), 97 (clear only on successful begin), 135–148 / 156–157 (finish paths omit clear)

```ts
if (controller) {
  set({ busyNote: "Still answering. Wait, or press Stop." });
  return;
}
set({ busyNote: "" });   // only path that clears
```

`onFinal` / `onError` / AbortError set status and latency but leave `busyNote` as written. Pane only *shows* it under `status === "loading"` (`AskPane.tsx` 89–97), so it is not visible forever — but the string stays in store until the next successful `begin`.

**Smallest fix:** Include `busyNote: ""` in the three terminal `set({…})` blocks inside `begin` (`onFinal`, `onError`, AbortError). Optional: clear on `stop()` too.

---

### 4. Prior not wiped on first token — **not a bug**

**File:** `web/lib/store.ts`  
**Lines:** 100–114 (`begin` reset), 122–127 (`onToken`)

`begin` clears `body` / `streamText`; it does **not** clear `priorQuestion` / `priorAnswer`. `onToken` only appends `streamText` and sets `status: "streaming"`. Prior stays for the loading/streaming window (AskPane 80–87).

No fix.

---

### 5. Engine payload gaining `history` — **not a bug**

Measured: `AskPayload = { mode; question?; selection? }`; JSON is `{ ...payload, stream: 1 }` only. Folding embeds prior text **inside** `question` as a single string — not a `history` array/field. Do not add `history` to the frozen `POST /ask` body.

No fix (keep as-is).

---

### 6. Gaps that leave the pane without a prior when the user might expect one

Not “never assigned,” but incomplete promote paths:

| Path | File:lines | Effect |
|------|------------|--------|
| Promote only on `done` / `refused` + `body` | `store.ts` 223–230 | After `stopped` or `error`, next submit keeps empty prior (body was nulled or never final). |
| `askSelection` never promotes | `store.ts` 238–250 | Selection ask calls `begin` with no `set({ prior… })`; previous pane body vanishes with no prior block unless a prior was already set. |
| Status never returns to `idle` | `store.ts` after first turn | Idle branch (219–222) that “clears priors” is effectively dead after first ask; priors/fold stick for the session. |

**Smallest fixes (optional):**  
- On promote, also accept `stopped` with non-empty `streamText` as prior answer, or skip fold when last turn did not finish.  
- In `askSelection`, before `begin`, if `status` is done/refused and `body`, same promote as `submit`.  
- Only fold when the previous turn actually finished.

---

## Verdict table

| Checklist item | Result |
|----------------|--------|
| prior never set | **No** — assigned in `submit` 228–234 |
| fold changes one-shot Q | **Yes** — `isFollowUp` length ≤48 + prefixes |
| busyNote stuck forever | **Partial** — stuck in store; UI only while loading |
| prior wiped on first token | **No** |
| engine gains `history` | **No** |

**Ship order:** fix (1) fold, then (2) busy double-submit / `lastAsked`, then (3) clear `busyNote` on terminal.

**Next check:** after a fix, ask Q1 → wait for body → ask a short standalone Q2 (≤48 chars, no “and/what about/show me/say that”) and assert the POST body `question` equals Q2 exactly (no `Follow-up:` prefix). Second check: spam Ask while loading and confirm `lastAsked` stays the in-flight question.
