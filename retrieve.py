"""Embed frozen chunks and search them. Phase 3. No chunking changes.

Stdlib only. Vectors live in the JSON index. Cosine is plain Python.
The embedder is injected so tests never call Ollama.
"""

import argparse
import json
import math
import time
import urllib.request
from pathlib import Path

from preprocess import normalize

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "data" / "index.json"
OLLAMA = "http://127.0.0.1:11434/api/embed"
DEFAULT_EMBEDDER = "nomic-embed-text"
GEMMA_EMBEDDER = "embeddinggemma-2:270m-bf16-text"
TOP_K = 10
BATCH = 16

# nomic was trained with these. Ollama's Modelfile does not add them.
NOMIC_DOCUMENT = "search_document: "
NOMIC_QUERY = "search_query: "

# Hugging Face card for google/embeddinggemma-2, "Task Instruction Prefixes".
# Web search, not question-answering: these questions retrieve a passage.
# prompt_name="Document" is only "title: none". A real heading must be written in.
GEMMA_QUERY = "task: search result | query: "
GEMMA_TITLE = "title: {title} | text: "


def cosine(a, b):
    """Length-normalized similarity. Zero-length vectors score 0."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def chunk_body(chunk):
    """Heading is already the first line of text. Do not add it twice."""
    return chunk.get("text") or ""


def figure_body(figure):
    parts = [figure.get("caption") or "", figure.get("referencing_paragraph") or ""]
    return "\n".join(part for part in parts if part).strip()


def format_input(model, kind, text, title=""):
    """kind is 'document' or 'query'. Unknown models fail closed.

    Confirmed 2026-10-11 from the Hugging Face card, not guessed. The text
    passes through preprocess.normalize first: that is the one seam where the
    dense channel's view of a text is decided, and both sides use it.
    """
    text = normalize(text)
    if model == DEFAULT_EMBEDDER:
        prefix = NOMIC_DOCUMENT if kind == "document" else NOMIC_QUERY
        return prefix + text
    if model == GEMMA_EMBEDDER:
        if kind == "query":
            return GEMMA_QUERY + text
        shown = title.strip() or "none"
        return GEMMA_TITLE.format(title=shown) + text
    raise SystemExit(
        f"no confirmed task prefix for {model}. "
        "Do not embed it until the prefix is checked."
    )


def chunk_title(chunk):
    heading = (chunk.get("heading") or "").strip()
    text = chunk.get("text") or ""
    if heading and text.startswith(heading):
        body = text[len(heading):].lstrip("\n").strip()
        return heading, body or text
    return "", text


def document_input(model, record, kind):
    """kind is 'chunk' or 'figure'."""
    if kind == "chunk":
        title, body = chunk_title(record)
        if model == DEFAULT_EMBEDDER:
            return format_input(model, "document", record.get("text") or "")
        return format_input(model, "document", body, title)
    caption = (record.get("caption") or "").strip()
    cite = (record.get("referencing_paragraph") or "").strip()
    if model == DEFAULT_EMBEDDER:
        return format_input(model, "document", figure_body(record))
    if cite:
        return format_input(model, "document", cite, caption)
    return format_input(model, "document", caption, "")


def ollama_embed(texts, model=DEFAULT_EMBEDDER, url=OLLAMA, timeout=120):
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    vectors = body.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError(f"bad embed response for {model}")
    return vectors


def embed_texts(texts, model, embed_fn, kind, title=""):
    formatted = [format_input(model, kind, text, title) for text in texts]
    return embed_fn(formatted, model)


def _needs_vector(record, dims):
    vector = record.get("embedding")
    return not isinstance(vector, list) or len(vector) != dims


def _vector_problem(vector, width):
    """Reason a response vector must not be stored, or None when it may."""
    if not isinstance(vector, list) or len(vector) != width:
        got = len(vector) if isinstance(vector, list) else "not a list"
        return f"width {got}, expected {width}"
    if not all(math.isfinite(value) for value in vector):
        return "non-finite value"
    if all(value == 0.0 for value in vector):
        return "all-zero vector"
    return None


def embed_index(index, model=DEFAULT_EMBEDDER, embed_fn=None, batch=BATCH, dims=None):
    """Add vectors to chunks and figures. Skip records that already match."""
    embed_fn = embed_fn or ollama_embed
    if dims:
        width = dims
    else:
        probe = embed_texts(["probe"], model, embed_fn, "document")
        width = len(probe[0])
    if index.get("embedder") not in (None, model):
        raise SystemExit(
            f"index embedder is {index.get('embedder')}, not {model}. "
            "Write a new file. Do not mix vectors."
        )

    def fill(records, kind):
        pending = []
        for record in records:
            text = document_input(model, record, kind)
            if not text or text.endswith("text: ") or text.endswith("search_document: "):
                record.pop("embedding", None)
                continue
            if _needs_vector(record, width):
                pending.append((record, text))
        for start in range(0, len(pending), batch):
            group = pending[start:start + batch]
            vectors = embed_fn([text for _, text in group], model)
            if not isinstance(vectors, list) or len(vectors) != len(group):
                got = len(vectors) if isinstance(vectors, list) else "no"
                raise SystemExit(
                    f"embedder returned {got} vectors for {len(group)} texts; "
                    "refusing to store the batch."
                )
            for (record, _), vector in zip(group, vectors):
                name = record.get("chunk_id") if kind == "chunk" else record.get("id")
                problem = _vector_problem(vector, width)
                if problem:
                    raise SystemExit(
                        f"{kind} {name}: embedding is {problem}; refusing to store it."
                    )
                record["embedding"] = [round(value, 6) for value in vector]
            yield len(group)

    chunks_done = 0
    figures_done = 0
    for count in fill(index.get("chunks", []), "chunk"):
        chunks_done += count
    for count in fill(index.get("figures", []), "figure"):
        figures_done += count
    index["embedder"] = model
    index["embedding_dims"] = width
    return chunks_done, figures_done


def rank_chunks(index, question, model=DEFAULT_EMBEDDER, embed_fn=None):
    """Every chunk with a vector, best cosine first. The math search uses."""
    embed_fn = embed_fn or ollama_embed
    if index.get("embedder") != model:
        raise SystemExit(f"index was embedded with {index.get('embedder')}, not {model}")
    query = embed_texts([question], model, embed_fn, "query")[0]
    if not isinstance(query, list) or not query or any(
        not math.isfinite(value) for value in query
    ):
        raise SystemExit("query embedding is empty or non-finite; refusing to rank.")
    declared = index.get("embedding_dims")
    if declared and len(query) != declared:
        raise SystemExit(
            f"query embedding is {len(query)} wide, index declares {declared}. "
            "Do not mix vectors."
        )
    ranked = []
    for chunk in index.get("chunks", []):
        vector = chunk.get("embedding")
        if vector is None:
            continue
        if declared and len(vector) != declared:
            raise SystemExit(
                f"chunk {chunk.get('chunk_id')}: vector is {len(vector)} wide, "
                f"index declares {declared}. Re-embed or repair the index."
            )
        ranked.append((cosine(query, vector), chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def search(index, question, model=DEFAULT_EMBEDDER, embed_fn=None, k=TOP_K):
    ranked = rank_chunks(index, question, model, embed_fn)
    return [
        {
            "score": score,
            "chunk_id": chunk["chunk_id"],
            "chapter": chunk["chapter"],
            "heading": chunk.get("heading", ""),
            "text": chunk.get("text", ""),
            "source": chunk.get("source", ""),
        }
        for score, chunk in ranked[:k]
    ]


def dense_rank(index, question, model=DEFAULT_EMBEDDER, embed_fn=None):
    """chunk_id -> 1-based dense rank over every chunk. No embedder: empty.

    An index with no embedder has no evidence to offer, so a caller that needs
    evidence fails closed instead of guessing.
    """
    if not index.get("embedder"):
        return {}
    ranked = rank_chunks(index, question, model, embed_fn)
    return {
        chunk["chunk_id"]: position
        for position, (_, chunk) in enumerate(ranked, start=1)
    }


def smoke(index, questions, model=DEFAULT_EMBEDDER, embed_fn=None, k=TOP_K):
    """A hit is the right chapter in the top k, and the phrase is in that chunk."""
    hits = 0
    lines = []
    for item in questions:
        found = search(index, item["q"], model, embed_fn, k)
        match = None
        for rank, hit in enumerate(found, start=1):
            chapter_ok = str(hit["chapter"]) == str(item["chapter"])
            phrase_ok = item["must_contain"].lower() in hit["text"].lower()
            if chapter_ok and phrase_ok:
                match = rank
                break
        if match:
            hits += 1
            lines.append(f"hit rank {match} ch {item['chapter']} {item['q']}")
        else:
            top = found[0]["chapter"] if found else "-"
            lines.append(f"miss top ch {top} wanted {item['chapter']} {item['q']}")
    return hits, len(questions), lines


def load_index(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_index(path, index):
    Path(path).write_text(json.dumps(index), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Embed or search the frozen book index.")
    parser.add_argument("--index", default=str(INDEX))
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    parser.add_argument("--smoke", default="")
    parser.add_argument("--k", type=int, default=TOP_K)
    args = parser.parse_args()
    index_path = Path(args.index)
    if args.embedder != DEFAULT_EMBEDDER and index_path.resolve() == INDEX.resolve():
        raise SystemExit(
            f"{args.embedder} must not write data/index.json. "
            "Pass --index data/index.<model>.json."
        )
    if not index_path.is_file():
        if not args.smoke and INDEX.is_file():
            base = load_index(INDEX)
            if base.get("embedder") not in (None, args.embedder):
                for record in base.get("chunks", []) + base.get("figures", []):
                    record.pop("embedding", None)
                base.pop("embedder", None)
                base.pop("embedding_dims", None)
            save_index(index_path, base)
            print(f"copied frozen chunks to {index_path.name}")
        else:
            raise SystemExit(f"missing index: {index_path}")
    index = load_index(index_path)
    if args.smoke:
        question_path = Path(args.smoke)
        if not question_path.is_file():
            raise SystemExit(f"missing questions: {question_path}")
        questions = json.loads(question_path.read_text(encoding="utf-8"))
        started = time.perf_counter()
        hits, total, lines = smoke(index, questions, args.embedder, k=args.k)
        elapsed = time.perf_counter() - started
        for line in lines:
            print(line)
        print(f"hits {hits}/{total} top-{args.k} seconds {elapsed:.1f}")
        return
    started = time.perf_counter()
    chunks_done, figures_done = embed_index(index, args.embedder)
    save_index(index_path, index)
    elapsed = time.perf_counter() - started
    print(f"embedder {args.embedder}")
    print(f"chunks embedded {chunks_done}")
    print(f"figures embedded {figures_done}")
    print(f"index bytes {index_path.stat().st_size}")
    print(f"seconds {elapsed:.1f}")


if __name__ == "__main__":
    main()
