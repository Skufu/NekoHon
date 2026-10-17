"use client";

import { useEffect, useState } from "react";
import Reader from "@/components/Reader";
import { fetchChunks, type ChunksPayload } from "@/lib/engine";
import { useAsk } from "@/lib/store";

export default function Page() {
  const [payload, setPayload] = useState<ChunksPayload | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    useAsk.getState().hydrateStore();
  }, []);

  useEffect(() => {
    fetchChunks()
      .then(setPayload)
      .catch((error: unknown) => {
        const detail = error instanceof Error ? error.message : "unknown error";
        setLoadError(
          `Could not load the book: ${detail} — is the engine running on :8000?`
        );
      });
  }, []);

  return <Reader payload={payload} loadError={loadError} />;
}
