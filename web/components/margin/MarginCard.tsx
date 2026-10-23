"use client";

import { forwardRef, memo, useState, useRef, type CSSProperties } from "react";
import CardActions from "@/components/margin/CardActions";
import FollowUpForm from "@/components/margin/FollowUpForm";
import TurnView from "@/components/margin/TurnView";
import { useDragResize } from "@/components/margin/useDragResize";
import { formatChapter } from "@/lib/anchor";
import { useAsk, type GlossItem } from "@/lib/store";

type MarginCardProps = {
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
  const toggleMinimizeGloss = useAsk((s) => s.toggleMinimizeGloss);

  const [followUpText, setFollowUpText] = useState("");
  const [copied, setCopied] = useState(false);
  const [expandedTurns, setExpandedTurns] = useState<Record<string, boolean>>({});

  const articleRef = useRef<HTMLElement | null>(null);
  const setRefs = (el: HTMLElement | null) => {
    articleRef.current = el;
    if (typeof ref === "function") ref(el);
    else if (ref) (ref as React.MutableRefObject<HTMLElement | null>).current = el;
  };

  const { isInteracting, dragX, dragY, dragHandlers, resizeHandlers, resetPosition } =
    useDragResize({ gloss, top, articleRef, onHeightChange });

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
    } catch {}
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
      <div className="gloss-card-body-wrap">
        <div className="gloss-card-shell">
          <div
            className="gloss-resize-handle"
            {...resizeHandlers("left")}
            title="Drag left edge to resize card width"
            aria-hidden="true"
          />
          <div
            className="gloss-resize-handle-bottom"
            {...resizeHandlers("bottom")}
            title="Drag bottom edge to resize card height"
            aria-hidden="true"
          />
          <div
            className="gloss-resize-handle-top"
            {...resizeHandlers("top")}
            title="Drag top edge to resize card height"
            aria-hidden="true"
          />
          <div
            className="gloss-resize-handle-corner"
            {...resizeHandlers("corner")}
            title="Drag corner to resize card width and height"
            aria-hidden="true"
          />
          <header
            className="gloss-card-header"
            {...dragHandlers}
            onDoubleClick={(e) => {
              e.stopPropagation();
              resetPosition();
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

            <CardActions gloss={gloss} copied={copied} onCopy={copyAnswer} onHeightChange={onHeightChange} />
          </header>
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
          <div
            className="gloss-turns"
            style={{
              maxHeight: gloss.customHeight
                ? `${gloss.customHeight}px`
                : (gloss.turns.length > 1 ? "420px" : undefined),
              overflowY: gloss.customHeight || gloss.turns.length > 1 ? "auto" : undefined,
            }}
          >
            {gloss.turns.map((turn, idx) => (
              <TurnView
                key={turn.id || idx}
                gloss={gloss}
                idx={idx}
                expanded={Boolean(expandedTurns[turn.id || String(idx)])}
                onSetExpanded={(key, value) =>
                  setExpandedTurns((prev) => ({ ...prev, [key]: value }))
                }
                onHeightChange={onHeightChange}
              />
            ))}
          </div>

          {canFollowUp && (
            <FollowUpForm
              gloss={gloss}
              active={active}
              text={followUpText}
              onTextChange={setFollowUpText}
            />
          )}
        </div>
      </div>
    </article>
  );
});

export default memo(MarginCard);
