"use client";

import { useEffect, useRef, useState } from "react";

export type IngestPhase = "idle" | "reading" | "ingesting" | "done" | "error";

export type IngestState = {
  status: IngestPhase;
  filename?: string;
  error?: string;
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

export default function IngestCard({
  state,
  onDismiss,
}: {
  state: IngestState;
  onDismiss: () => void;
}) {
  const isActive = state.status === "reading" || state.status === "ingesting";
  const startedAtRef = useRef(Date.now());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (state.status === "reading") {
      startedAtRef.current = Date.now();
      setNow(Date.now());
    }
  }, [state.status]);

  useEffect(() => {
    if (!isActive) return;
    const id = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(id);
  }, [isActive]);

  if (state.status === "idle" || !state.filename) return null;

  const isError = state.status === "error";
  const elapsed = isActive
    ? Math.max(0, Math.floor((now - startedAtRef.current) / 1000))
    : 0;

  const stageText = isError
    ? state.error || "The import failed."
    : state.status === "reading"
      ? "Reading the file…"
      : state.status === "ingesting"
        ? "Shelving…"
        : "Shelved. Opening the book…";

  return (
    <section
      className={`nk-ingest-card${state.status === "done" ? " is-done" : ""}${
        isError ? " is-error" : ""
      }`}
    >
      <span className="nk-ingest-ring" aria-hidden>
        {isActive && (
          <svg
            viewBox="0 0 28 28"
            width="28"
            height="28"
            fill="none"
            stroke="currentColor"
            className="nk-ingest-spinner"
            aria-hidden
            focusable="false"
          >
            <circle className="nk-ingest-track" cx="14" cy="14" r="11.5" strokeWidth="2" />
            <circle
              className="nk-ingest-arc"
              cx="14"
              cy="14"
              r="11.5"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray="20 53"
            />
          </svg>
        )}
        {state.status === "done" && (
          <svg
            viewBox="0 0 28 28"
            width="28"
            height="28"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="nk-ingest-check"
            aria-hidden
            focusable="false"
          >
            <path d="M7.5 14.5l4.5 4.5 8.5-10" />
          </svg>
        )}
        {isError && (
          <svg
            viewBox="0 0 28 28"
            width="28"
            height="28"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            className="nk-ingest-alert"
            aria-hidden
            focusable="false"
          >
            <circle cx="14" cy="14" r="11" />
            <path d="M14 8.5v6.5" />
            <circle cx="14" cy="19.5" r="1.1" fill="currentColor" stroke="none" />
          </svg>
        )}
      </span>
      <span className="nk-ingest-copy">
        <span className="nk-ingest-name">{displayTitle(state.filename)}</span>
        <span className="nk-ingest-line">
          <span
            className="nk-ingest-stage"
            role={isError ? "alert" : "status"}
            aria-live={isError ? "assertive" : "polite"}
            aria-atomic="true"
          >
            {stageText}
          </span>
          {isActive && (
            <span className="nk-ingest-time" aria-hidden>
              {formatElapsed(elapsed)}
            </span>
          )}
        </span>
      </span>
      {isError && (
        <button type="button" className="nk-ingest-dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      )}
    </section>
  );
}
