"""Embed frozen chunks and search them. No chunking changes.

Stdlib only. Vectors live in the JSON index. Cosine is plain Python.
The embedder is injected so tests never call Ollama.
"""

import argparse
import json
import math
import operator
import os
import time
import urllib.request
from pathlib import Path

from engine.figures import cited_numbers, figure_cards
from engine.retrieval.preprocess import normalize

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "data" / "index.json"
OLLAMA = "http://127.0.0.1:11434/api/embed"
DEFAULT_EMBEDDER = "nomic-embed-text"
GEMMA_EMBEDDER = "embeddinggemma-2:270m-bf16-text"
TOP_K = 10
BATCH = 16

# The task prefix each model expects, written here because Ollama's Modelfile
# does not add them. Unknown models fail closed. nomic: from its model card,
# "search_document: " / "search_query: ". gemma: the Hugging Face card for
# google/embeddinggemma-2, "Task Instruction Prefixes"; it is web search, not
# question-answering, and prompt_name="Document" is only "title: none", so a
# real heading must be written into the text.
PREFIXES = {
    DEFAULT_EMBEDDER: {
        "document": "search_document: ",
        "query": "search_query: ",
    },
    GEMMA_EMBEDDER: {
        "document": "title: {title} | text: ",
        "query": "task: search result | query: ",
    },
}


if hasattr(math, "sumprod"):
    _dot = math.sumprod
else:
    def _dot(a, b):
        return sum(map(operator.mul, a, b))


