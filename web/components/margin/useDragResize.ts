import { useRef, useState, type MutableRefObject, type PointerEvent } from "react";
import { useAsk, type GlossItem } from "@/lib/store";

export type ResizeEdge = "left" | "bottom" | "top" | "corner";
type Mode = "drag" | ResizeEdge;

const MIN_W = 280;
const MAX_W = 540;
const MIN_H = 200;
const MAX_H = 720;
const DEFAULT_W = 320;
const DEFAULT_H = 320;

const changesWidth = (m: Mode) => m === "left" || m === "corner";
const changesHeight = (m: Mode) => m === "bottom" || m === "top" || m === "corner";
const movesCard = (m: Mode) => m === "drag" || m === "top";

type Params = {
  gloss: GlossItem;
  top: number;
  articleRef: MutableRefObject<HTMLElement | null>;
  onHeightChange?: () => void;
};

export function useDragResize({ gloss, top, articleRef, onHeightChange }: Params) {
  const setGlossDragOffset = useAsk((s) => s.setGlossDragOffset);
  const setGlossWidth = useAsk((s) => s.setGlossWidth);
  const setGlossHeight = useAsk((s) => s.setGlossHeight);

  const [isInteracting, setIsInteracting] = useState(false);
  const modeRef = useRef<Mode | null>(null);
  const startRef = useRef({ clientX: 0, clientY: 0, dragX: 0, dragY: 0, width: DEFAULT_W, height: DEFAULT_H });

  const dragX = gloss.dragOffset?.x ?? 0;
  const dragY = gloss.dragOffset?.y ?? 0;

  const liveDragRef = useRef({ x: dragX, y: dragY });
  const liveWidthRef = useRef<number | undefined>(gloss.customWidth);
  const liveHeightRef = useRef<number | undefined>(gloss.customHeight);
  const rafRef = useRef(0);

  if (!modeRef.current) {
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

  const syncLeader = () =>
    updateLeaderLineDOM(liveDragRef.current.x, liveDragRef.current.y, liveWidthRef.current);

  const applyTransform = (el: HTMLElement) => {
    const { x, y } = liveDragRef.current;
    el.style.transform =
      x !== 0 || y !== 0
        ? `translate3d(${x}px, ${Math.round(top + y)}px, 0)`
        : `translateY(${Math.round(top)}px)`;
  };

  const resetPosition = () => {
    liveDragRef.current = { x: 0, y: 0 };
    if (articleRef.current) {
      articleRef.current.style.transform = `translateY(${Math.round(top)}px)`;
    }
    updateLeaderLineDOM(0, 0, liveWidthRef.current);
    setGlossDragOffset(gloss.id, { x: 0, y: 0 });
  };

  const begin = (mode: Mode, e: PointerEvent<HTMLElement>) => {
    modeRef.current = mode;
    setIsInteracting(true);
    const width = gloss.customWidth ?? DEFAULT_W;
    let height = gloss.customHeight ?? DEFAULT_H;
    if (changesHeight(mode)) {
      const cardEl = articleRef.current || (e.currentTarget.closest(".gloss-card") as HTMLElement | null);
      const turnsEl = cardEl?.querySelector<HTMLElement>(".gloss-turns");
      height = gloss.customHeight ?? (turnsEl?.offsetHeight || DEFAULT_H);
      liveHeightRef.current = height;
    }
    if (changesWidth(mode)) liveWidthRef.current = width;
    startRef.current = {
      clientX: e.clientX,
      clientY: e.clientY,
      dragX: liveDragRef.current.x,
      dragY: liveDragRef.current.y,
      width,
      height,
    };
  };

  const startDrag = (e: PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, a, input")) return;
    e.preventDefault();
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {}
    begin("drag", e);
  };

  const startResize = (edge: ResizeEdge, e: PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    begin(edge, e);
  };

  const onMove = (mode: Mode, e: PointerEvent<HTMLElement>) => {
    if (modeRef.current !== mode) return;
    const s = startRef.current;
    if (mode === "drag") {
      liveDragRef.current = {
        x: Math.round(s.dragX + (e.clientX - s.clientX)),
        y: Math.round(s.dragY + (e.clientY - s.clientY)),
      };
    }
    if (changesWidth(mode)) {
      const delta = s.clientX - e.clientX;
      liveWidthRef.current = Math.max(MIN_W, Math.min(MAX_W, Math.round(s.width + delta)));
    }
    if (changesHeight(mode)) {
      const delta = mode === "top" ? s.clientY - e.clientY : e.clientY - s.clientY;
      const nextHeight = Math.max(MIN_H, Math.min(MAX_H, Math.round(s.height + delta)));
      liveHeightRef.current = nextHeight;
      if (mode === "top") {
        liveDragRef.current = {
          x: liveDragRef.current.x,
          y: Math.round(s.dragY - (nextHeight - s.height)),
        };
      }
    }
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      const el = articleRef.current;
      if (el) {
        if (changesWidth(mode)) {
          el.style.width = `${liveWidthRef.current}px`;
          el.style.left = "auto";
          el.style.right = "0px";
        }
        if (changesHeight(mode)) {
          const turnsEl = el.querySelector<HTMLElement>(".gloss-turns");
          if (turnsEl) {
            turnsEl.style.maxHeight = `${liveHeightRef.current}px`;
            turnsEl.style.overflowY = "auto";
          }
        }
        if (movesCard(mode)) applyTransform(el);
      }
      if (mode !== "bottom") syncLeader();
    });
  };

  const onUp = (mode: Mode, e: PointerEvent<HTMLElement>) => {
    if (modeRef.current !== mode) return;
    modeRef.current = null;
    setIsInteracting(false);
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    if (changesWidth(mode) && liveWidthRef.current !== undefined) {
      setGlossWidth(gloss.id, liveWidthRef.current);
    }
    if (changesHeight(mode) && liveHeightRef.current !== undefined) {
      setGlossHeight(gloss.id, liveHeightRef.current);
    }
    if (movesCard(mode)) setGlossDragOffset(gloss.id, liveDragRef.current);
    if (mode !== "bottom") syncLeader();
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {}
    if (mode !== "drag") onHeightChange?.();
  };

  const dragHandlers = {
    onPointerDown: startDrag,
    onPointerMove: (e: PointerEvent<HTMLElement>) => onMove("drag", e),
    onPointerUp: (e: PointerEvent<HTMLElement>) => onUp("drag", e),
  };

  const resizeHandlers = (edge: ResizeEdge) => ({
    onPointerDown: (e: PointerEvent<HTMLElement>) => startResize(edge, e),
    onPointerMove: (e: PointerEvent<HTMLElement>) => onMove(edge, e),
    onPointerUp: (e: PointerEvent<HTMLElement>) => onUp(edge, e),
  });

  return { isInteracting, dragX, dragY, dragHandlers, resizeHandlers, resetPosition };
}
