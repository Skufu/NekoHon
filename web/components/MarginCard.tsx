"use client";

import { forwardRef, memo, useState, useRef, type CSSProperties } from "react";
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
  onSelect: () => void;
  onHover: (hovered: boolean) => void;
  onHeightChange?: () => void;
};

function modeBadge(gloss: GlossItem): string {
  if (gloss.kind === "quiz") return "Quiz";
  const firstTurn = gloss.turns[0];
  const mode = firstTurn?.mode ?? (gloss as unknown as { mode?: string }).mode;
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
    const firstLine = firstNewline !== -1 ? text.slice(0, firstNewline).trim() : text.trim();
    const rest = firstNewline !== -1 ? text.slice(firstNewline + 1).trimStart() : "";

    const quoteMatch = firstLine.match(
      /^\[(?:ch|chapter)\.?\s*([^\]]+)\]\s*["\u201c]?([^"\u201d\n]*)/i
    );

    if (quoteMatch) {
      const ch = quoteMatch[1].trim();
      const quoteText = quoteMatch[2].replace(/["\u201d]$/, "").trim();
      return (
        <div className="turn-body is-streaming">
          <p className="answer">
            {rest ? renderAnimatedTokens(rest) : null}
            <span className="stream-cursor" aria-hidden="true" />
          </p>
          <div className="source-pill-row">
            <span
              className="source-pill"
              title={quoteText ? `“${quoteText}”` : undefined}
            >
              + Source quote · Ch. {formatChapter(ch)}
            </span>
          </div>
        </div>
      );
    }
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
  const setGlossDragOffset = useAsk((s) => s.setGlossDragOffset);
  const setGlossWidth = useAsk((s) => s.setGlossWidth);
  const setGlossHeight = useAsk((s) => s.setGlossHeight);
  const removeTurn = useAsk((s) => s.removeTurn);

  const [followUpText, setFollowUpText] = useState("");
  const [copied, setCopied] = useState(false);
  const [isInteracting, setIsInteracting] = useState(false);
  const [expandedTurns, setExpandedTurns] = useState<Record<string, boolean>>({});
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

  const isResizingRef = useRef<"left" | "bottom" | "top" | "corner" | null>(null);
  const resizeStartRef = useRef<{
    clientX: number;
    clientY: number;
    startWidth: number;
    startHeight: number;
    startDragY: number;
  }>({
    clientX: 0,
    clientY: 0,
    startWidth: 320,
    startHeight: 320,
    startDragY: 0,
  });

  const dragX = gloss.dragOffset?.x ?? 0;
  const dragY = gloss.dragOffset?.y ?? 0;

  const liveDragRef = useRef<{ x: number; y: number }>({ x: dragX, y: dragY });
  const liveWidthRef = useRef<number | undefined>(gloss.customWidth);
  const liveHeightRef = useRef<number | undefined>(gloss.customHeight);
  const rafRef = useRef<number>(0);

  if (!isDraggingRef.current && !isResizingRef.current) {
    liveDragRef.current = { x: dragX, y: dragY };
    liveWidthRef.current = gloss.customWidth;
    liveHeightRef.current = gloss.customHeight;
  }

  const updateLeaderLineDOM = (newX: number, newY: number, customW?: number) => {
    const leaderPath = document.querySelector<SVGPathElement>(`[data-leader-for="${gloss.id}"]`);
    if (!leaderPath) return;
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
  const chLabel = formatChapter(gloss.chapter);
  const latestTurn = gloss.turns[gloss.turns.length - 1];
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

  const style: CSSProperties = {
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

  const handleHeaderPointerDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, a, input")) return;
    e.preventDefault();
    try {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    } catch {}
    isDraggingRef.current = true;
    setIsInteracting(true);
    dragStartRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      origX: liveDragRef.current.x,
      origY: liveDragRef.current.y,
    };
  };

  const handleHeaderPointerMove = (e: React.PointerEvent<HTMLElement>) => {
    if (!isDraggingRef.current) return;
    const dx = e.clientX - dragStartRef.current.clientX;
    const dy = e.clientY - dragStartRef.current.clientY;
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
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
    setGlossDragOffset(gloss.id, liveDragRef.current);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  };

  const handleResizeLeftDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    isResizingRef.current = "left";
    setIsInteracting(true);
    const startW = gloss.customWidth ?? 320;
    liveWidthRef.current = startW;
    resizeStartRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      startWidth: startW,
      startHeight: gloss.customHeight ?? 320,
      startDragY: liveDragRef.current.y,
    };
  };

  const handleResizeLeftMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "left") return;
    const delta = resizeStartRef.current.clientX - e.clientX;
    const nextWidth = Math.max(280, Math.min(540, Math.round(resizeStartRef.current.startWidth + delta)));
    liveWidthRef.current = nextWidth;
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        if (articleRef.current) {
          articleRef.current.style.width = `${liveWidthRef.current}px`;
          articleRef.current.style.left = "auto";
          articleRef.current.style.right = "0px";
        }
        updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
      });
    }
  };

  const handleResizeLeftUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "left") return;
    isResizingRef.current = null;
    setIsInteracting(false);
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    if (liveWidthRef.current !== undefined) {
      setGlossWidth(gloss.id, liveWidthRef.current);
    }
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
    onHeightChange?.();
  };

  const handleResizeBottomDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    isResizingRef.current = "bottom";
    setIsInteracting(true);
    const cardEl = articleRef.current || ((e.currentTarget as HTMLElement).closest(".gloss-card") as HTMLElement | null);
    const turnsEl = cardEl?.querySelector<HTMLElement>(".gloss-turns");
    const currentH = gloss.customHeight ?? (turnsEl?.offsetHeight || 320);
    liveHeightRef.current = currentH;
    resizeStartRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      startWidth: gloss.customWidth ?? 320,
      startHeight: currentH,
      startDragY: liveDragRef.current.y,
    };
  };

  const handleResizeBottomMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "bottom") return;
    const delta = e.clientY - resizeStartRef.current.clientY;
    const nextHeight = Math.max(200, Math.min(720, Math.round(resizeStartRef.current.startHeight + delta)));
    liveHeightRef.current = nextHeight;
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        if (articleRef.current) {
          const turnsEl = articleRef.current.querySelector<HTMLElement>(".gloss-turns");
          if (turnsEl) {
            turnsEl.style.maxHeight = `${liveHeightRef.current}px`;
            turnsEl.style.overflowY = "auto";
          }
        }
      });
    }
  };

  const handleResizeBottomUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "bottom") return;
    isResizingRef.current = null;
    setIsInteracting(false);
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    if (liveHeightRef.current !== undefined) {
      setGlossHeight(gloss.id, liveHeightRef.current);
    }
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
    onHeightChange?.();
  };

  const handleResizeTopDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    isResizingRef.current = "top";
    setIsInteracting(true);
    const cardEl = articleRef.current || ((e.currentTarget as HTMLElement).closest(".gloss-card") as HTMLElement | null);
    const turnsEl = cardEl?.querySelector<HTMLElement>(".gloss-turns");
    const currentH = gloss.customHeight ?? (turnsEl?.offsetHeight || 320);
    liveHeightRef.current = currentH;
    resizeStartRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      startWidth: gloss.customWidth ?? 320,
      startHeight: currentH,
      startDragY: liveDragRef.current.y,
    };
  };

  const handleResizeTopMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "top") return;
    const delta = resizeStartRef.current.clientY - e.clientY;
    const nextHeight = Math.max(200, Math.min(720, Math.round(resizeStartRef.current.startHeight + delta)));
    const actualDelta = nextHeight - resizeStartRef.current.startHeight;
    const nextDragY = Math.round(resizeStartRef.current.startDragY - actualDelta);
    liveHeightRef.current = nextHeight;
    liveDragRef.current = { x: liveDragRef.current.x, y: nextDragY };
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        if (articleRef.current) {
          const turnsEl = articleRef.current.querySelector<HTMLElement>(".gloss-turns");
          if (turnsEl) {
            turnsEl.style.maxHeight = `${liveHeightRef.current}px`;
            turnsEl.style.overflowY = "auto";
          }
          articleRef.current.style.transform =
            liveDragRef.current.x !== 0 || liveDragRef.current.y !== 0
              ? `translate3d(${liveDragRef.current.x}px, ${Math.round(top + liveDragRef.current.y)}px, 0)`
              : `translateY(${Math.round(top)}px)`;
        }
        updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
      });
    }
  };

  const handleResizeTopUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "top") return;
    isResizingRef.current = null;
    setIsInteracting(false);
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    if (liveHeightRef.current !== undefined) {
      setGlossHeight(gloss.id, liveHeightRef.current);
    }
    setGlossDragOffset(gloss.id, liveDragRef.current);
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
    onHeightChange?.();
  };

  const handleResizeCornerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    isResizingRef.current = "corner";
    setIsInteracting(true);
    const cardEl = articleRef.current || ((e.currentTarget as HTMLElement).closest(".gloss-card") as HTMLElement | null);
    const turnsEl = cardEl?.querySelector<HTMLElement>(".gloss-turns");
    const currentH = gloss.customHeight ?? (turnsEl?.offsetHeight || 320);
    const currentW = gloss.customWidth ?? 320;
    liveWidthRef.current = currentW;
    liveHeightRef.current = currentH;
    resizeStartRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      startWidth: currentW,
      startHeight: currentH,
      startDragY: liveDragRef.current.y,
    };
  };

  const handleResizeCornerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "corner") return;
    const deltaX = resizeStartRef.current.clientX - e.clientX;
    const nextWidth = Math.max(280, Math.min(540, Math.round(resizeStartRef.current.startWidth + deltaX)));
    const deltaY = e.clientY - resizeStartRef.current.clientY;
    const nextHeight = Math.max(200, Math.min(720, Math.round(resizeStartRef.current.startHeight + deltaY)));
    liveWidthRef.current = nextWidth;
    liveHeightRef.current = nextHeight;
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        if (articleRef.current) {
          articleRef.current.style.width = `${liveWidthRef.current}px`;
          articleRef.current.style.left = "auto";
          articleRef.current.style.right = "0px";
          const turnsEl = articleRef.current.querySelector<HTMLElement>(".gloss-turns");
          if (turnsEl) {
            turnsEl.style.maxHeight = `${liveHeightRef.current}px`;
            turnsEl.style.overflowY = "auto";
          }
        }
        updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
      });
    }
  };

  const handleResizeCornerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isResizingRef.current !== "corner") return;
    isResizingRef.current = null;
    setIsInteracting(false);
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
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {}
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
      className={`gloss-card ${placed ? "" : "unplaced"} ${
        active ? "is-active" : ""
      } ${hovered ? "is-hover" : ""} ${isMinimized ? "is-minimized" : ""} ${
        isInteracting ? "is-interacting" : ""
      }`}
      style={style}
      onClick={onSelect}
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
      {/* Minimized 26px node indicator content */}
      <div
        className="gloss-node-bar"
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
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
        <span className="gloss-node-dot" aria-hidden="true" />
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
      <div className="gloss-card-body-wrap">
        <div className="gloss-card-shell">
          {/* Multi-directional resize handles */}
          <div
            className="gloss-resize-handle"
            onPointerDown={handleResizeLeftDown}
            onPointerMove={handleResizeLeftMove}
            onPointerUp={handleResizeLeftUp}
            title="Drag left edge to resize card width"
            aria-hidden="true"
          />
          <div
            className="gloss-resize-handle-bottom"
            onPointerDown={handleResizeBottomDown}
            onPointerMove={handleResizeBottomMove}
            onPointerUp={handleResizeBottomUp}
            title="Drag bottom edge to resize card height"
            aria-hidden="true"
          />
          <div
            className="gloss-resize-handle-top"
            onPointerDown={handleResizeTopDown}
            onPointerMove={handleResizeTopMove}
            onPointerUp={handleResizeTopUp}
            title="Drag top edge to resize card height"
            aria-hidden="true"
          />
          <div
            className="gloss-resize-handle-corner"
            onPointerDown={handleResizeCornerDown}
            onPointerMove={handleResizeCornerMove}
            onPointerUp={handleResizeCornerUp}
            title="Drag corner to resize card width and height"
            aria-hidden="true"
          />

          {/* Header row - draggable */}
          <header
            className="gloss-card-header"
            onPointerDown={handleHeaderPointerDown}
            onPointerMove={handleHeaderPointerMove}
            onPointerUp={handleHeaderPointerUp}
            onDoubleClick={(e) => {
              e.stopPropagation();
              liveDragRef.current = { x: 0, y: 0 };
              if (articleRef.current) {
                articleRef.current.style.transform = `translateY(${Math.round(top)}px)`;
              }
              updateLeaderLineDOM(0, 0, liveWidthRef.current);
              setGlossDragOffset(gloss.id, { x: 0, y: 0 });
            }}
            title="Drag header to move card · Double-click to reset position"
          >
            <div className="gloss-card-title">
              <span className="mini-badge">{badge}</span>
              <span className="meta">·</span>
              <span className="meta">
                {gloss.kind === "whole"
                  ? `Whole book · ${chLabel}`
                  : chLabel}
              </span>
            </div>

            <div className="gloss-card-actions">
              {/* Width expand/compact toggle */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setGlossWidth(gloss.id, (gloss.customWidth ?? 320) >= 420 ? 320 : 440);
                  onHeightChange?.();
                }}
                aria-label="Toggle wide card"
                title={(gloss.customWidth ?? 320) >= 420 ? "Compact width" : "Expand width"}
                className="gloss-icon-btn"
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <polyline points="15 3 21 3 21 9" />
                  <polyline points="9 21 3 21 3 15" />
                  <line x1="21" y1="3" x2="14" y2="10" />
                  <line x1="3" y1="21" x2="10" y2="14" />
                </svg>
              </button>

              {/* Minimize to node */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleMinimizeGloss(gloss.id);
                }}
                aria-label="Minimize note"
                title="Minimize to margin node"
                className="gloss-icon-btn"
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
              </button>

              {/* Copy answer */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  copyAnswer();
                }}
                aria-label={copied ? "Copied" : "Copy answer"}
                title={copied ? "Copied" : "Copy answer with citations"}
                className="gloss-icon-btn"
              >
                {copied ? (
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    className="gloss-icon-good"
                  >
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : (
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                )}
              </button>

              {/* Delete note */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removeGloss(gloss.id);
                }}
                aria-label="Delete note"
                title="Delete note"
                className="gloss-icon-btn"
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </header>

          {/* Sleek single-line passage ref bar */}
          {gloss.quote && gloss.kind !== "quiz" ? (
            <div
              className="card-passage-ref"
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                const topCite = latestTurn?.body?.citations?.[0];
                showCitation({
                  chunk_id: topCite?.chunk_id || gloss.chunkId,
                  chapter: topCite?.chapter ? String(topCite.chapter) : gloss.chapter,
                  quote: topCite?.quote || gloss.quote,
                  at: topCite ? undefined : gloss.at,
                  nonce: Date.now(),
                });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  const topCite = latestTurn?.body?.citations?.[0];
                  showCitation({
                    chunk_id: topCite?.chunk_id || gloss.chunkId,
                    chapter: topCite?.chapter ? String(topCite.chapter) : gloss.chapter,
                    quote: topCite?.quote || gloss.quote,
                    at: topCite ? undefined : gloss.at,
                    nonce: Date.now(),
                  });
                }
              }}
              title="Jump to this passage in the book"
            >
              <span className="card-passage-quote">“{gloss.quote}”</span>
              <span className="card-passage-jump">Jump</span>
            </div>
          ) : null}

          {/* Turns */}
          <div
            className="gloss-turns"
            style={{
              maxHeight: gloss.customHeight
                ? `${gloss.customHeight}px`
                : (gloss.turns.length > 1 ? "420px" : undefined),
              overflowY: gloss.customHeight || gloss.turns.length > 1 ? "auto" : undefined,
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
                  {/* Collapsible header pill for earlier turns */}
                  {isCollapsible ? (
                    <div className="turn-accordion-header">
                      <button
                        type="button"
                        className={`turn-accordion-btn ${isExpanded ? "is-expanded" : ""}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedTurns((prev) => ({
                            ...prev,
                            [turn.id || String(idx)]: !isExpanded,
                          }));
                          onHeightChange?.();
                        }}
                        aria-expanded={isExpanded}
                      >
                        <span className="turn-accordion-arrow" aria-hidden="true">
                          {isExpanded ? "▾" : "▸"}
                        </span>
                        <span className="turn-accordion-title">{turnTitle}</span>
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

                  {/* Multi-turn separator for latest turn */}
                  {idx > 0 && isLatest ? (
                    <div className="turn-divider">
                      <span className="turn-badge">Follow-up</span>
                    </div>
                  ) : null}

                  <div
                    className={`turn-collapse-wrap ${isExpanded ? "is-open" : ""}`}
                    onTransitionEnd={() => onHeightChange?.()}
                  >
                    <div className="turn-collapse-inner">
                      {/* Turn question (for follow-ups or ask queries) when isLatest */}
                      {isLatest &&
                        turn.question &&
                        turn.question !== gloss.quote &&
                        !(turn.mode === "quiz" && turn.question === "Quiz") && (
                          <p className="turn-question">
                            {turn.question}
                          </p>
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
                            onChip={showCitation}
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

          {/* Follow-up suggestions */}
          {canFollowUp && active && (
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
                    Another quiz question
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
                    Explain the answer
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
                    {chipText}
                  </button>
                ))
              )}
            </div>
          )}

          {/* Follow-up input at bottom */}
          {canFollowUp && (
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
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                >
                  <line x1="12" y1="19" x2="12" y2="5" />
                  <polyline points="5 12 12 5 19 12" />
                </svg>
              </button>
            </form>
          )}
        </div>
      </div>
    </article>
  );
});

export default memo(MarginCard);
