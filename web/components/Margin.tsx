"use client";

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import MarginCard from "./MarginCard";
import { useAsk, type GlossItem } from "@/lib/store";

const GAP = 16;
const GAP_MINI = 6;
const CROWD = 88;

type Item = {
  id: string;
  desired: number;
  anchorY: number;
  h: number;
  created: number;
  mini: boolean;
};

type Layout = {
  tops: Record<string, number>;
  anchors: Record<string, number>;
  mini: Record<string, boolean>;
  height: number;
};

const gapAfter = (a: Item, b: Item) => (a.mini && b.mini ? GAP_MINI : GAP);

/**
 * Places gloss cards beside their passages. The active gloss sits exactly
 * at its anchor; the rest stack away in both directions without overlapping.
 */
function place(items: Item[], activeId: string | null): Record<string, number> {
  if (items.length === 0) return {};
  const tops: number[] = items.map((it) => it.desired);
  const ai = activeId ? items.findIndex((it) => it.id === activeId) : -1;

  const forward = (from: number) => {
    for (let i = Math.max(1, from); i < items.length; i++) {
      tops[i] = Math.max(
        tops[i],
        tops[i - 1] + items[i - 1].h + gapAfter(items[i - 1], items[i])
      );
    }
  };

  if (ai < 0) {
    tops[0] = Math.max(0, tops[0] ?? 0);
    forward(1);
  } else {
    forward(ai + 1);
    for (let i = ai - 1; i >= 0; i--) {
      tops[i] = Math.min(
        tops[i],
        tops[i + 1] - gapAfter(items[i], items[i + 1]) - items[i].h
      );
    }
    if (tops[0] < 0) {
      tops[0] = 0;
      forward(1);
    }
  }

  const out: Record<string, number> = {};
  items.forEach((it, i) => {
    out[it.id] = tops[i];
  });
  return out;
}

