"use client";

import {
  forwardRef,
  memo,
  useState,
  useRef,
  useEffect,
  type CSSProperties,
} from "react";
import AnswerView from "@/components/AnswerView";
import { formatChapter } from "@/lib/anchor";
import { useAsk, type GlossItem } from "@/lib/store";

export type MarginCardProps = {
  gloss: GlossItem;
  top: number;
  placed: boolean;
  mini: boolean;
  active: boolean;
  hovered: boolean;
  floating?: boolean;
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
  onHeightChange?: () => void;
};

type Edge = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
const EDGES: Edge[] = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
const MARGIN = 8;
const MIN_W = 240;
const MIN_H = 120;

function getHandleStyle(edge: Edge): CSSProperties {
  switch (edge) {
    case "n":
      return { position: "absolute", top: -6, left: 14, right: 14, height: 14, cursor: "ns-resize", zIndex: 15, touchAction: "none" };
    case "s":
      return { position: "absolute", bottom: -6, left: 14, right: 14, height: 14, cursor: "ns-resize", zIndex: 15, touchAction: "none" };
    case "e":
      return { position: "absolute", right: -6, top: 14, bottom: 14, width: 14, cursor: "ew-resize", zIndex: 15, touchAction: "none" };
    case "w":
      return { position: "absolute", left: -6, top: 14, bottom: 14, width: 14, cursor: "ew-resize", zIndex: 15, touchAction: "none" };
    case "ne":
      return { position: "absolute", top: -6, right: -6, width: 22, height: 22, cursor: "nesw-resize", zIndex: 16, touchAction: "none" };
    case "nw":
      return { position: "absolute", top: -6, left: -6, width: 22, height: 22, cursor: "nwse-resize", zIndex: 16, touchAction: "none" };
    case "se":
      return { position: "absolute", bottom: -6, right: -6, width: 22, height: 22, cursor: "nwse-resize", zIndex: 16, touchAction: "none" };
    case "sw":
      return { position: "absolute", bottom: -6, left: -6, width: 22, height: 22, cursor: "nesw-resize", zIndex: 16, touchAction: "none" };
  }
}

function modeBadge(gloss: GlossItem): string {
  if (gloss.kind === "quiz") return "Quiz";
  const mode = gloss.turns[0]?.mode;
  if (mode === "explain") return "Explain";
  if (mode === "ask") return "Ask";
  if (mode === "quiz") return "Quiz";
  return "Answer";
}

function getDynamicFollowUps(gloss: GlossItem): string[] {
  const latestTurn = gloss.turns[gloss.turns.length - 1];
  if (latestTurn?.body?.followups && latestTurn.body.followups.length > 0) {
    return latestTurn.body.followups;
  }

  if (gloss.kind === "quiz") {
    return [
      "Why is this the key concept?",
      "Explain this in simpler words",
      "Give a practical example",
    ];
  }

  // Combine available text to extract key concepts
  const corpus = [
    gloss.heading || "",
    gloss.quote || "",
    latestTurn?.body?.answer?.slice(0, 300) || "",
  ].join(" ");

  const commonStops = new Set([
    "the", "a", "an", "in", "on", "at", "for", "to", "of", "and", "or", "is",
    "are", "was", "were", "what", "how", "why", "when", "this", "that", "it",
    "with", "as", "by", "from", "chapter", "figure", "table", "data", "book"
  ]);

  const matches = corpus.match(/\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b|\b[A-Z]{2,}\b/g) || [];
  const candidates: string[] = [];
  const seen = new Set<string>();

  for (const m of matches) {
    const clean = m.trim();
    const lower = clean.toLowerCase();
    if (clean.length < 3) continue;
    if (commonStops.has(lower)) continue;
    if (!seen.has(lower)) {
      seen.add(lower);
      candidates.push(clean);
    }
    if (candidates.length >= 3) break;
  }

  if (candidates.length >= 2) {
    return [
      `How does this apply to ${candidates[0]}?`,
      `What are the trade-offs of ${candidates[1]}?`,
      "Explain with a concrete example",
    ];
  }
  if (candidates.length === 1) {
    return [
      `Why is ${candidates[0]} important here?`,
      "What are the main trade-offs?",
      "Explain with a real-world example",
    ];
  }

  return [
    "Why does this matter in practice?",
    "What are the core trade-offs?",
    "Explain with a real-world example",
  ];
}

function renderAnimatedTokens(text: string) {
  const parts = text.split(/(\s+)/);
  const splitPoint = Math.max(0, parts.length - 12);
  const older = parts.slice(0, splitPoint).join("");
  const recent = parts.slice(splitPoint);

  return (
    <>
      {older ? <span>{older}</span> : null}
      {recent.map((part, i) => (
        <span key={splitPoint + i} className="stream-token">
          {part}
        </span>
      ))}
    </>
  );
}

function renderStreamingText(raw: string) {
  let text = raw.replace(/^(?:read as|asked as):[^\n]*\n?/i, "");

  if (text.startsWith("[")) {
    const firstNewline = text.indexOf("\n");
    const rest = firstNewline !== -1 ? text.slice(firstNewline + 1).trimStart() : "";

    return (
      <div className="turn-body is-streaming">
        <p className="answer">
          {rest ? renderAnimatedTokens(rest) : null}
          <span className="stream-cursor" aria-hidden="true" />
        </p>
      </div>
    );
  }

  return (
    <div className="turn-body is-streaming">
      <p className="answer">
        {renderAnimatedTokens(text)}
        <span className="stream-cursor" aria-hidden="true" />
      </p>
    </div>
  );
}

