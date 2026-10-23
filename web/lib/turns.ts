import type { AnswerBody } from "./engine";

export type Status =
  | "idle"
  | "loading"
  | "streaming"
  | "done"
  | "refused"
  | "stopped"
  | "error";

export type ThreadTurn = {
  question: string;
  answer: string;
  refused: boolean;
  citations: { chunk_id: string; chapter: string; quote: string }[];
};

export type GlossTurn = {
  id: string;
  mode: "answer" | "ask" | "explain" | "quiz";
  question: string;
  status: Status;
  streamText: string;
  resetting: boolean;
  body: AnswerBody | null;
  error: string;
  elapsed: number;
  firstToken: number | null;
  latency: number | null;
  showQuizKey?: boolean;
};

export type GlossItem = {
  id: string;
  kind: "selection" | "whole" | "quiz";
  chunkId: string;
  endChunkId?: string;
  chapter: string;
  heading?: string;
  quote: string;
  at?: number;
  createdAt: number;
  turns: GlossTurn[];
  minimized?: boolean;
  dragOffset?: { x: number; y: number };
  customWidth?: number;
  customHeight?: number;
};

export type TurnPatch = Partial<GlossTurn> | ((turn: GlossTurn) => GlossTurn);

export function mapTurns(turns: GlossTurn[], turnId: string, patch: TurnPatch): GlossTurn[] {
  return turns.map((t) =>
    t.id !== turnId ? t : typeof patch === "function" ? patch(t) : { ...t, ...patch }
  );
}

export function patchGloss(
  glosses: GlossItem[],
  glossId: string,
  patch: Partial<GlossItem> | ((gloss: GlossItem) => GlossItem)
): GlossItem[] {
  return glosses.map((g) =>
    g.id !== glossId ? g : typeof patch === "function" ? patch(g) : { ...g, ...patch }
  );
}

export function patchTurn(
  glosses: GlossItem[],
  glossId: string,
  turnId: string,
  patch: TurnPatch
): GlossItem[] {
  return patchGloss(glosses, glossId, (g) => ({ ...g, turns: mapTurns(g.turns, turnId, patch) }));
}

export function stopOtherActiveTurns(
  glosses: GlossItem[],
  keepGlossId: string,
  keepTurnId: string
): GlossItem[] {
  return glosses.map((g) => ({
    ...g,
    turns: g.turns.map((t) =>
      g.id === keepGlossId && t.id === keepTurnId
        ? t
        : t.status === "loading" || t.status === "streaming"
          ? { ...t, status: "stopped" as Status }
          : t
    ),
  }));
}
