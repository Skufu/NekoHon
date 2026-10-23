import { askStream, type AnswerBody, type AskRequest } from "./engine";
import type { UserHighlight } from "./anchor";
import { saveBookState } from "./persist";
import {
  mapTurns,
  patchGloss,
  patchTurn,
  stopOtherActiveTurns,
  type GlossItem,
  type Status,
  type ThreadTurn,
} from "./turns";

type InFlightTurn = {
  controller: AbortController;
  ticker: ReturnType<typeof setInterval>;
  pacerTimer: number | null;
  startedAt: number;
};

export type StreamState = {
  glosses: GlossItem[];
  thread: ThreadTurn[];
  highlights: UserHighlight[];
  activeBookId: string;
};

export type StreamDeps = {
  get: () => StreamState;
  set: (update: (state: StreamState) => Partial<StreamState>) => void;
};

export type StreamPayload = {
  mode: string;
  book_id?: string;
  question?: string;
  selection?: string;
  chunk_id?: string;
  end_chunk_id?: string;
  heading?: string;
  history?: { question: string; answer: string }[];
};

const inFlightMap = new Map<string, InFlightTurn>();

function cancelPacerTimer(flight: InFlightTurn) {
  if (flight.pacerTimer !== null) {
    if (typeof cancelAnimationFrame !== "undefined") {
      cancelAnimationFrame(flight.pacerTimer);
    } else {
      clearTimeout(flight.pacerTimer);
    }
    flight.pacerTimer = null;
  }
}

function cleanupFlight(flight: InFlightTurn) {
  cancelPacerTimer(flight);
  clearInterval(flight.ticker);
  flight.controller.abort();
}

function flightKey(glossId: string, turnId: string) {
  return `${glossId}:${turnId}`;
}

export function abortFlights(glossId?: string) {
  for (const [key, flight] of inFlightMap.entries()) {
    if (!glossId || key.startsWith(`${glossId}:`)) {
      cleanupFlight(flight);
      inFlightMap.delete(key);
    }
  }
}

function startElapsedTicker(deps: StreamDeps, glossId: string, turnId: string, startedAt: number) {
  let shownSecs = 0;
  return setInterval(() => {
    const elapsed = (performance.now() - startedAt) / 1000;
    const secs = Math.round(elapsed) + (elapsed > 8 ? 0.5 : 0);
    if (secs === shownSecs) return;
    shownSecs = secs;
    deps.set((state) => ({ glosses: patchTurn(state.glosses, glossId, turnId, { elapsed }) }));
  }, 200);
}

function pacerStepSize(remaining: string, backlog: number) {
  let step = 0;
  const wordMatch = remaining.match(/^\s*\S+\s*/);
  if (backlog > 40) {
    const cap = Math.min(remaining.length, Math.max(12, Math.ceil(backlog / 5)));
    const spaceIdx = remaining.indexOf(" ", cap);
    if (spaceIdx !== -1 && spaceIdx - cap < 15) {
      step = spaceIdx + 1;
    } else {
      const twoWords = remaining.match(/^(\s*\S+\s*){1,2}/);
      step = twoWords ? twoWords[0].length : cap;
    }
  } else {
    step = wordMatch ? wordMatch[0].length : Math.min(remaining.length, 6);
  }
  if (step <= 0) step = Math.min(remaining.length, 1);
  return step;
}

function finishTurn(
  deps: StreamDeps,
  flight: InFlightTurn,
  key: string,
  glossId: string,
  turnId: string,
  body: AnswerBody
) {
  const { get, set } = deps;
  const { startedAt } = flight;
  cancelPacerTimer(flight);
  clearInterval(flight.ticker);
  inFlightMap.delete(key);

  const latency = (performance.now() - startedAt) / 1000;
  const isRefused = body.refused;

  set((state) => {
    const targetGloss = state.glosses.find((g) => g.id === glossId);
    const targetTurn = targetGloss?.turns.find((t) => t.id === turnId);

    const nextGlosses = patchGloss(state.glosses, glossId, (g) => {
      const nextChunkId =
        g.kind === "quiz" && body.citations?.[0]?.chunk_id
          ? body.citations[0].chunk_id
          : g.chunkId;
      const nextChapter =
        g.kind === "quiz" && body.citations?.[0]?.chapter
          ? String(body.citations[0].chapter)
          : g.chapter;
      return {
        ...g,
        chunkId: nextChunkId,
        chapter: nextChapter,
        turns: mapTurns(g.turns, turnId, {
          status: (isRefused ? "refused" : "done") as Status,
          body,
          streamText: "",
          latency,
        }),
      };
    });

    let nextThread = state.thread;
    if (targetGloss?.kind === "whole" && targetTurn?.question) {
      nextThread = [
        ...state.thread,
        {
          question: targetTurn.question,
          answer: body.answer,
          refused: body.refused,
          citations: body.citations,
        },
      ];
    }

    return { glosses: nextGlosses, thread: nextThread };
  });
  saveBookState(get().activeBookId, get().highlights, get().glosses);
}

