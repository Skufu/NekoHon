"""Re-embed the three book indexes with embeddinggemma. Writes the index files.

Both embedders are 768-wide, and embed_index skips records whose width already
matches, so the vectors must be stripped first or nothing is re-embedded.

The nomic builds are NOT tracked by git (data/ is ignored), so switching back
means re-embedding, not checking out.

Run: python artifacts/probes/reembed-gemma-2026-10-23.py [embedder-model]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import retrieve  # noqa: E402

TARGETS = [
    (ROOT / "data" / "index.json", "fde"),
    (ROOT / "data" / "index.quantization.json", "quantization"),
    (ROOT / "data" / "index.ddia.json", "ddia"),
]
MODEL = sys.argv[1] if len(sys.argv) > 1 else retrieve.GEMMA_EMBEDDER


def slow_embed(texts, model):
    return retrieve.ollama_embed(texts, model, timeout=900)


def _jsonable(obj):
    """Derived caches attached by _prepare_index: sets and read-only maps."""
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if hasattr(obj, "items"):
        return dict(obj)
    return str(obj)


def main():
    retrieve.embed_texts(["warmup"], MODEL, slow_embed, "document")
    for path, book_id in TARGETS:
        index = json.loads(path.read_text(encoding="utf-8"))
        before = index.get("embedder")
        chunks = index.get("chunks") or []
        figures = index.get("figures") or []
        for record in chunks + figures:
            record.pop("embedding", None)
            record.pop("_uvec", None)
        index["embedder"] = MODEL
        started = time.perf_counter()
        retrieve.embed_index(index, model=MODEL, embed_fn=slow_embed)
        elapsed = time.perf_counter() - started
        # _prepare_index attaches unit vectors and book forms as private
        # underscore keys, including sets. They are derived, not stored.
        for record in chunks + figures:
            for key in [name for name in record if name.startswith("_")]:
                del record[key]
        for key in [name for name in index if name.startswith("_")]:
            del index[key]
        path.write_text(json.dumps(index, indent=2, default=_jsonable),
                        encoding="utf-8")
        print(f"{book_id:14s} {before} -> {index.get('embedder')}  "
              f"chunks {len(chunks)}  figures {len(figures)}  {elapsed:.1f}s")

    # Read back and prove the vectors are the new ones, not leftovers.
    for path, book_id in TARGETS:
        index = json.loads(path.read_text(encoding="utf-8"))
        sample = next(c for c in index["chunks"] if c.get("embedding"))
        print(f"{book_id:14s} embedder={index['embedder']!r} "
              f"dims={index.get('embedding_dims')} "
              f"first_vector={len(sample['embedding'])}")


if __name__ == "__main__":
    main()