export default function Margin({
  proseRef,
  wide,
}: {
  proseRef: RefObject<HTMLDivElement | null>;
  wide: boolean;
}) {
  const colRef = useRef<HTMLDivElement>(null);
  const cards = useRef(new Map<string, HTMLElement>());

  const glosses = useAsk((s) => s.glosses ?? []);
  const activeGlossId = useAsk((s) => s.activeGlossId);
  const hoveredGlossId = useAsk((s) => s.hoveredGlossId);
  const setActiveGloss = useAsk((s) => s.setActiveGloss);
  const setHoveredGloss = useAsk((s) => s.setHoveredGloss);

  const [layout, setLayout] = useState<Layout>({
    tops: {},
    anchors: {},
    mini: {},
    height: 0,
  });

  const glossesRef = useRef(glosses);
  glossesRef.current = glosses;
  const layoutKey = glosses
    .map(
      (g) =>
        `${g.id}|${g.chunkId}|${g.minimized ? 1 : 0}|${g.turns.length}|${g.turns.some((t) => t.status === "loading" || t.status === "streaming") ? 1 : 0}`
    )
    .join(",");

  const raf = useRef(0);
  const placed = useRef(new Set<string>());

  useLayoutEffect(() => {
    for (const id of Object.keys(layout.tops)) {
      placed.current.add(id);
    }
  }, [layout]);

  const compute = useCallback(() => {
    const col = colRef.current;
    const prose = proseRef.current;
    if (!col || !prose) return;

    const marginColRect = col.getBoundingClientRect();
    const items: Item[] = [];
    const glossMap = new Map<string, GlossItem>();

    for (const g of glossesRef.current) {
      glossMap.set(g.id, g);
      let desired = 0;
      let anchorY = 18;

      const chunkEl = prose.querySelector<HTMLElement>(
        `[data-chunk-id="${CSS.escape(g.chunkId)}"]`
      );

      if (chunkEl) {
        const anchorEl =
          chunkEl.querySelector<HTMLElement>(
            `[data-gloss-id="${CSS.escape(g.id)}"]`
          ) || chunkEl;
        const targetRect = anchorEl.getBoundingClientRect();
        desired = targetRect.top - marginColRect.top - 6;
        anchorY = targetRect.top - marginColRect.top + targetRect.height / 2;
      }

      const isCardMin = Boolean(g.minimized);
      const cardEl = cards.current.get(g.id);
      const h = isCardMin ? 28 : (cardEl?.offsetHeight ?? 80);

      items.push({
        id: g.id,
        desired,
        anchorY,
        h,
        created: g.createdAt,
        mini: isCardMin,
      });
    }

    // Sort by desired position ascending, tie-break by creation time
    items.sort((a, b) => a.desired - b.desired || a.created - b.created);

    const isStreaming = (it: Item) => {
      const g = glossMap.get(it.id);
      return (
        g?.turns.some(
          (t) => t.status === "loading" || t.status === "streaming"
        ) ?? false
      );
    };

    // Mark mini for crowded items or explicitly minimized cards that are not active and not streaming
    const mini: Record<string, boolean> = {};
    items.forEach((it, i) => {
      const g = glossMap.get(it.id);
      const explicitlyMin = Boolean(g?.minimized);
      const near = (j: number) =>
        j >= 0 &&
        j < items.length &&
        Math.abs(items[j].desired - it.desired) < CROWD;

      it.mini =
        explicitlyMin ||
        (it.id !== activeGlossId &&
          !isStreaming(it) &&
          (near(i - 1) || near(i + 1)));
      if (it.mini) {
        it.h = 28;
      }
      mini[it.id] = it.mini;
    });

    const tops = place(items, activeGlossId);
    const anchors: Record<string, number> = {};
    let height = 0;

    for (const it of items) {
      anchors[it.id] = it.anchorY;
      height = Math.max(height, (tops[it.id] ?? 0) + it.h);
    }

    setLayout((prev) => {
      const sameTops =
        Object.keys(tops).length === Object.keys(prev.tops).length &&
        Object.entries(tops).every(
          ([k, v]) =>
            Math.abs((prev.tops[k] ?? -1e9) - v) < 0.5 &&
            Math.abs((prev.anchors[k] ?? -1e9) - (anchors[k] ?? -1e9)) < 0.5
        );
      const sameMini =
        Object.keys(mini).length === Object.keys(prev.mini).length &&
        Object.entries(mini).every(([k, v]) => prev.mini[k] === v);
      const sameHeight = Math.abs(prev.height - height) < 1;

      return sameTops && sameMini && sameHeight
        ? prev
        : { tops, anchors, mini, height };
    });
  }, [layoutKey, activeGlossId, proseRef]);

  const schedule = useCallback(() => {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(compute);
  }, [compute]);

  useLayoutEffect(() => {
    compute();
  }, [compute, wide]);

  useEffect(() => {
    const ro = new ResizeObserver(schedule);
    const prose = proseRef.current;
    if (prose) {
      ro.observe(prose);
      if (prose.parentElement) ro.observe(prose.parentElement);
    }
    for (const el of cards.current.values()) {
      ro.observe(el);
    }
    window.addEventListener("resize", schedule);
    document.fonts?.ready?.then(schedule).catch(() => {});

    return () => {
      ro.disconnect();
      window.removeEventListener("resize", schedule);
      cancelAnimationFrame(raf.current);
    };
  }, [schedule, proseRef, layoutKey, wide]);

  const activeGloss = glosses.find((g) => g.id === activeGlossId) ?? null;

  // Mobile / Narrow sheet fallback (< 1080px)
  if (!wide) {
    if (!activeGloss) return null;
    return (
      <div
        className="gloss-sheet"
        role="dialog"
        aria-label="Margin note"
      >
        <div className="gloss-sheet-bar">
          <span className="gloss-sheet-handle" aria-hidden="true" />
          <button
            type="button"
            aria-label="Close"
            onClick={() => setActiveGloss(null)}
            className="gloss-sheet-close"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="gloss-sheet-body">
          <MarginCard
            gloss={activeGloss}
            top={0}
            placed={true}
            mini={false}
            active={true}
            hovered={false}
            onSelect={() => {}}
            onHover={() => {}}
          />
        </div>
      </div>
    );
  }

  // Active / hovered leader lines
  const lead = [
    activeGlossId,
    hoveredGlossId && hoveredGlossId !== activeGlossId ? hoveredGlossId : null,
  ].filter(
    (x): x is string =>
      Boolean(
        x &&
          layout.tops[x] !== undefined &&
          layout.anchors[x] !== undefined
      )
  );

  return (
    <div
      ref={colRef}
      className="margin-column"
      style={{ minHeight: Math.max(layout.height + 40, 120) }}
    >
      {glosses.length === 0 && (
        <div className="margin-empty">
          <p className="margin-empty-title">This area is for notes.</p>
          <p className="margin-empty-sub">
            Select any highlighted word or phrase, then just start typing to ask.
          </p>
        </div>
      )}

      {/* Gutter SVG Leader Lines */}
      {glosses.length > 0 && (
        <svg
          className="gloss-leader-svg"
          style={{
            left: -28,
            width: 28,
            height: Math.max(1, layout.height),
          }}
          aria-hidden="true"
        >
          {lead.map((id) => {
            const g = glosses.find((item) => item.id === id);
            const dragX = g?.dragOffset?.x ?? 0;
            const dragY = g?.dragOffset?.y ?? 0;
            const widthShift = g?.customWidth ? 320 - g.customWidth : 0;
            const y0 = layout.anchors[id];
            const y1 = (layout.tops[id] ?? 0) + 18 + dragY;
            const x0 = 4;
            const x1 = 27 + dragX + widthShift;
            const dx = x1 - x0;
            const cpOffset = Math.max(12, Math.min(80, Math.abs(dx) * 0.45));
            const cp1x = Math.round(x0 + (dx >= 0 ? cpOffset : -cpOffset * 0.5));
            const cp2x = Math.round(x1 - (dx >= 0 ? cpOffset : -cpOffset * 0.5));
            const d = `M ${x0} ${y0} C ${cp1x} ${y0}, ${cp2x} ${y1}, ${x1} ${y1}`;
            const isActive = id === activeGlossId;
            return (
              <g key={id} opacity={isActive ? 1 : 0.65}>
                <path
                  data-leader-for={id}
                  data-y0={y0}
                  d={d}
                  className="gloss-leader"
                  stroke="var(--rubric)"
                  strokeWidth="1.5"
                  fill="none"
                />
                <circle cx={x0} cy={y0} r={2.5} fill="var(--rubric)" />
                <circle
                  data-leader-end-for={id}
                  cx={x1}
                  cy={y1}
                  r={2}
                  fill="var(--rubric)"
                />
              </g>
            );
          })}
        </svg>
      )}

      {/* Margin cards */}
      {glosses.map((g) => (
        <MarginCardItem
          key={g.id}
          gloss={g}
          top={layout.tops[g.id] ?? 0}
          placed={placed.current.has(g.id)}
          mini={layout.mini[g.id] ?? false}
          active={g.id === activeGlossId}
          hovered={g.id === hoveredGlossId}
          cardsRef={cards}
          onSelect={setActiveGloss}
          onHover={setHoveredGloss}
          onHeightChange={schedule}
        />
      ))}
    </div>
  );
}

const MarginCardItem = memo(function MarginCardItem({
  gloss,
  top,
  placed,
  mini,
  active,
  hovered,
  cardsRef,
  onSelect,
  onHover,
  onHeightChange,
}: {
  gloss: GlossItem;
  top: number;
  placed: boolean;
  mini: boolean;
  active: boolean;
  hovered: boolean;
  cardsRef: React.RefObject<Map<string, HTMLElement>>;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onHeightChange: () => void;
}) {
  const handleSelect = useCallback(() => onSelect(gloss.id), [onSelect, gloss.id]);
  const handleHover = useCallback((h: boolean) => onHover(h ? gloss.id : null), [onHover, gloss.id]);

  return (
    <MarginCard
      ref={(el) => {
        if (el) cardsRef.current?.set(gloss.id, el);
        else cardsRef.current?.delete(gloss.id);
      }}
      gloss={gloss}
      top={top}
      placed={placed}
      mini={mini}
      active={active}
      hovered={hovered}
      onSelect={handleSelect}
      onHover={handleHover}
      onHeightChange={onHeightChange}
    />
  );
});