function createPacer(
  deps: StreamDeps,
  flight: InFlightTurn,
  key: string,
  glossId: string,
  turnId: string
) {
  const { get, set } = deps;
  const { startedAt } = flight;
  let targetText = "";
  let displayedText = "";
  let finalResult: AnswerBody | null = null;

  const stopPacer = () => cancelPacerTimer(flight);

  const pacerStep = () => {
    flight.pacerTimer = null;
    if (targetText.startsWith("[")) {
      const nlIdx = targetText.indexOf("\n");
      if (nlIdx === -1) {
        displayedText = targetText;
      } else if (displayedText.length < nlIdx + 1) {
        displayedText = targetText.slice(0, nlIdx + 1);
      }
    }

    if (displayedText.length < targetText.length) {
      const remaining = targetText.slice(displayedText.length);
      const backlog = targetText.length - displayedText.length;
      displayedText += remaining.slice(0, pacerStepSize(remaining, backlog));

      set((state) => ({
        glosses: patchTurn(state.glosses, glossId, turnId, (t) => ({
          ...t,
          status: "streaming" as Status,
          streamText: displayedText,
          resetting: false,
          firstToken: t.firstToken ?? (performance.now() - startedAt) / 1000,
        })),
      }));

      if (displayedText.length < targetText.length || finalResult !== null) {
        ensurePacerRunning();
      }
    } else if (finalResult !== null) {
      finishTurn(deps, flight, key, glossId, turnId, finalResult);
    }
  };

  const ensurePacerRunning = () => {
    if (flight.pacerTimer === null) {
      if (typeof requestAnimationFrame !== "undefined") {
        flight.pacerTimer = requestAnimationFrame(pacerStep);
      } else {
        flight.pacerTimer = setTimeout(pacerStep, 16) as unknown as number;
      }
    }
  };

  const push = (text: string) => {
    targetText += text;
    ensurePacerRunning();
  };

  const reset = () => {
    const quoteMatch = targetText.match(
      /^(\[(?:Ch|Chapter)\.?\s*[^\]]+\]\s*["“][^"”\n]+["”]?)/i
    );
    if (quoteMatch) {
      const preservedQuoteLine = quoteMatch[1] + "\n";
      targetText = preservedQuoteLine;
      if (displayedText.length > preservedQuoteLine.length) {
        displayedText = preservedQuoteLine;
      }
      set((state) => ({
        glosses: patchTurn(state.glosses, glossId, turnId, {
          streamText: displayedText,
          resetting: false,
        }),
      }));
      ensurePacerRunning();
    } else {
      targetText = "";
      displayedText = "";
      set((state) => ({
        glosses: patchTurn(state.glosses, glossId, turnId, (t) => ({
          ...t,
          streamText: "",
          resetting: t.streamText.length > 0,
        })),
      }));
    }
  };

  const final = (body: AnswerBody, mode: string) => {
    finalResult = body;
    if (body.answer && !body.refused && mode !== "quiz") {
      if (targetText.length === 0) {
        targetText = body.answer;
      } else if (
        body.answer.startsWith(targetText.trimEnd()) &&
        body.answer.length > targetText.length
      ) {
        targetText = body.answer;
      }
    }
    ensurePacerRunning();
  };

  return { stopPacer, push, reset, final };
}

export function runTurnStream(
  deps: StreamDeps,
  glossId: string,
  turnId: string,
  payload: StreamPayload
) {
  const { get, set } = deps;
  abortFlights();

  set((state) => ({ glosses: stopOtherActiveTurns(state.glosses, glossId, turnId) }));

  const key = flightKey(glossId, turnId);
  const controller = new AbortController();
  const startedAt = performance.now();
  const flight: InFlightTurn = {
    controller,
    ticker: startElapsedTicker(deps, glossId, turnId, startedAt),
    pacerTimer: null,
    startedAt,
  };
  inFlightMap.set(key, flight);

  const pacer = createPacer(deps, flight, key, glossId, turnId);

  const settle = (patch: (latency: number) => Partial<GlossItem["turns"][number]>) => {
    pacer.stopPacer();
    clearInterval(flight.ticker);
    inFlightMap.delete(key);
    const latency = (performance.now() - startedAt) / 1000;
    set((state) => ({ glosses: patchTurn(state.glosses, glossId, turnId, patch(latency)) }));
    saveBookState(get().activeBookId, get().highlights, get().glosses);
  };

  const requestPayload: AskRequest = {
    ...payload,
    book_id: payload.book_id || get().activeBookId,
  };

  askStream(
    requestPayload,
    {
      onToken: pacer.push,
      onReset: pacer.reset,
      onFinal: (body) => pacer.final(body, payload.mode),
      onError: (message) =>
        settle((latency) => ({
          status: "error" as Status,
          error: message,
          streamText: "",
          latency,
        })),
    },
    controller.signal
  ).catch((err: unknown) => {
    const isAbort = (err as { name?: string })?.name === "AbortError";
    settle((latency) => ({
      status: (isAbort ? "stopped" : "error") as Status,
      error: isAbort ? "" : "Engine unreachable — start it on :8000, then ask again.",
      streamText: "",
      latency: isAbort ? latency : null,
    }));
  });
}
