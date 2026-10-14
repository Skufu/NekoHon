"""Stage 5-9 probes: stemmer behavior, stop words, fold, real-index word map.

Run:  python artifacts/probes/probe-stages.py
Offline. Reads data/index.json read-only; never writes anything.
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "probes"))

from preprocess import STOPWORDS, fold, stem, stemmed_words, words  # noqa: E402

INDEX_PATH = ROOT / "data" / "index.json"


def main():
    print("== (a) stemming: the standard Snowball (Porter2) stemmer ==")
    for word in ("extracted", "extract", "extracting"):
        print(f"   stem({word!r}) = {stem(word)!r}")
    print("   published Porter2 example families:")
    for word, expected in (
        ("consigned", "consign"),
        ("consigning", "consign"),
        ("consignment", "consign"),
        ("relational", "relat"),
        ("generously", "generous"),
        ("ties", "tie"),
        ("tied", "tie"),
        ("tying", "tie"),
        ("skies", "sky"),
        ("skis", "ski"),
        ("news", "news"),
        ("dying", "die"),
    ):
        got = stem(word)
        flag = "ok" if got == expected else "MISMATCH"
        print(f"   {word:12s} -> {got:12s} ({flag})")
    probes = (
        "extracted", "relational", "generously", "skies", "news",
        "storage", "storing", "streaming", "consignment",
    )
    print(
        "   idempotent on all probe words (stem(stem(w)) == stem(w)): "
        f"{all(stem(stem(w)) == stem(w) for w in probes)}"
    )
    print("   book-relevant families collapse too:")
    for family in (
        ("ingest", "ingesting", "ingested", "ingestion"),
        ("transform", "transforming", "transformed", "transformation"),
        ("stream", "streaming", "streamed", "streams"),
    ):
        collapsed = {stem(w) for w in family}
        print(f"   {'/'.join(family)} -> {collapsed}")

    print()
    print("== (b) stop words: the SMART list ==")
    print(f"   STOPWORDS: {len(STOPWORDS)} words (vendor/stopwords-en.txt)")
    for word in ("actually", "the", "what", "would", "extract", "watermark", "data"):
        print(f"   {word:10s} in STOPWORDS: {word in STOPWORDS}")

    print()
    print("== (4) fold: NFKC + typographic punctuation to ASCII ==")
    curly = "the book’s “ﬁle” — done"
    straight = 'the book\'s "file" - done'
    print(f"   {curly!r} -> {fold(curly)!r}")
    print(f"   equals the straight-ASCII form: {fold(curly) == straight}")
    print(f"   fold is idempotent: {fold(fold(curly)) == fold(curly)}")

    print()
    print("== (c) real index: raw word map vs stemmed word map ==")
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    chunks = index.get("chunks") or []
    print(f"   {INDEX_PATH.name}: {len(chunks)} chunks")

    def df_map(view):
        table = {}
        for position, chunk in enumerate(chunks):
            for word in set(view(chunk.get("text") or "")):
                if word in STOPWORDS:
                    continue
                table.setdefault(word, set()).add(position)
        return table

    start = time.perf_counter()
    raw = df_map(words)
    raw_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    stemmed = df_map(stemmed_words)
    stem_ms = (time.perf_counter() - start) * 1000
    print(f"   content-word keys: raw {len(raw)}, stemmed {len(stemmed)}")
    print(f"   map build: raw {raw_ms:.0f} ms, stemmed {stem_ms:.0f} ms")

    family = ("extract", "extracted", "extracting", "extraction")
    print("   document frequencies BEFORE stemming, one entry per surface form:")
    for word in family:
        print(f"     df({word!r}) = {len(raw.get(word, ()))}")
    union = set().union(*(raw.get(word, set()) for word in family))
    print("   AFTER stemming, one entry for the family:")
    print(f"     df({stem('extract')!r}) = {len(stemmed.get('extract', ()))}")
    print(f"     stemmed set == raw family union: {stemmed.get('extract', set()) == union}")
    sample = sorted(chunks[position].get("chunk_id", "?") for position in union)[:6]
    print(f"     example chunks in the family: {', '.join(sample)}")
    raw_forms = [form for form in ("watermark", "watermarks") if form in raw]
    print(
        "   control: 'watermark' is not a stopword and stems to itself; "
        f"raw df(watermark)={len(raw.get('watermark', ()))}, "
        f"df(watermarks)={len(raw.get('watermarks', ()))} -> "
        f"stemmed df(watermark)={len(stemmed.get('watermark', ()))} "
        f"(surface forms {raw_forms} merged, none swallowed)"
    )

    question = "how is data extracted"
    raw_terms = {w for w in words(question) if w not in STOPWORDS}
    stemmed_terms = {w for w in stemmed_words(question) if w not in STOPWORDS}
    print(f"   question {question!r}")
    for term in sorted(raw_terms):
        print(f"     raw term df({term!r}) = {len(raw.get(term, ()))}")
    for term in sorted(stemmed_terms):
        print(f"     stemmed term df({term!r}) = {len(stemmed.get(term, ()))}")

    all_tokens = [w for chunk in chunks for w in words(chunk.get("text") or "")]
    start = time.perf_counter()
    stems = [stem(w) for w in all_tokens]
    seconds = time.perf_counter() - start
    print(
        f"   stem throughput: {len(stems)} tokens in {seconds * 1000:.0f} ms "
        f"({len(stems) / seconds:,.0f} tokens/s)"
    )
    unique = sorted(set(all_tokens))
    start = time.perf_counter()
    for word in unique:
        stem(word)
    seconds = time.perf_counter() - start
    print(
        f"   stem only the {len(unique)} unique keys: {seconds * 1000:.0f} ms "
        "(the map-build cost that matters; cache it once per process)"
    )


if __name__ == "__main__":
    main()