def cosine(a, b):
    """Length-normalized similarity. Zero-length vectors score 0."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = _dot(a, b)
    norm_a = _dot(a, a)
    norm_b = _dot(b, b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def figure_body(figure):
    parts = [figure.get("caption") or "", figure.get("referencing_paragraph") or ""]
    return "\n".join(part for part in parts if part).strip()


def format_input(model, kind, text, title=""):
    """kind is 'document' or 'query'. Unknown models fail closed.

    The text passes through preprocess.normalize first: that is the one seam
    where the dense channel's view of a text is decided, and both sides use it.
    """
    text = normalize(text)
    prefix = PREFIXES.get(model, {}).get(kind)
    if prefix is None:
        raise SystemExit(
            f"no confirmed task prefix for {model}. "
            "Do not embed it until the prefix is checked."
        )
    return prefix.format(title=title.strip() or "none") + text


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


_EMBED_CACHE = {}
_MAX_EMBED_CACHE = 256


def ollama_embed(texts, model=DEFAULT_EMBEDDER, url=OLLAMA, timeout=120):
    cache_key = None
    if len(texts) <= 4:
        cache_key = (url, model, tuple(texts))
        if cache_key in _EMBED_CACHE:
            return [list(v) for v in _EMBED_CACHE[cache_key]]

    payload = json.dumps({
        "model": model,
        "input": texts,
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "24h"),
    }).encode("utf-8")
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

    if cache_key is not None:
        if len(_EMBED_CACHE) >= _MAX_EMBED_CACHE:
            try:
                _EMBED_CACHE.pop(next(iter(_EMBED_CACHE)))
            except Exception:
                _EMBED_CACHE.clear()
        _EMBED_CACHE[cache_key] = [list(v) for v in vectors]

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
    _prepare_index(index)
    return chunks_done, figures_done


_INDEX_CACHE = {}
_MAX_LRU = 256
_QUERY_UNIT_CACHE = {}
_RANK_CACHE = {}
_DENSE_RANK_CACHE = {}


def _lru_put(cache, key, value, max_size=_MAX_LRU):
    if len(cache) >= max_size:
        try:
            cache.pop(next(iter(cache)))
        except Exception:
            cache.clear()
    cache[key] = value


def _lru_get(cache, key):
    if key in cache:
        val = cache.pop(key)
        cache[key] = val
        return val
    return None


def _prepare_index(index):
    """Derive and attach unit vectors, postings, and book forms."""
    if not isinstance(index, dict):
        return index
    chunks = index.get("chunks") or []
    for chunk in chunks:
        vector = chunk.get("embedding")
        if vector is not None:
            c_unit = chunk.get("_uvec")
            if c_unit is None or len(c_unit) != len(vector):
                c_norm = math.sqrt(_dot(vector, vector))
                c_unit = [y / c_norm for y in vector] if c_norm > 0.0 else vector
                chunk["_uvec"] = c_unit
        if chunk.get("text") and "_cited_numbers" not in chunk:
            chunk["_cited_numbers"] = cited_numbers(chunk.get("text"))

    figures = index.get("figures") or []
    for figure in figures:
        f_vec = figure.get("embedding")
        if f_vec is not None:
            f_unit = figure.get("_uvec")
            if f_unit is None or len(f_unit) != len(f_vec):
                f_norm = math.sqrt(_dot(f_vec, f_vec))
                f_unit = [y / f_norm for y in f_vec] if f_norm > 0.0 else f_vec
                figure["_uvec"] = f_unit

    from engine.retrieval import keywords
    keywords.postings(index)
    if "_postings" in index and "_df" not in index:
        index["_df"] = {w: len(pos) for w, pos in index["_postings"].items()}

    from engine.retrieval import readings
    readings._book_forms(index)
    return index


def rank_chunks(index, question, model=DEFAULT_EMBEDDER, embed_fn=None):
    """Every chunk with a vector, best cosine first. The math search uses."""
    embed_fn = embed_fn or ollama_embed
    if index.get("embedder") != model:
        raise SystemExit(f"index was embedded with {index.get('embedder')}, not {model}")

    use_cache = (embed_fn is ollama_embed)
    norm_q = normalize(question)
    rank_key = (id(index), len(index.get("chunks", [])), model, norm_q)

    if use_cache:
        cached_rank = _lru_get(_RANK_CACHE, rank_key)
        if cached_rank is not None:
            return list(cached_rank)

    q_unit = None
    if use_cache:
        q_unit = _lru_get(_QUERY_UNIT_CACHE, (model, norm_q))

    if q_unit is None:
        query = embed_texts([question], model, embed_fn, "query")[0]
        if (
            not isinstance(query, list)
            or not query
            or any(not math.isfinite(value) for value in query)
            or all(value == 0.0 for value in query)
        ):
            raise SystemExit(
                "query embedding is empty, non-finite, or all-zero; refusing to rank."
            )
        declared = index.get("embedding_dims")
        if declared and len(query) != declared:
            raise SystemExit(
                f"query embedding is {len(query)} wide, index declares {declared}. "
                "Do not mix vectors."
            )
        q_norm = math.sqrt(_dot(query, query))
        q_unit = [x / q_norm for x in query] if q_norm > 0.0 else query
        if use_cache:
            _lru_put(_QUERY_UNIT_CACHE, (model, norm_q), q_unit)

    declared = index.get("embedding_dims")
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
        c_unit = chunk.get("_uvec")
        if c_unit is None or len(c_unit) != len(vector):
            c_norm = math.sqrt(_dot(vector, vector))
            c_unit = [y / c_norm for y in vector] if c_norm > 0.0 else vector
            chunk["_uvec"] = c_unit
        score = _dot(q_unit, c_unit)
        ranked.append((score, chunk))
    ranked.sort(key=operator.itemgetter(0), reverse=True)
    if use_cache:
        _lru_put(_RANK_CACHE, rank_key, ranked)
    return list(ranked)


def search(index, question, model=DEFAULT_EMBEDDER, embed_fn=None, k=TOP_K, return_ranks=False):
    ranked = rank_chunks(index, question, model, embed_fn)
    passages = [
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
    if return_ranks:
        ranks = {
            chunk["chunk_id"]: position
            for position, (_, chunk) in enumerate(ranked, start=1)
        }
        return passages, ranks
    return passages


def search_with_ranks(index, question, model=DEFAULT_EMBEDDER, embed_fn=None, k=TOP_K):
    return search(index, question, model=model, embed_fn=embed_fn, k=k, return_ranks=True)


def dense_rank(index, question, model=DEFAULT_EMBEDDER, embed_fn=None):
    """chunk_id -> 1-based dense rank over every chunk. No embedder: empty.

    An index with no embedder has no evidence to offer, so a caller that needs
    evidence fails closed instead of guessing.
    """
    if not index.get("embedder"):
        return {}
    use_cache = (embed_fn is None or embed_fn is ollama_embed)
    norm_q = normalize(question)
    key = (id(index), len(index.get("chunks", [])), model, norm_q)
    if use_cache:
        cached = _lru_get(_DENSE_RANK_CACHE, key)
        if cached is not None:
            return dict(cached)
    ranked = rank_chunks(index, question, model, embed_fn)
    ranks = {
        chunk["chunk_id"]: position
        for position, (_, chunk) in enumerate(ranked, start=1)
    }
    if use_cache:
        _lru_put(_DENSE_RANK_CACHE, key, ranks)
    return dict(ranks)


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
    p = Path(path).resolve()
    if p.is_file():
        stat = p.stat()
        mtime_ns = stat.st_mtime_ns
        size = stat.st_size
        cache_entry = _INDEX_CACHE.get(str(p))
        if cache_entry and cache_entry["mtime_ns"] == mtime_ns and cache_entry["size"] == size:
            return cache_entry["index"]
        data = json.loads(p.read_text(encoding="utf-8"))
        _prepare_index(data)
        _INDEX_CACHE[str(p)] = {"mtime_ns": mtime_ns, "size": size, "index": data}
        return data
    return json.loads(Path(path).read_text(encoding="utf-8"))


def warm_caches(index_path=INDEX, embedder=DEFAULT_EMBEDDER):
    """Preload index, unit vectors, postings, book forms, and primed caches."""
    p = Path(index_path).resolve()
    if p.is_file():
        return load_index(p)
    return None


def save_index(path, index):
    clean_index = dict(index)
    clean_index.pop("_book_forms", None)
    clean_index.pop("_postings", None)
    clean_index.pop("_df", None)
    clean_index.pop("_chunk_items", None)
    clean_chunks = []
    for chunk in index.get("chunks", []):
        c = dict(chunk)
        c.pop("_uvec", None)
        c.pop("_cited_numbers", None)
        clean_chunks.append(c)
    clean_index["chunks"] = clean_chunks
    clean_figures = []
    for figure in index.get("figures", []):
        f = dict(figure)
        f.pop("_uvec", None)
        clean_figures.append(f)
    clean_index["figures"] = clean_figures
    p = Path(path).resolve()
    p.write_text(json.dumps(clean_index), encoding="utf-8")
    _INDEX_CACHE.pop(str(p), None)


def chunks_payload(index):
    """The reader's view of the index: reading order, no vectors, reader-ready text.

    One block per chunk — measured 2026-10-15: no two consecutive chunks in
    this book overlap, so nothing needs merging. Every chunk text repeats its
    heading as the first line (1042/1042), so that line is dropped here and
    the heading travels as its own field; the reader renders it when it
    changes. Figures arrive as cards for the ids the chunk carries.
    """
    figures = index.get("figures") or []
    book_id = index.get("book_id") or ""
    chunks = []
    for chunk in index.get("chunks") or []:
        _, body = chunk_title(chunk)
        chunks.append({
            "chunk_id": chunk.get("chunk_id"),
            "chapter": chunk.get("chapter"),
            "heading": chunk.get("heading") or "",
            "section": chunk.get("section") or "",
            "source": chunk.get("source") or "",
            "text": body,
            "figures": figure_cards(chunk.get("figures") or [], figures, book_id=book_id),
        })
    return {
        "book_id": book_id,
        "title": index.get("title") or "",
        "author": index.get("author") or "",
        "chunks": chunks,
        "figures": figure_cards([f.get("id") for f in figures if f.get("id")], figures, book_id=book_id),
    }


def main():
    parser = argparse.ArgumentParser(description="Embed or search the frozen book index.")
    parser.add_argument("--index", default=str(INDEX))
    parser.add_argument(
        "--book-id",
        default=None,
        help="Book ID; resolves index to data/index.<book_id>.json if --index is not set and data/index.<book_id>.json exists, else data/index.json",
    )
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    parser.add_argument("--smoke", default="")
    parser.add_argument("--k", type=int, default=TOP_K)
    args = parser.parse_args()

    if args.book_id is not None and args.index == str(INDEX):
        book_index = ROOT / "data" / f"index.{args.book_id}.json"
        if book_index.exists():
            index_path = book_index
        else:
            index_path = INDEX
    else:
        index_path = Path(args.index)

    if args.embedder != DEFAULT_EMBEDDER and index_path.resolve() == INDEX.resolve():
        raise SystemExit(
            f"{args.embedder} must not write data/index.json. "
            "Pass --index data/index.<model>.json."
        )
    if not index_path.is_file():
        if not args.smoke and INDEX.is_file() and index_path != INDEX and args.book_id is None:
            base = load_index(INDEX)
            if base.get("embedder") not in (None, args.embedder):
                for record in base.get("chunks", []) + base.get("figures", []):
                    record.pop("embedding", None)
                base.pop("embedder", None)
                base.pop("embedding_dims", None)
            save_index(index_path, base)
            print(f"copied frozen chunks to {index_path.name}")
        else:
            if args.book_id is not None:
                raise FileNotFoundError(
                    f"missing index: {index_path}. "
                    f"Run 'python3 -m engine.ingest --epub books/{args.book_id}.epub --book-id {args.book_id}' first."
                )
            raise SystemExit(f"missing index: {index_path}")
    index = load_index(index_path)
    if args.book_id is not None:
        idx_book = index.get("book_id")
        if idx_book and idx_book != args.book_id:
            raise FileNotFoundError(
                f"Index {index_path} has book_id '{idx_book}', expected '{args.book_id}'. "
                f"Run 'python3 -m engine.ingest --epub books/{args.book_id}.epub --book-id {args.book_id}' first."
            )
        if not idx_book:
            index["book_id"] = args.book_id
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
