import { useState, type ChangeEvent, type DragEvent } from "react";
import { importEpubBook, type BookCatalogItem } from "@/lib/engine";
import { useAsk } from "@/lib/store";

export type ImportingState = {
  status: "idle" | "reading" | "ingesting" | "done" | "error";
  filename?: string;
  error?: string;
};

export function useEpubImport() {
  const addBookToCatalog = useAsk((s) => s.addBookToCatalog);
  const openBook = useAsk((s) => s.openBook);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [importingState, setImportingState] = useState<ImportingState>({ status: "idle" });

  const handleFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".epub")) {
      setImportingState({
        status: "error",
        error: "Please select an .epub file to import into NekoHon.",
      });
      return;
    }

    setImportingState({ status: "reading", filename: file.name });
    try {
      const reader = new FileReader();
      const base64Promise = new Promise<string>((resolve, reject) => {
        reader.onload = () => {
          const res = reader.result as string;
          const comma = res.indexOf(",");
          resolve(comma >= 0 ? res.slice(comma + 1) : res);
        };
        reader.onerror = () => reject(new Error("Failed to read file"));
      });
      reader.readAsDataURL(file);
      const base64 = await base64Promise;

      setImportingState({ status: "ingesting", filename: file.name });
      const result = await importEpubBook(file.name, base64);
      if (result.ok && result.book_id) {
        const cleanTitle = file.name
          .replace(/\.epub$/i, "")
          .replace(/[-_]/g, " ")
          .trim();
        const bookToAdd: BookCatalogItem = result.book || {
          book_id: result.book_id,
          title: cleanTitle || "Imported Volume",
          author: "Local Reader Ingestion",
          chapter_count: 10,
          chunk_count: 450,
          figure_count: 15,
        };
        addBookToCatalog(bookToAdd);
        setImportingState({ status: "done", filename: file.name });
        setTimeout(() => {
          setImportingState({ status: "idle" });
          openBook(result.book_id);
        }, 600);
      } else {
        setImportingState({
          status: "error",
          error: result.error || "Engine could not parse the EPUB.",
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Import failed";
      setImportingState({ status: "error", error: msg });
    }
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingFile(true);
  };

  const onDragLeave = () => {
    setIsDraggingFile(false);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingFile(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      handleFile(file);
    }
  };

  const onFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFile(file);
    }
  };

  return {
    isDraggingFile,
    importingState,
    dismissImport: () => setImportingState({ status: "idle" }),
    onDragOver,
    onDragLeave,
    onDrop,
    onFileInputChange,
  };
}

type ImportDropProps = {
  isDraggingFile: boolean;
  importingState: ImportingState;
  onDismiss: () => void;
};

export default function ImportDrop({ isDraggingFile, importingState, onDismiss }: ImportDropProps) {
  return (
    <>
      {isDraggingFile && (
        <div className="drop-overlay">
          <div className="drop-card">
            <svg
              viewBox="0 0 24 24"
              width="44"
              height="44"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="drop-icon"
              aria-hidden
            >
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
              <path d="M12 6v6" />
              <path d="m9 9 3-3 3 3" />
            </svg>
            <div className="drop-title">Drop .epub to ingest into NekoHon</div>
            <div className="drop-sub">Local embedding and passage chunking via Ollama</div>
          </div>
        </div>
      )}

      {importingState.status !== "idle" && (
        <div className="ingest-modal">
          <div className="ingest-card">
            {importingState.status === "reading" || importingState.status === "ingesting" ? (
              <>
                <div className="ingest-spinner" aria-hidden />
                <div className="ingest-title">
                  {importingState.status === "reading"
                    ? "Reading EPUB package…"
                    : "Ingesting & embedding passages locally…"}
                </div>
                <div className="ingest-sub">{importingState.filename}</div>
              </>
            ) : importingState.status === "done" ? (
              <>
                <div className="ingest-title">Volume Shelved Successfully</div>
                <div className="ingest-sub">Opening reader view…</div>
              </>
            ) : (
              <>
                <div className="ingest-title">Ingestion Error</div>
                <div className="ingest-error-text">{importingState.error}</div>
                <button
                  type="button"
                  onClick={onDismiss}
                  className="ingest-close-btn"
                >
                  Close
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
