"use client";

import { useMemo, useRef, useState, type PointerEvent } from "react";
import { formatChapter } from "@/lib/anchor";
import type { Chunk } from "@/lib/engine";
import { useAsk } from "@/lib/store";

type RailProps = {
  chunks: Chunk[];
  activeChunkId: string;
  scrollProgress: number;
  viewportRatio: number;
  onScrub: (ratio: number) => void;
};

export default function Rail({
  chunks,
  activeChunkId,
  scrollProgress,
  viewportRatio,
  onScrub,
}: RailProps) {
  const highlights = useAsk((s) => s.highlights ?? []);
  const glossAnchors = useAsk((s) => s.glossAnchors ?? []);

  const railRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef(false);
  const [hoveredChapter, setHoveredChapter] = useState<{
    chapter: string;
    heading: string;
    y: number;
  } | null>(null);

  const total = chunks.length || 1;

  const chunkIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    chunks.forEach((c, idx) => map.set(c.chunk_id, idx));
    return map;
  }, [chunks]);

  // Chapter boundaries
  const chapterMarks = useMemo(() => {
    const list: { chapter: string; heading: string; index: number; pct: number }[] = [];
    chunks.forEach((chunk, i) => {
      if (i === 0 || chunk.chapter !== chunks[i - 1]?.chapter) {
        list.push({
          chapter: chunk.chapter,
          heading: chunk.heading,
          index: i,
          pct: (i / total) * 100,
        });
      }
    });
    return list;
  }, [chunks, total]);

  // Set of chunk IDs with highlights
  const highlightedChunks = useMemo(() => {
    return highlights
      .map((h) => {
        const idx = chunkIndexMap.get(h.chunkId);
        return idx !== undefined ? { id: h.id, pct: (idx / total) * 100 } : null;
      })
      .filter((v): v is { id: string; pct: number } => v !== null);
  }, [chunkIndexMap, highlights, total]);

  // Set of chunk IDs with glosses
  const glossChunks = useMemo(() => {
    return glossAnchors
      .map((g) => {
        const idx = chunkIndexMap.get(g.chunkId);
        return idx !== undefined ? { id: g.id, pct: (idx / total) * 100 } : null;
      })
      .filter((v): v is { id: string; pct: number } => v !== null);
  }, [chunkIndexMap, glossAnchors, total]);

  const scrub = (clientY: number) => {
    if (!railRef.current) return;
    const rect = railRef.current.getBoundingClientRect();
    const y = Math.max(0, Math.min(rect.height, clientY - rect.top));
    const ratio = rect.height > 0 ? y / rect.height : 0;
    onScrub(ratio);
  };

  const handlePointerDown = (e: PointerEvent<HTMLDivElement>) => {
    dragRef.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    scrub(e.clientY);
  };

  const handlePointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!railRef.current) return;
    const rect = railRef.current.getBoundingClientRect();
    const y = e.clientY - rect.top;

    if (dragRef.current && e.buttons) {
      scrub(e.clientY);
    }

    // Determine nearest chapter for tooltip
    if (rect.height > 0) {
      const hoverRatio = Math.max(0, Math.min(1, y / rect.height));
      const chunkIndex = Math.min(chunks.length - 1, Math.floor(hoverRatio * chunks.length));
      const chunk = chunks[chunkIndex];
      if (chunk) {
        setHoveredChapter({
          chapter: chunk.chapter,
          heading: chunk.heading,
          y,
        });
      }
    }
  };

  const handlePointerUp = () => {
    dragRef.current = false;
  };

  const thumbHeight = Math.max(16, viewportRatio * 100);
  const thumbTop = Math.max(
    0,
    Math.min(100 - thumbHeight, scrollProgress * (100 - thumbHeight))
  );

  return (
    <div
      ref={railRef}
      role="slider"
      aria-label="Reading progress minimap"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(scrollProgress * 100)}
      tabIndex={-1}
      className="rail"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onPointerLeave={() => setHoveredChapter(null)}
    >
      {/* Background track line */}
      <div className="rail-track" />

      {/* Chapter boundary tick marks */}
      {chapterMarks.map((m) => (
        <span
          key={`ch-${m.chapter}-${m.index}`}
          className="rail-tick"
          style={{ top: `${m.pct}%` }}
          aria-hidden
        />
      ))}

      {/* User highlights indicator (yellow bars) */}
      {highlightedChunks.map((h) => (
        <span
          key={`hl-${h.id}`}
          className="rail-hl"
          style={{ top: `${h.pct}%` }}
          aria-hidden
        />
      ))}

      {/* Margin gloss indicators (vermilion dots) */}
      {glossChunks.map((g) => (
        <span
          key={`gl-${g.id}`}
          className="rail-gloss"
          style={{ top: `${g.pct}%` }}
          aria-hidden
        />
      ))}

      {/* Viewport thumb rectangle */}
      <span
        className="rail-thumb"
        style={{
          top: `${thumbTop}%`,
          height: `${thumbHeight}%`,
        }}
        aria-hidden
      />

      {/* Hover Chapter Tooltip */}
      {hoveredChapter && (
        <div
          className="rail-tooltip"
          style={{
            top: Math.max(
              8,
              Math.min(
                hoveredChapter.y - 12,
                (railRef.current?.clientHeight ?? 400) - 32
              )
            ),
          }}
        >
          <span className="rail-tooltip-ch">
            {formatChapter(hoveredChapter.chapter)}
          </span>
          {hoveredChapter.heading && (
            <span className="rail-tooltip-heading">
              · {hoveredChapter.heading}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
