"use client";

import { useEffect, useRef, useState } from "react";

export type IngestPhase = "idle" | "reading" | "ingesting" | "done" | "error";

export type IngestState = {
  status: IngestPhase;
  filename?: string;
  error?: string;
  /** The engine's title for the volume, once it has read the OPF. */
  title?: string;
  /** The jacket the engine extracted, once it is on disk. */
  coverUrl?: string;
  /** Real counts from the embedding batches; absent until the first batch. */
  passages?: { done: number; total: number };
};

export function displayTitle(filename: string): string {
  const title = filename
    .replace(/\.epub$/i, "")
    .replace(/[-_]+/g, " ")
    .trim();
  return title || "Untitled volume";
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

const DIAL_RADIUS = 20;
const DIAL_LENGTH = 2 * Math.PI * DIAL_RADIUS;

/**
 * The importing book: the real jacket, dimmed, with a dial under it that
 * fills from the engine's own batch counts. No guess, no fake percentage —
 * before the first batch the dial spins instead of claiming a number.
 */
export default function IngestCard({
  state,
  onDismiss,
}: {
  state: IngestState;
  onDismiss: () => void;
}) {
  const isActive = state.status === "reading" || state.status === "ingesting";
  const isError = state.status === "error";
  const isDone = state.status === "done";
  const startedAtRef = useRef(Date.now());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (state.status === "reading" || state.status === "ingesting") {
      startedAtRef.current = Date.now();
    }
    setNow(Date.now());
  }, [state.status]);

  useEffect(() => {
    if (!isActive) return;
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(id);
  }, [isActive]);

  if (state.status === "idle" || !state.filename) return null;

  const title = state.title?.trim() || displayTitle(state.filename);
  const total = state.passages?.total ?? 0;
  const done = state.passages?.done ?? 0;
  const percent = total > 0 ? Math.min(100, Math.round((100 * done) / total)) : 0;
  const measured = total > 0;
  const elapsed = isActive
    ? Math.max(0, Math.floor((now - startedAtRef.current) / 1000))
    : 0;

  const stageText = isError
    ? state.error || "The import failed."
    : isDone
      ? "Shelved. Opening the book…"
      : state.status === "reading"
        ? `Reading the file… · ${formatElapsed(elapsed)}`
        : measured
          ? `${done} of ${total} passages · ${formatElapsed(elapsed)}`
          : `Reading the text… · ${formatElapsed(elapsed)}`;

  return (
    <article
      className={`nk-ingest${isDone ? " is-done" : ""}${isError ? " is-error" : ""}`}
      aria-busy={isActive}
    >
      <span className="nk-ingest-cover">
        {state.coverUrl ? (
          <img
            src={state.coverUrl}
            alt=""
            className="nk-ingest-cover-img"
            onError={(event) => {
              event.currentTarget.style.display = "none";
            }}
          />
        ) : null}
        <span className="nk-ingest-fallback" aria-hidden>
          <span className="nk-ingest-fallback-title">{title}</span>
        </span>
      </span>

      <span className="nk-ingest-wait">
        <span
          className={`nk-ingest-dial${isActive && !measured ? " is-spinning" : ""}`}
        >
          <svg
            viewBox="0 0 48 48"
            width="48"
            height="48"
            fill="none"
            stroke="currentColor"
            role={isActive ? "progressbar" : undefined}
            aria-valuemin={isActive ? 0 : undefined}
            aria-valuemax={isActive ? 100 : undefined}
            aria-valuenow={isActive ? percent : undefined}
            aria-label={isActive ? "Shelving progress" : undefined}
            aria-hidden={isActive ? undefined : true}
            focusable="false"
          >
            <circle
              className="nk-ingest-track"
              cx="24"
              cy="24"
              r={DIAL_RADIUS}
              strokeWidth="3"
            />
            {isActive ? (
              <circle
                className="nk-ingest-arc"
                cx="24"
                cy="24"
                r={DIAL_RADIUS}
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray={DIAL_LENGTH}
                strokeDashoffset={DIAL_LENGTH * (1 - percent / 100)}
              />
            ) : null}
            {isDone ? (
              <path className="nk-ingest-check" d="M14 24.5l7 7 13-15" strokeWidth="2.6" />
            ) : null}
            {isError ? (
              <path className="nk-ingest-alert" d="M24 14v12M24 33.5v0" strokeWidth="3" />
            ) : null}
          </svg>
          {isActive && measured ? (
            <span className="nk-ingest-percent" aria-hidden>
              {percent}
            </span>
          ) : null}
        </span>

        <span
          className="nk-ingest-stage"
          role={isError ? "alert" : "status"}
          aria-live={isError ? "assertive" : "polite"}
        >
          {stageText}
        </span>

        {isError ? (
          <button type="button" className="nk-ingest-dismiss" onClick={onDismiss}>
            Dismiss
          </button>
        ) : null}
      </span>

      <span className="nk-ingest-name" title={title}>
        {title}
      </span>
    </article>
  );
}