const MarginCard = forwardRef<HTMLElement, MarginCardProps>(function MarginCard(
  {
    gloss,
    top,
    placed,
    mini,
    active,
    hovered,
    floating = false,
    onSelect,
    onHover,
    onHeightChange,
  },
  ref
) {
  const showCitation = useAsk((s) => s.showCitation);
  const removeGloss = useAsk((s) => s.removeGloss);
  const stopGloss = useAsk((s) => s.stopGloss);
  const toggleQuizKey = useAsk((s) => s.toggleQuizKey);
  const askFollowUp = useAsk((s) => s.askFollowUp);
  const startQuiz = useAsk((s) => s.startQuiz);
  const toggleMinimizeGloss = useAsk((s) => s.toggleMinimizeGloss);
  const setGlossPinned = useAsk((s) => s.setGlossPinned);
  const setGlossDragOffset = useAsk((s) => s.setGlossDragOffset);
  const setGlossWidth = useAsk((s) => s.setGlossWidth);
  const setGlossHeight = useAsk((s) => s.setGlossHeight);
  const removeTurn = useAsk((s) => s.removeTurn);

  const [followUpText, setFollowUpText] = useState("");
  const [copied, setCopied] = useState(false);
  const [isInteracting, setIsInteracting] = useState(false);
  const [expandedTurns, setExpandedTurns] = useState<Record<string, boolean>>({});
  const [maximized, setMaximized] = useState(false);
  const [floatingGeom, setFloatingGeom] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const articleRef = useRef<HTMLElement | null>(null);
  const setRefs = (el: HTMLElement | null) => {
    articleRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) (ref as React.MutableRefObject<HTMLElement | null>).current = el;
  };

  const isDraggingRef = useRef(false);
  const dragStartRef = useRef<{ clientX: number; clientY: number; origX: number; origY: number }>({
    clientX: 0,
    clientY: 0,
    origX: 0,
    origY: 0,
  });
  const barDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    x: number;
    y: number;
    w: number;
    moved: boolean;
  } | null>(null);
  const suppressBarClickRef = useRef(false);
  const livePinRef = useRef<{ x: number; y: number } | null>(null);

  const activeEdgeRef = useRef<Edge | null>(null);
  const resizeStartGeomRef = useRef<{
    clientX: number;
    clientY: number;
    x: number;
    y: number;
    w: number;
    h: number;
    dragX: number;
    dragY: number;
  }>({
    clientX: 0,
    clientY: 0,
    x: 0,
    y: 0,
    w: 320,
    h: 320,
    dragX: 0,
    dragY: 0,
  });

  const dragX = gloss.dragOffset?.x ?? 0;
  const dragY = gloss.dragOffset?.y ?? 0;

  const liveDragRef = useRef<{ x: number; y: number }>({ x: dragX, y: dragY });
  const liveWidthRef = useRef<number | undefined>(gloss.customWidth);
  const liveHeightRef = useRef<number | undefined>(gloss.customHeight);
  const rafRef = useRef<number>(0);

  if (!isDraggingRef.current && !activeEdgeRef.current) {
    liveDragRef.current = { x: dragX, y: dragY };
    liveWidthRef.current = gloss.customWidth;
    liveHeightRef.current = gloss.customHeight;
  }

  // Floating geometry seed and re-clamp on viewport resize
  useEffect(() => {
    if (!floating) return;
    const updateGeom = () => {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const defaultW = Math.min(500, Math.max(240, vw - 24));
      const defaultH = 310;
      const defaultX = Math.round((vw - defaultW) / 2);
      const defaultY = vh - 12 - defaultH;

      setFloatingGeom((prev) => {
        if (!prev) {
          return { x: defaultX, y: defaultY, w: defaultW, h: defaultH };
        }
        const w = Math.min(Math.max(prev.w, MIN_W), Math.max(MIN_W, vw - MARGIN * 2));
        const h = Math.min(Math.max(prev.h, MIN_H), Math.max(MIN_H, vh - MARGIN * 2));
        const x = Math.min(Math.max(prev.x, MARGIN), Math.max(MARGIN, vw - MARGIN - w));
        const y = Math.min(Math.max(prev.y, MARGIN), Math.max(MARGIN, vh - MARGIN - h));
        return { x, y, w, h };
      });
    };
    updateGeom();
    window.addEventListener("resize", updateGeom);
    return () => window.removeEventListener("resize", updateGeom);
  }, [floating]);

  const currentFloatingGeom = (() => {
    if (!floating) return null;
    if (typeof window === "undefined") {
      return { x: 8, y: 72, w: 340, h: 310 };
    }
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    if (maximized) {
      return { x: 8, y: 72, w: vw - 16, h: vh - 80 };
    }
    if (floatingGeom) {
      return floatingGeom;
    }
    const defaultW = Math.min(500, Math.max(240, vw - 24));
    const defaultH = 310;
    const defaultX = Math.round((vw - defaultW) / 2);
    const defaultY = vh - 12 - defaultH;
    return { x: defaultX, y: defaultY, w: defaultW, h: defaultH };
  })();

  const updateLeaderLineDOM = (newX: number, newY: number, customW?: number) => {
    const leaderPath = document.querySelector<SVGPathElement>(`[data-leader-for="${gloss.id}"]`);
    if (!leaderPath) return;
    leaderPath.style.strokeDasharray = "none";
    leaderPath.style.animation = "none";
    const y0 = parseFloat(leaderPath.getAttribute("data-y0") || "0");
    const widthShift = customW ? 320 - customW : 0;
    const x0 = 4;
    const x1 = 27 + newX + widthShift;
    const y1 = Math.round(top + 18 + newY);
    const dx = x1 - x0;
    const cpOffset = Math.max(12, Math.min(80, Math.abs(dx) * 0.45));
    const cp1x = Math.round(x0 + (dx >= 0 ? cpOffset : -cpOffset * 0.5));
    const cp2x = Math.round(x1 - (dx >= 0 ? cpOffset : -cpOffset * 0.5));
    leaderPath.setAttribute("d", `M ${x0} ${y0} C ${cp1x} ${y0}, ${cp2x} ${y1}, ${x1} ${y1}`);
    const endDot = document.querySelector<SVGCircleElement>(`[data-leader-end-for="${gloss.id}"]`);
    if (endDot) {
      endDot.setAttribute("cx", String(x1));
      endDot.setAttribute("cy", String(y1));
    }
  };

  const badge = modeBadge(gloss);
  const latestTurn = gloss.turns[gloss.turns.length - 1];
  const activeChapter = latestTurn?.body?.citations?.[0]?.chapter || gloss.chapter;
  const chLabel = formatChapter(activeChapter);
  const canFollowUp =
    latestTurn &&
    (latestTurn.status === "done" ||
      latestTurn.status === "refused" ||
      latestTurn.status === "stopped");

  const copyAnswer = async () => {
    const parts: string[] = [];
    if (gloss.quote) {
      parts.push(`“${gloss.quote}” (${chLabel})`);
    }
    for (const t of gloss.turns) {
      if (t.question && t.question !== gloss.quote) {
        parts.push(`Q: ${t.question}`);
      }
      if (t.body?.answer) {
        parts.push(t.body.answer);
      } else if (t.streamText) {
        parts.push(t.streamText);
      }
    }
    const text = parts.join("\n\n");
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // ignore clipboard failure
    }
  };

  const isMinimized = mini || Boolean(gloss.minimized);
  const isPinned = Boolean(gloss.minimized && gloss.pinnedAt);

  // A pinned minimized note holds its own spot in the page, in margin-column
  // coordinates: it scrolls with the passage it belongs to, is not placed by
  // the margin flow, and stays draggable.
  useEffect(() => {
    const at = gloss.pinnedAt;
    if (!at) return;
    const clamp = () => {
      const col = articleRef.current?.closest<HTMLElement>(".margin-column");
      if (!col) return;
      const colLeft = col.getBoundingClientRect().left;
      const pageW = document.documentElement.clientWidth;
      const minX = 8 - colLeft;
      const maxX = Math.max(minX, pageW - 8 - at.w - colLeft);
      const x = Math.min(Math.max(at.x, minX), maxX);
      const y = Math.max(at.y, 0);
      if (x !== at.x || y !== at.y) {
        setGlossPinned(gloss.id, { ...at, x, y });
      }
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, [gloss.pinnedAt, gloss.id, setGlossPinned]);

  const pinnedStyle: CSSProperties | null = isPinned
    ? {
        left: 0,
        right: "auto",
        width: `${gloss.pinnedAt!.w}px`,
        transform: `translate3d(${gloss.pinnedAt!.x}px, ${gloss.pinnedAt!.y}px, 0)`,
        zIndex: 30,
        transition: "none",
      }
    : null;

  const floatingStyle: CSSProperties = currentFloatingGeom
    ? {
        position: "fixed",
        left: `${currentFloatingGeom.x}px`,
        top: `${currentFloatingGeom.y}px`,
        width: `${currentFloatingGeom.w}px`,
        height: `${currentFloatingGeom.h}px`,
        zIndex: 45,
        display: "flex",
        flexDirection: "column",
        ...(maximized
          ? {
              transition:
                "left 220ms cubic-bezier(0.32, 0.72, 0, 1), top 220ms cubic-bezier(0.32, 0.72, 0, 1), width 220ms cubic-bezier(0.32, 0.72, 0, 1), height 220ms cubic-bezier(0.32, 0.72, 0, 1)",
            }
          : null),
      }
    : {};

  const marginStyle: CSSProperties = {
    transform:
      dragX !== 0 || dragY !== 0
        ? `translate3d(${dragX}px, ${Math.round(top + dragY)}px, 0)`
        : `translateY(${Math.round(top)}px)`,
    ...(placed ? null : { transition: "none" }),
    ...(gloss.customWidth
      ? {
          width: `${gloss.customWidth}px`,
          left: "auto",
          right: 0,
        }
      : null),
  };

  const style: CSSProperties = floating
    ? floatingStyle
    : pinnedStyle ?? marginStyle;

  // Keyboard: Alt+Arrow resizes, Alt+Shift+Arrow moves.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (floating && e.altKey && !maximized && currentFloatingGeom) {
        const step = e.shiftKey ? 24 : 16;
        const move = e.shiftKey;
        let { x, y, w, h } = currentFloatingGeom;
        if (e.key === "ArrowLeft") move ? (x -= step) : (w -= step, x += step);
        else if (e.key === "ArrowRight") move ? (x += step) : (w += step);
        else if (e.key === "ArrowUp") move ? (y -= step) : (h += step, y -= step);
        else if (e.key === "ArrowDown") move ? (y += step) : (h -= step);
        else return;
        e.preventDefault();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        w = Math.min(Math.max(w, MIN_W), vw - MARGIN * 2);
        h = Math.min(Math.max(h, MIN_H), vh - MARGIN * 2);
        x = Math.min(Math.max(x, MARGIN), vw - MARGIN - w);
        y = Math.min(Math.max(y, MARGIN), vh - MARGIN - h);
        setFloatingGeom({ x, y, w, h });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, floating, maximized, currentFloatingGeom]);

  const handleHeaderPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, a, input, [data-pa-nodrag]")) return;
    e.preventDefault();
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {}
    isDraggingRef.current = true;
    setIsInteracting(true);
    if (floating) {
      const current = currentFloatingGeom || { x: 0, y: 0, w: 320, h: 310 };
      dragStartRef.current = {
        clientX: e.clientX,
        clientY: e.clientY,
        origX: current.x,
        origY: current.y,
      };
    } else {
      dragStartRef.current = {
        clientX: e.clientX,
        clientY: e.clientY,
        origX: liveDragRef.current.x,
        origY: liveDragRef.current.y,
      };
    }
  };

  const handleHeaderPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - dragStartRef.current.clientX;
    const dy = e.clientY - dragStartRef.current.clientY;

    if (floating) {
      if (maximized) return;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const curW = currentFloatingGeom?.w ?? 340;
      const curH = currentFloatingGeom?.h ?? 310;
      const nextX = Math.min(Math.max(8, dragStartRef.current.origX + dx), vw - 8 - curW);
      const nextY = Math.min(Math.max(8, dragStartRef.current.origY + dy), vh - 8 - curH);

      if (articleRef.current) {
        articleRef.current.style.left = `${nextX}px`;
        articleRef.current.style.top = `${nextY}px`;
      }
      return;
    }

    const nextX = Math.round(dragStartRef.current.origX + dx);
    const nextY = Math.round(dragStartRef.current.origY + dy);
    liveDragRef.current = { x: nextX, y: nextY };
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        if (articleRef.current) {
          articleRef.current.style.transform =
            liveDragRef.current.x !== 0 || liveDragRef.current.y !== 0
              ? `translate3d(${liveDragRef.current.x}px, ${Math.round(top + liveDragRef.current.y)}px, 0)`
              : `translateY(${Math.round(top)}px)`;
        }
        updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
      });
    }
  };

  const handleHeaderPointerUp = (e: React.PointerEvent<HTMLElement>) => {
    if (!isDraggingRef.current) return;
    isDraggingRef.current = false;
    setIsInteracting(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}

    if (floating) {
      if (articleRef.current) {
        const nextX = parseFloat(articleRef.current.style.left) || currentFloatingGeom?.x || 8;
        const nextY = parseFloat(articleRef.current.style.top) || currentFloatingGeom?.y || 72;
        setFloatingGeom((prev) => ({
          ...(prev || currentFloatingGeom || { w: 340, h: 310 }),
          x: nextX,
          y: nextY,
        }));
      }
      return;
    }

    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
    setGlossDragOffset(gloss.id, liveDragRef.current);
  };

  const handleHeaderDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (floating) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const defaultW = Math.min(500, Math.max(240, vw - 24));
      const defaultH = 310;
      const defaultX = Math.round((vw - defaultW) / 2);
      const defaultY = vh - 12 - defaultH;
      setFloatingGeom({ x: defaultX, y: defaultY, w: defaultW, h: defaultH });
      setMaximized(false);
      return;
    }
    liveDragRef.current = { x: 0, y: 0 };
    if (articleRef.current) {
      articleRef.current.style.transform = `translateY(${Math.round(top)}px)`;
    }
    updateLeaderLineDOM(0, 0, liveWidthRef.current);
    setGlossDragOffset(gloss.id, { x: 0, y: 0 });
  };

  const handleBarPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0 || !isPinned || !gloss.pinnedAt) return;
    if ((e.target as HTMLElement).closest("button, a, input")) return;
    e.preventDefault();
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {}
    suppressBarClickRef.current = false;
    livePinRef.current = { x: gloss.pinnedAt.x, y: gloss.pinnedAt.y };
    barDragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      x: gloss.pinnedAt.x,
      y: gloss.pinnedAt.y,
      w: gloss.pinnedAt.w,
      moved: false,
    };
  };

  const handleBarPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    const drag = barDragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 3) return;
    if (!drag.moved) {
      drag.moved = true;
      setIsInteracting(true);
    }
    const col = articleRef.current?.closest<HTMLElement>(".margin-column");
    const colLeft = col?.getBoundingClientRect().left ?? 0;
    const pageW = document.documentElement.clientWidth;
    const minX = 8 - colLeft;
    const maxX = Math.max(minX, pageW - 8 - drag.w - colLeft);
    const x = Math.round(Math.min(Math.max(drag.x + dx, minX), maxX));
    const y = Math.round(Math.max(drag.y + dy, 0));
    livePinRef.current = { x, y };
    if (articleRef.current) {
      articleRef.current.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    }
  };

  const handleBarPointerUp = (e: React.PointerEvent<HTMLElement>) => {
    const drag = barDragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    barDragRef.current = null;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
    if (!drag.moved) return;
    suppressBarClickRef.current = true;
    setIsInteracting(false);
    const live = livePinRef.current;
    setGlossPinned(gloss.id, {
      x: live?.x ?? drag.x,
      y: live?.y ?? drag.y,
      w: drag.w,
    });
  };

  const handleResizeDown = (e: React.PointerEvent<HTMLDivElement>, edge: Edge) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {}
    activeEdgeRef.current = edge;
    setIsInteracting(true);

    if (floating) {
      const cur = currentFloatingGeom || { x: 8, y: 72, w: 340, h: 310 };
      resizeStartGeomRef.current = {
        clientX: e.clientX,
        clientY: e.clientY,
        x: cur.x,
        y: cur.y,
        w: cur.w,
        h: cur.h,
        dragX: 0,
        dragY: 0,
      };
      return;
    }

    const cardEl = articleRef.current;
    const turnsEl = cardEl?.querySelector<HTMLElement>(".gloss-turns");
    const currentH = gloss.customHeight ?? (turnsEl?.offsetHeight || 320);
    const currentW = gloss.customWidth ?? 320;
    liveWidthRef.current = currentW;
    liveHeightRef.current = currentH;
    resizeStartGeomRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      x: 0,
      y: 0,
      w: currentW,
      h: currentH,
      dragX: liveDragRef.current.x,
      dragY: liveDragRef.current.y,
    };
  };

  const handleResizeMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const edge = activeEdgeRef.current;
    if (!edge) return;
    const start = resizeStartGeomRef.current;
    const dx = e.clientX - start.clientX;
    const dy = e.clientY - start.clientY;

    if (floating) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const maxW = vw - MARGIN * 2;
      const maxH = vh - MARGIN * 2;

      let nextW = start.w;
      let nextH = start.h;
      let nextX = start.x;
      let nextY = start.y;

      if (edge.includes("e")) {
        nextW = Math.min(Math.max(start.w + dx, MIN_W), maxW);
      }
      if (edge.includes("w")) {
        nextW = Math.min(Math.max(start.w - dx, MIN_W), maxW);
        nextX = start.x + (start.w - nextW);
      }
      if (edge.includes("s")) {
        nextH = Math.min(Math.max(start.h + dy, MIN_H), maxH);
      }
      if (edge.includes("n")) {
        nextH = Math.min(Math.max(start.h - dy, MIN_H), maxH);
        nextY = start.y + (start.h - nextH);
      }

      if (nextX < MARGIN) { nextW -= (MARGIN - nextX); nextX = MARGIN; }
      if (nextY < MARGIN) { nextH -= (MARGIN - nextY); nextY = MARGIN; }
      if (nextX + nextW > vw - MARGIN) { nextW = vw - MARGIN - nextX; }
      if (nextY + nextH > vh - MARGIN) { nextH = vh - MARGIN - nextY; }

      if (articleRef.current) {
        articleRef.current.style.left = `${Math.round(nextX)}px`;
        articleRef.current.style.top = `${Math.round(nextY)}px`;
        articleRef.current.style.width = `${Math.round(nextW)}px`;
        articleRef.current.style.height = `${Math.round(nextH)}px`;
      }
      return;
    }

    let nextW = start.w;
    let nextH = start.h;
    let nextDragX = start.dragX;
    let nextDragY = start.dragY;

    if (edge.includes("w")) {
      const deltaW = start.clientX - e.clientX;
      nextW = Math.max(240, Math.min(540, Math.round(start.w + deltaW)));
    } else if (edge.includes("e")) {
      const deltaW = e.clientX - start.clientX;
      nextW = Math.max(240, Math.min(540, Math.round(start.w + deltaW)));
      nextDragX = Math.round(start.dragX + (nextW - start.w));
    }

    if (edge.includes("s")) {
      const deltaH = e.clientY - start.clientY;
      nextH = Math.max(140, Math.min(720, Math.round(start.h + deltaH)));
    } else if (edge.includes("n")) {
      const deltaH = start.clientY - e.clientY;
      nextH = Math.max(140, Math.min(720, Math.round(start.h + deltaH)));
      const actualDelta = nextH - start.h;
      nextDragY = Math.round(start.dragY - actualDelta);
    }

    liveWidthRef.current = nextW;
    liveHeightRef.current = nextH;
    liveDragRef.current = { x: nextDragX, y: nextDragY };

    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        if (articleRef.current) {
          articleRef.current.style.width = `${nextW}px`;
          articleRef.current.style.left = "auto";
          articleRef.current.style.right = "0px";
          const turnsEl = articleRef.current.querySelector<HTMLElement>(".gloss-turns");
          if (turnsEl) {
            turnsEl.style.maxHeight = `${nextH}px`;
            turnsEl.style.overflowY = "auto";
          }
          articleRef.current.style.transform =
            nextDragX !== 0 || nextDragY !== 0
              ? `translate3d(${nextDragX}px, ${Math.round(top + nextDragY)}px, 0)`
              : `translateY(${Math.round(top)}px)`;
        }
        updateLeaderLineDOM(nextDragX, nextDragY, nextW);
      });
    }
  };

  const handleResizeUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const edge = activeEdgeRef.current;
    if (!edge) return;
    activeEdgeRef.current = null;
    setIsInteracting(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}

    if (floating) {
      if (articleRef.current) {
        const nextX = parseFloat(articleRef.current.style.left) || currentFloatingGeom?.x || 8;
        const nextY = parseFloat(articleRef.current.style.top) || currentFloatingGeom?.y || 72;
        const nextW = parseFloat(articleRef.current.style.width) || currentFloatingGeom?.w || 340;
        const nextH = parseFloat(articleRef.current.style.height) || currentFloatingGeom?.h || 310;
        setFloatingGeom({ x: nextX, y: nextY, w: nextW, h: nextH });
      }
      return;
    }

    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    if (liveWidthRef.current !== undefined) {
      setGlossWidth(gloss.id, liveWidthRef.current);
    }
    if (liveHeightRef.current !== undefined) {
      setGlossHeight(gloss.id, liveHeightRef.current);
    }
    setGlossDragOffset(gloss.id, liveDragRef.current);
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
    onHeightChange?.();
  };

  const nodeTitle = (() => {
    if (gloss.kind === "quiz") {
      return gloss.heading ? `Quiz: ${gloss.heading}` : "Quiz";
    }
    if (gloss.quote) {
      return `“${gloss.quote.replace(/^["'“”‘’]+|["'“”‘’]+$/g, "").trim()}”`;
    }
    const latest = gloss.turns[gloss.turns.length - 1];
    return latest?.question || gloss.turns[0]?.question || chLabel;
  })();

  return (
    <article
      ref={setRefs}
      data-gloss-id={gloss.id}
      aria-label={`${badge} note for ${chLabel}`}
      className={`gloss-card ${floating ? "is-floating" : ""} ${placed ? "" : "unplaced"} ${
        active ? "is-active" : ""
      } ${hovered ? "is-hover" : ""} ${isMinimized ? "is-minimized" : ""} ${
        isPinned ? "is-pinned" : ""
      } ${
        isInteracting ? "is-interacting" : ""
      }`}
      style={style}
      onPointerDown={() => {
        suppressBarClickRef.current = false;
      }}
      onClick={(e) => {
        if (suppressBarClickRef.current) {
          suppressBarClickRef.current = false;
          e.stopPropagation();
          return;
        }
        onSelect();
      }}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onTransitionEnd={(e) => {
        if (
          e.target === e.currentTarget ||
          (e.target as HTMLElement).classList.contains("gloss-card-body-wrap")
        ) {
          onHeightChange?.();
        }
      }}
    >
      {/* Minimized 26px node indicator content (top bullet dot removed) */}
      <div
        className="gloss-node-bar"
        role="button"
        tabIndex={0}
        onPointerDown={handleBarPointerDown}
        onPointerMove={handleBarPointerMove}
        onPointerUp={handleBarPointerUp}
        onPointerCancel={handleBarPointerUp}
        onClick={(e) => {
          e.stopPropagation();
          if (suppressBarClickRef.current) {
            suppressBarClickRef.current = false;
            return;
          }
          if (gloss.minimized) {
            toggleMinimizeGloss(gloss.id);
          }
          onSelect();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            if (gloss.minimized) {
              toggleMinimizeGloss(gloss.id);
            }
            onSelect();
          }
        }}
      >
        <span className="gloss-node-badge">{badge}</span>
        <span className="gloss-node-title">{nodeTitle}</span>
        <button
          type="button"
          className="gloss-node-close"
          aria-label="Remove note"
          title="Remove note"
          onClick={(e) => {
            e.stopPropagation();
            removeGloss(gloss.id);
          }}
        >
          ×
        </button>
      </div>

      {/* Expanded morphable shell */}
      <div
        className="gloss-card-body-wrap"
        style={floating ? { height: "100%", display: "flex", flexDirection: "column", minHeight: 0 } : undefined}
      >
        <div
          className="gloss-card-shell"
          style={floating ? { height: "100%", display: "flex", flexDirection: "column", minHeight: 0, overflow: "hidden" } : undefined}
        >
          {/* Multi-directional 8-way resize handles */}
          {!isMinimized && !maximized && EDGES.map((edge) => (
            <div
              key={edge}
              className={`gloss-resize-${edge}`}
              style={getHandleStyle(edge)}
              onPointerDown={(e) => handleResizeDown(e, edge)}
              onPointerMove={handleResizeMove}
              onPointerUp={handleResizeUp}
              title={`Drag ${edge} edge to resize`}
              aria-hidden="true"
            />
          ))}

          {/* Header row - draggable single-line bubble header */}
          <header
            className="gloss-card-header"
            data-pa-drag
            onPointerDown={handleHeaderPointerDown}
            onPointerMove={handleHeaderPointerMove}
            onPointerUp={handleHeaderPointerUp}
            onDoubleClick={handleHeaderDoubleClick}
            title="Drag header to move · Double-click to reset"
          >
            <div className="gloss-card-title">
              <span className="mini-badge">{badge}</span>
              <span className={`gloss-ch-label`}>{chLabel}</span>
            </div>

            <div className="gloss-card-actions">
              {/* 1. Maximize / Toggle wide */}
              <button
                type="button"
                className="gloss-icon-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  if (floating) {
                    setMaximized((m) => !m);
                  } else {
                    setGlossWidth(gloss.id, (gloss.customWidth ?? 320) >= 420 ? 320 : 440);
                    onHeightChange?.();
                  }
                }}
                aria-label={maximized ? "Restore size" : "Maximize"}
                title={maximized ? "Restore size" : "Maximize"}
              >
                {maximized ? (
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path
                      d="M6 2.5v3.5H2.5M10 13.5v-3.5h3.5"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path
                      d="M2.5 9.5V2.5h7M13.5 6.5v7h-7"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </button>

              {/* 2. Minimize */}
              <button
                type="button"
                className="gloss-icon-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  if (!floating && !gloss.minimized && articleRef.current) {
                    const el = articleRef.current;
                    const col = el.closest<HTMLElement>(".margin-column");
                    const rect = el.getBoundingClientRect();
                    const colRect = col?.getBoundingClientRect();
                    setGlossPinned(gloss.id, {
                      x: Math.round(rect.left - (colRect?.left ?? 0)),
                      y: Math.round(rect.top - (colRect?.top ?? 0)),
                      w: Math.round(rect.width),
                    });
                  }
                  toggleMinimizeGloss(gloss.id);
                }}
                aria-label="Minimize note"
                title={floating ? "Tuck into the ask button" : "Minimize to margin note"}
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="M3.5 6L8 10.5L12.5 6"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>

              {/* 3. Close / Delete note */}
              <button
                type="button"
                className="gloss-icon-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  removeGloss(gloss.id);
                }}
                aria-label="Delete note"
                title="Delete note"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="M4 4l8 8M12 4L4 12"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            </div>
          </header>

          {/* Turns */}
          <div
            className="gloss-turns"
            style={{
              flex: floating ? "1 1 auto" : undefined,
              minHeight: 0,
              maxHeight: floating
                ? undefined
                : gloss.customHeight
                ? `${gloss.customHeight}px`
                : gloss.turns.length > 1
                ? "420px"
                : undefined,
              overflowY: "auto",
            }}
          >
            {gloss.turns.map((turn, idx) => {
              const isLatest = idx === gloss.turns.length - 1;
              const isCollapsible = gloss.turns.length > 1 && !isLatest;
              const isExpanded = isLatest || Boolean(expandedTurns[turn.id || String(idx)]);
              const turnTitle =
                turn.question && turn.question !== gloss.quote
                  ? turn.question
                  : (turn.mode === "quiz" ? "Quiz" : "Initial explanation");

              const seenFigureIdsBefore = new Set(
                gloss.turns
                  .slice(0, idx)
                  .flatMap((t) => t.body?.figures?.map((f) => f.id) || [])
              );
              const turnBody = turn.body
                ? {
                    ...turn.body,
                    figures: (turn.body.figures || []).filter(
                      (f) => !seenFigureIdsBefore.has(f.id)
                    ),
                  }
                : null;

              return (
                <div key={turn.id || idx} className="turn-container">
                  {/* Collapsible header bubble chip for earlier turns */}
                  {isCollapsible ? (
                    <div className="turn-earlier">
                      <button
                        type="button"
                        className="turn-earlier-bubble"
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedTurns((prev) => ({
                            ...prev,
                            [turn.id || String(idx)]: !isExpanded,
                          }));
                          onHeightChange?.();
                        }}
                        aria-expanded={isExpanded}
                        title={turnTitle}
                      >
                        <span className="turn-earlier-text">
                          {turnTitle}
                        </span>
                        <svg
                          className={`turn-chevron ${isExpanded ? "is-open" : ""}`}
                          width="11"
                          height="11"
                          viewBox="0 0 16 16"
                          fill="none"
                          aria-hidden="true"
                        >
                          <path
                            d="M4 6l4 4 4-4"
                            stroke="currentColor"
                            strokeWidth="1.75"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </button>
                      <button
                        type="button"
                        className="turn-prune-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeTurn(gloss.id, turn.id);
                          onHeightChange?.();
                        }}
                        title="Remove this turn"
                        aria-label="Remove turn"
                      >
                        ×
                      </button>
                    </div>
                  ) : null}

                  <div
                    className={`turn-collapse-wrap ${isExpanded ? "is-open" : ""}`}
                    onTransitionEnd={() => onHeightChange?.()}
                  >
                    <div className="turn-collapse-inner">
                      {/* Turn question user bubble when isLatest */}
                      {isLatest &&
                        turn.question &&
                        turn.question !== gloss.quote &&
                        !(turn.mode === "quiz" && turn.question === "Quiz") && (
                          <div
                            className="turn-question-bubble"
                            title={turn.question}
                          >
                            <div className="turn-question-text">
                              {turn.question}
                            </div>
                          </div>
                        )}

                      {/* Loading / Streaming state */}
                      {(turn.status === "loading" || turn.status === "streaming") && (
                        <div className="turn-busy">
                          {turn.resetting && (
                            <p className="meta">
                              Re-checking the quote…
                            </p>
                          )}
                          {turn.streamText ? (
                            renderStreamingText(turn.streamText)
                          ) : (
                            <div className="shimmer-wash">
                              <div className="shimmer" />
                              <div className="shimmer" />
                            </div>
                          )}
                          <div className="turn-status-row">
                            <span>
                              {(turn.elapsed ?? 0).toFixed(0)}s elapsed
                              {turn.elapsed && turn.elapsed > 8
                                ? " (~25s first-load model warmup)"
                                : ""}
                            </span>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                stopGloss(gloss.id);
                              }}
                              className="turn-stop-btn"
                            >
                              Stop
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Completed / Refused state */}
                      {turn.mode === "quiz" && turn.body && (
                        <div className="quiz-turn">
                          <p className="answer quiz-question">
                            {turn.body.answer}
                          </p>
                          <div className="quiz-reveal">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleQuizKey(gloss.id, turn.id);
                              }}
                              className="quiz-toggle"
                            >
                              {turn.showQuizKey ? "Hide the key" : "Show the key"}
                            </button>
                            {turn.showQuizKey && (
                              <div
                                className="quiz-key"
                                role={turn.body.citations[0] ? "button" : undefined}
                                tabIndex={turn.body.citations[0] ? 0 : undefined}
                                onClick={(e) => {
                                  if (turn.body?.citations?.[0]) {
                                    e.stopPropagation();
                                    showCitation({
                                      chunk_id: turn.body.citations[0].chunk_id,
                                      chapter: turn.body.citations[0].chapter,
                                      quote: turn.body.citations[0].quote,
                                      nonce: Date.now(),
                                    });
                                  }
                                }}
                                onKeyDown={(e) => {
                                  if (
                                    (e.key === "Enter" || e.key === " ") &&
                                    turn.body?.citations?.[0]
                                  ) {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    showCitation({
                                      chunk_id: turn.body.citations[0].chunk_id,
                                      chapter: turn.body.citations[0].chapter,
                                      quote: turn.body.citations[0].quote,
                                      nonce: Date.now(),
                                    });
                                  }
                                }}
                                title={
                                  turn.body.citations[0]
                                    ? "Jump to this citation in the book"
                                    : undefined
                                }
                              >
                                {turn.body.citations[0]?.quote ? (
                                  <p className="answer-quote-text">
                                    “{turn.body.citations[0].quote}”
                                  </p>
                                ) : null}
                                {turn.body.citations[0] ? (
                                  <span className="chip">
                                    Ch. {turn.body.citations[0].chapter}
                                  </span>
                                ) : null}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {turn.mode !== "quiz" && turnBody && (
                        <div className="turn-body">
                          <AnswerView
                            body={turnBody}
                            anchorQuote={gloss.quote}
                            question={turn.question}
                            onChip={showCitation}
                            onCopy={copyAnswer}
                            copied={copied}
                          />
                        </div>
                      )}

                      {/* Error state */}
                      {turn.status === "error" && (
                        <p className="turn-error">
                          {turn.error || "Engine error occurred."}
                        </p>
                      )}

                      {/* Stopped state */}
                      {turn.status === "stopped" && (
                        <p className="turn-stopped">
                          Stopped — this is a partial answer.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Bubble Footer */}
          {canFollowUp && (
            <footer
              className={`gloss-card-footer`}
              style={floating ? { flexShrink: 0 } : undefined}
            >
              {/* Follow-up suggestions */}
              {active && (
                <div className="followup-chips" role="group" aria-label="Suggested follow-ups">
                  {gloss.kind === "quiz" && latestTurn?.status === "done" ? (
                    <>
                      <button
                        type="button"
                        className="followup-chip"
                        onClick={(e) => {
                          e.stopPropagation();
                          startQuiz(gloss.chunkId, gloss.chapter);
                        }}
                      >
                        <span className={`followup-chip-text`}>Another quiz question</span>
                      </button>
                      <button
                        type="button"
                        className="followup-chip"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (!latestTurn.showQuizKey) {
                            toggleQuizKey(gloss.id, latestTurn.id);
                          }
                          askFollowUp(gloss.id, "Explain why this is the answer in simpler words");
                        }}
                      >
                        <span className={`followup-chip-text`}>Explain the answer</span>
                      </button>
                    </>
                  ) : (
                    getDynamicFollowUps(gloss).map((chipText) => (
                      <button
                        key={chipText}
                        type="button"
                        className="followup-chip"
                        onClick={(e) => {
                          e.stopPropagation();
                          askFollowUp(gloss.id, chipText);
                        }}
                      >
                        <span className={`followup-chip-text`}>{chipText}</span>
                      </button>
                    ))
                  )}
                </div>
              )}

              {/* Follow-up input */}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const q = followUpText.trim();
                  if (!q) return;
                  askFollowUp(gloss.id, q);
                  setFollowUpText("");
                }}
                onClick={(e) => e.stopPropagation()}
                className="followup-form"
              >
                <input
                  ref={inputRef}
                  data-pa-followup
                  value={followUpText}
                  onChange={(e) => setFollowUpText(e.target.value)}
                  placeholder="Ask a follow-up…"
                  aria-label="Ask a follow-up"
                  className="followup-input"
                />
                <button
                  type="submit"
                  disabled={!followUpText.trim()}
                  aria-label="Send follow-up"
                  className="followup-submit"
                >
                  <svg
                    className={`followup-submit-icon`}
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M3.33 8h9.34M8.67 4l4 4-4 4"
                      stroke="currentColor"
                      strokeWidth="1.75"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              </form>
            </footer>
          )}
        </div>
      </div>
    </article>
  );
});

export default memo(MarginCard);
