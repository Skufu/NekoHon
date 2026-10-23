import { useAsk, type GlossItem } from "@/lib/store";

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

type FollowUpFormProps = {
  gloss: GlossItem;
  active: boolean;
  text: string;
  onTextChange: (text: string) => void;
};

export default function FollowUpForm({ gloss, active, text, onTextChange }: FollowUpFormProps) {
  const askFollowUp = useAsk((s) => s.askFollowUp);
  const startQuiz = useAsk((s) => s.startQuiz);
  const toggleQuizKey = useAsk((s) => s.toggleQuizKey);
  const latestTurn = gloss.turns[gloss.turns.length - 1];

  return (
    <>
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

      <form
        onSubmit={(e) => {
          e.preventDefault();
          const q = text.trim();
          if (!q) return;
          askFollowUp(gloss.id, q);
          onTextChange("");
        }}
        onClick={(e) => e.stopPropagation()}
        className="followup-form"
      >
        <input
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          placeholder="Ask a follow-up…"
          aria-label="Ask a follow-up"
          className="followup-input"
        />
        <button
          type="submit"
          disabled={!text.trim()}
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
    </>
  );
}
