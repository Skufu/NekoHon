# System map — ask-this-book, 2026-11-01

End-to-end architecture of the offline multi-volume companion stack as of 2026-11-01. Rendered visual artifacts: [system-map-2026-11-01.html](file:///Users/adriangabriellfrancisco/workspace/github.com/Skufu/ask-this-book/artifacts/reports/system-map-2026-11-01.html) and [system-map-2026-11-01.svg](file:///Users/adriangabriellfrancisco/workspace/github.com/Skufu/ask-this-book/artifacts/reports/system-map-2026-11-01.svg).

```mermaid
flowchart TD
    subgraph INGEST["1. Ingestion & Storage"]
        BOOKS["5 EPUB / PDF Books<br/>(fde, quantization, ddia, ai-engineering, ai-agents)"] -->|ingest.py| SQLITE[("SQLite FTS5 + Blobs<br/>data/index.*.sqlite<br/>(4,488 chunks)")]
        BOOKS -->|ingest.py| FIGS["data/figures/*"]
    end

    subgraph QUERY["2. Query Understanding & Guards"]
        Q(["User Question / Selection"]) --> CANON["canonical.py<br/>(Bare phrase → 'What is X?')"]
        CANON --> GUARD{"has_uncovered_subject<br/>vocabulary guard"}
        GUARD -->|Uncovered Phrase| REFUSE["Refusal:<br/>'Not in this book.'"]
        GUARD -->|Pass| PREP["preprocess.py<br/>(Tokens, NFKC fold)"]
    end

    subgraph RETRIEVAL["3. Hybrid Retrieval & Ranking"]
        PREP --> RET["retrieve.py<br/>Dense SIMD vector search<br/>(nomic-embed-text)"]
        SQLITE --> RET
        SQLITE --> FTS["fts_index.py<br/>Lexical BM25 search"]
        PREP --> FTS
        RET --> FUSE["fusion.py<br/>RRF fusion + lexical leader promotion"]
        FTS --> FUSE
        FUSE --> RANK["answer._prioritize_phrase_matches<br/>Exact phrase boost + code penalty"]
        RANK --> SHOWN["5 shown passages<br/>(+ 2-chunk follow-up window)"]
    end

    subgraph INFERENCE["4. Generation & Verification"]
        SHOWN --> GEN["Local Ollama (:11434)<br/>nekohon_q35_2b_x3_2e (Qwen3.5-2B)"]
        GEN --> PARSE["answer.py<br/>_concept_span quote expansion"]
        PARSE --> CITE_CHECK{"Citation Check<br/>Byte-exact quote + [Ch. N]"}
        CITE_CHECK -->|Verifiable Quote| ANS["Valid Answer Body<br/>[Ch. N] Citation + Gloss"]
        CITE_CHECK -->|Uncited / Fabricated| REFUSE
    end

    subgraph SERVING["5. Delivery & UI"]
        ANS --> OBSERVE["observe.py<br/>traces.jsonl logging"]
        REFUSE --> OBSERVE
        OBSERVE --> ENGINE["server.py (HTTP :8000)<br/>POST /ask, GET /chunks, stream=1"]
        FIGS --> ENGINE
        ENGINE --> UI["web/ Next.js UI (:3100)<br/>Reader pane + Ask pane + Margin cards"]
    end
```

## Active Components (2026-11-01)

| Stage | Implementation | Specification |
| --- | --- | --- |
| Storage | `store.py` / `fts_index.py` | Per-book SQLite databases (`data/index.<book>.sqlite`) with FTS5 lexical indexes and embedding vector blobs |
| Embeddings | `retrieve.py` | `nomic-embed-text` with SIMD-accelerated dot product search |
| Fusion | `fusion.py` | Reciprocal Rank Fusion with lexical top-5 promotion |
| Vocabulary Guard | `preprocess.py` | Pre-retrieval refusal for multi-word phrases absent from the book corpus |
| Answer Model | Ollama (`127.0.0.1:11434`) | `nekohon_q35_2b_x3_2e` (Qwen3.5-2B, Q4_K_M, 1.31 GB) |
| Citation Gate | `answer.py` | Verbatim quote matching against shown passages; uncited completions convert to `Not in this book.` |
| Server | `server.py` | In-process Python HTTP server on port 8000 with streaming NDJSON (`stream=1`) |
| Client | `web/` | Local Next.js 16 application with reader and margin gloss cards on port 3100 |
