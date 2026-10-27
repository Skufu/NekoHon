"""Track A of the verifier testbed: re-apply six real shipped defects, one per tree.

Each defect is the inverse of a fix that actually landed:

1. our 3706e22 — prior-quote lookup matched raw text (CRLF in the index)
2. our 3706e22 — attribution guard in ask but not respond
3. our 3706e22 — four plain-register cues missing
4. their 90626cc — import accepted any path
5. their 90626cc — LRU cache race
6. their 90626cc — no cache clear after import

Bias control: nothing here is invented for the test; each block is the exact
pre-fix text, recovered from the commit that changed it.

Usage: python artifacts/probes/track-a-apply-2026-10-25.py
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACK = ROOT / ".delta" / "track-a"

DEFECTS = {
    "d1": {
        "file": "answer.py",
        "old": """    snippet = re.sub(r"\\s+", " ", quote or "").strip().lower()[:50]
    if not snippet:
        return None

    def carries(text):
        return snippet in re.sub(r"\\s+", " ", text or "").lower()""",
        "new": """    snippet = (quote or "").strip().lower()[:50]
    if not snippet:
        return None

    def carries(text):
        return snippet in (text or "").lower()""",
    },
    "d2": {
        "file": "answer.py",
        "old": """    if names_absent_person(index, question):
        return _refusal([])
    anchors = anchor_words(asked_form, context["word_map"])""",
        "new": """    anchors = anchor_words(asked_form, context["word_map"])""",
    },
    "d3": {
        "file": "answer.py",
        "old": """    "plainer words",
    "for a beginner",""",
        "new": """    "for a beginner",""",
    },
    "d4": {
        "file": "engine/server.py",
        "old": """        if not epub_path.is_relative_to((ROOT / "books").resolve()):
            return None, None, "epub_path must be under books/"
""",
        "new": "",
    },
    "d5": {
        "file": "engine/retrieval/retrieve.py",
        "old": """    val = cache.pop(key, None)
    if val is not None:
        cache[key] = val
    return val""",
        "new": """    if key in cache:
        val = cache.pop(key)
        cache[key] = val
        return val
    return None""",
    },
    "d6": {
        "file": "engine/server.py",
        "old": """    INDEX_CACHE[book_id] = index
    retrieve_mod.clear_index_caches()
    readings.clear_wmap_cache()""",
        "new": """    INDEX_CACHE[book_id] = index
    readings.clear_wmap_cache()""",
    },
    "baseline": {
        "file": "answer.py",
        "old": """    def carries(text):
        return snippet in re.sub(r"\\s+", " ", text or "").lower()

    for i, chunk in enumerate(chunks):
        if str(chunk.get("chapter")) == str(chapter) and carries(chunk.get("text")):
            return i
    for i, chunk in enumerate(chunks):
        if carries(chunk.get("text")):
            return i""",
        "new": """    def contains_snippet(text):
        return snippet in re.sub(r"\\s+", " ", text or "").lower()

    for i, chunk in enumerate(chunks):
        if str(chunk.get("chapter")) == str(chapter) and contains_snippet(chunk.get("text")):
            return i
    for i, chunk in enumerate(chunks):
        if contains_snippet(chunk.get("text")):
            return i""",
    },
}


def main():
    failures = []
    for name, spec in DEFECTS.items():
        path = TRACK / name / spec["file"]
        if not path.is_file():
            failures.append(f"{name}: missing {path}")
            continue
        text = path.read_text(encoding="utf-8")
        count = text.count(spec["old"])
        if count != 1:
            failures.append(f"{name}: expected 1 match in {spec['file']}, found {count}")
            continue
        path.write_text(text.replace(spec["old"], spec["new"]), encoding="utf-8")
        print(f"{name}: applied to {spec['file']}")
    if failures:
        print("FAILED")
        for failure in failures:
            print(" ", failure)
        raise SystemExit(1)
    print("all defects applied")


if __name__ == "__main__":
    main()
