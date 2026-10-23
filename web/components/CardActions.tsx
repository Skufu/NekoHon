import { useAsk, type GlossItem } from "@/lib/store";

type CardActionsProps = {
  gloss: GlossItem;
  copied: boolean;
  onCopy: () => void;
  onHeightChange?: () => void;
};

export default function CardActions({ gloss, copied, onCopy, onHeightChange }: CardActionsProps) {
  const removeGloss = useAsk((s) => s.removeGloss);
  const toggleMinimizeGloss = useAsk((s) => s.toggleMinimizeGloss);
  const setGlossWidth = useAsk((s) => s.setGlossWidth);

  return (
    <div className="gloss-card-actions">
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
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onCopy();
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
  );
}
