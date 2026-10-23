import AnswerView from "@/components/AnswerView";
import { formatChapter } from "@/lib/anchor";
import { useAsk, type GlossItem } from "@/lib/store";

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

type TurnViewProps = {
  gloss: GlossItem;
  idx: number;
  expanded: boolean;
  onSetExpanded: (key: string, value: boolean) => void;
  onHeightChange?: () => void;
};

export default function TurnView({ gloss, idx, expanded, onSetExpanded, onHeightChange }: TurnViewProps) {
  const showCitation = useAsk((s) => s.showCitation);
  const stopGloss = useAsk((s) => s.stopGloss);
  const toggleQuizKey = useAsk((s) => s.toggleQuizKey);
  const removeTurn = useAsk((s) => s.removeTurn);

  const turn = gloss.turns[idx];
  const isLatest = idx === gloss.turns.length - 1;
  const isCollapsible = gloss.turns.length > 1 && !isLatest;
  const isExpanded = isLatest || expanded;
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
    <div className="turn-container">
      {isCollapsible ? (
        <div className="turn-accordion-header">
          <button
            type="button"
            className={`turn-accordion-btn ${isExpanded ? "is-expanded" : ""}`}
            onClick={(e) => {
              e.stopPropagation();
              onSetExpanded(turn.id || String(idx), !isExpanded);
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
          {isLatest &&
            turn.question &&
            turn.question !== gloss.quote &&
            !(turn.mode === "quiz" && turn.question === "Quiz") && (
              <p className="turn-question">
                {turn.question}
              </p>
            )}
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
          {turn.status === "error" && (
            <p className="turn-error">
              {turn.error || "Engine error occurred."}
            </p>
          )}
          {turn.status === "stopped" && (
            <p className="turn-stopped">
              Stopped — this is a partial answer.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
