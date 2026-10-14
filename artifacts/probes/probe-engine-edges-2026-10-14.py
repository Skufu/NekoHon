"""Probe the three app-edge failures of 2026-10-14, plus the timeout->HTTP map.

Investigation only: imports the engine, edits nothing. Each finding reproduces
with one command; the numbers printed here are the numbers
`artifacts/engine-edges-2026-10-14.md` cites.

    python artifacts/probe-engine-edges-2026-10-14.py a   # 'hey' -> 'they'
    python artifacts/probe-engine-edges-2026-10-14.py b   # 'speed of ddr5s'
    python artifacts/probe-engine-edges-2026-10-14.py c   # 'what is'
    python artifacts/probe-engine-edges-2026-10-14.py d   # timeout -> HTTP map
    python artifacts/probe-engine-edges-2026-10-14.py all

`--answer` adds the live respond() for a/b/c (real Ollama, default model).
Embedding calls to 127.0.0.1:11434 are real; embeddings are deterministic.
Case d stubs the model call by raising the same exception shapes; it never
waits the real 120 s (answer.py:110,126 is the clock; server.py:122-124 the
catch).
"""

import argparse
import difflib
import inspect
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import answer
import canonical
import preprocess
import readings
import retrieve
from keywords import postings
from prompt import ANSWER_MODEL

FIXTURE = ROOT / "tests" / "fixtures" / "questions.json"


class ModelCalled(Exception):
    """Raised if the reading repair tries to call a model."""


def model_guard(*_args, **_kwargs):
    raise ModelCalled("model called during reading repair")


def load_index():
    return retrieve.load_index(retrieve.INDEX)


def line(text=""):
    print(text)


def show_top(index, question, k=5, label="top"):
    hits = retrieve.search(index, question, k=k)
    line(f"  {label} {question!r}:")
    for rank, hit in enumerate(hits, 1):
        text = " ".join(hit["text"].split())[:110]
        line(f"    {rank}. {hit['score']:.4f}  {hit['chunk_id']}  "
             f"ch{hit['chapter']} | {text}")
    return hits


def runner_up_word(word, vocabulary):
    """The second-best book word, for the probe's report only."""
    scores = []
    for candidate in vocabulary:
        scores.append((difflib.SequenceMatcher(None, word, candidate).ratio(),
                       candidate))
    scores.sort(reverse=True)
    return scores[1] if len(scores) > 1 else (0.0, "")


def content_words(question):
    asked = canonical.canonical_query(question)
    return asked, [w for w in preprocess.words(asked)
                   if w not in preprocess.STOPWORDS]


def case_a(index, live):
    question = "hey"
    line("CASE A  'hey' gets read as 'they'")
    asked = canonical.canonical_query(question)
    line(f"  canonical_query('hey') = {asked!r}  (opener, unchanged; canonical.py:27-31)")

    spans = list(preprocess.token_spans(question))
    line(f"  token_spans = {spans}")
    word_map = postings(index)
    df = len(word_map.get("hey", ()))
    line(f"  'hey' in word_map: {df > 0}  (df={df})")

    vocabulary = sorted(word_map)
    score, candidate, runner = readings._closest(question, vocabulary)
    rscore, rword = runner_up_word(question, vocabulary)
    line(f"  difflib _closest('hey') = score {score:.4f} candidate {candidate!r} "
         f"runner_up {runner:.4f} ({rword!r})")
    line(f"  CUTOFF = {readings.CUTOFF}  passes = {score >= readings.CUTOFF}  "
         f"unique top = {score > runner}")

    fixes = readings._fixes(question, word_map)
    line(f"  _fixes -> {fixes}")
    line(f"  resolved_reading -> {readings.resolved_reading(question, word_map)!r}")

    hits = show_top(index, question, label="literal")
    literal_top = hits[0]["score"]
    reading = readings.second_reading(index, question, literal_top, word_map=word_map)
    if reading is None:
        line("  second_reading -> None (gate rejected)")
        return
    delta = reading["chunk"]["score"] - literal_top
    line(f"  second_reading: reading {reading['reading']!r} -> "
         f"{reading['chunk']['score']:.4f} {reading['chunk']['chunk_id']} "
         f"ch{reading['chunk']['chapter']}  delta {delta:+.4f} "
         f"gate ('>' literal) = True  KEPT")
    line(f"  swaps = {reading['swaps']}")

    line("  repair source: difflib SequenceMatcher, no model. answer.py:496 runs")
    line("  second_reading first; llm_second_reading runs only when it is None.")
    context = answer.retrieval_context(index, question, generate_fn=model_guard)
    line(f"  retrieval_context with raise-on-model generate_fn completed: "
         f"asked={context['asked']!r} model calls during repair = 0")
    if live:
        body = answer.respond(index, question)
        first = body["answer"].splitlines()[0][:150]
        line(f"  live respond [{ANSWER_MODEL}]: refused={body['refused']} "
             f"citations={body['citations']}")
        line(f"    {first}")
        for extra in body["answer"].splitlines()[1:]:
            if extra.startswith("Read as:"):
                line(f"    {extra}")


def case_b(index, live):
    raw = "speed of ddr5s"
    line("CASE B  'speed of ddr5s' never gets repaired")
    asked = canonical.canonical_query(raw)
    line(f"  canonical_query({raw!r}) = {asked!r}")

    spans = list(preprocess.token_spans(asked))
    line(f"  token_spans = {spans}")
    line(f"  TOKEN pattern {preprocess.TOKEN.pattern!r}: digits are not tokens, "
         f"so 'ddr5s' splits into 'ddr' + 's'")
    word_map = postings(index)
    for _start, _end, token in spans:
        folded = token.lower()
        df = len(word_map.get(folded, ()))
        line(f"    {token!r} -> {folded!r}: in word_map={df > 0} df={df}")

    fixes = readings._fixes(asked, word_map)
    line(f"  _fixes -> {fixes}  (every query token is a book word, so no token "
         f"is even considered for repair)")
    line(f"  'ddr5' in word_map: {'ddr5' in word_map}  (book 'DDR5' also "
         f"tokenizes to 'ddr'; digits dropped on both sides)")
    s1 = difflib.SequenceMatcher(None, "ddr5s", "ddr5").ratio()
    s2 = difflib.SequenceMatcher(None, "ddr5s", "ddr").ratio()
    s3, c3, r3 = readings._closest("ddr5s", sorted(word_map))
    line(f"  counterfactual ratios: 'ddr5s'/'ddr5' = {s1:.4f} (> CUTOFF, but "
         f"'ddr5' is not in the vocabulary)")
    line(f"                         'ddr5s'/'ddr'  = {s2:.4f}")
    line(f"  _closest('ddr5s', vocab) -> {s3:.4f} {c3!r} runner_up {r3:.4f} "
         f"(below CUTOFF {readings.CUTOFF})")

    for chunk in index.get("chunks") or []:
        if "DDR5" in (chunk.get("text") or ""):
            text = " ".join(chunk["text"].split())
            at = text.index("DDR5")
            line(f"  book word exists: {chunk['chunk_id']} ch{chunk['chapter']} | "
                 f"...{text[max(0, at-70):at+90]}...")
            break

    hits = show_top(index, asked, label="literal")
    literal_top = hits[0]["score"]
    before = [t.lower() for t in preprocess.tokens(asked)]
    oov = [w for w in before if w not in word_map]
    line(f"  llm fallback gate (readings.py:160-162): tokens {before}")
    line(f"    out-of-book tokens = {oov} -> returns None before the model call "
         f"is even attempted")
    fallback = readings.llm_second_reading(index, asked, literal_top,
                                           generate_fn=model_guard, word_map=word_map)
    line(f"  llm_second_reading with raise-on-model generate_fn -> {fallback!r}")
    second = readings.second_reading(index, asked, literal_top, word_map=word_map)
    line(f"  second_reading -> {second!r}")
    line(f"  result: no repair; the model is asked the literal {asked!r}")
    if live:
        body = answer.respond(index, raw)
        first = body["answer"].splitlines()[0][:150]
        line(f"  live respond [{ANSWER_MODEL}]: refused={body['refused']} "
             f"citations={body['citations']}")
        line(f"    {first}")


def case_c(index, live):
    question = "what is"
    line("CASE C  degenerate 'what is' is answered with a random passage")
    asked = canonical.canonical_query(question)
    line(f"  canonical_query('what is') = {asked!r}  (WH regex matches 'what'; "
         f"canonical.py:48-49, unchanged)")
    words = preprocess.words(asked)
    content = [w for w in words if w not in preprocess.STOPWORDS]
    line(f"  words = {words}; stopwords = {[w for w in words if w in preprocess.STOPWORDS]}")
    line(f"  content words after stopword removal = {content}  (count {len(content)})")

    hits = show_top(index, asked, label="literal")
    word_map = postings(index)
    line(f"  word_map: " + ", ".join(
        f"{w!r} df={len(word_map.get(w, ()))}" for w in words))
    line(f"  _fixes -> {readings._fixes(asked, word_map)}  (both tokens are "
         f"book words)")
    literal_top = hits[0]["score"]
    fallback = readings.llm_second_reading(index, asked, literal_top,
                                           generate_fn=model_guard, word_map=word_map)
    line(f"  llm_second_reading with raise-on-model generate_fn -> {fallback!r}")
    line(f"  so the model receives Question: {asked!r} verbatim, with the "
         f"passages above")

    line("  degenerate rule check: content_words(canonical_query(q)) == [] -> fire")
    questions = ["what is", "hey"] + [item["q"] for item in
                                          json.loads(FIXTURE.read_text(encoding="utf-8"))[:5]]
    for q in questions:
        canon, content = content_words(q)
        line(f"    fires={not content!s:5} {q!r:55} -> asked {canon!r:60} "
             f"content {content}")
    if live:
        body = answer.respond(index, question)
        first = body["answer"].splitlines()[0][:150]
        line(f"  live respond [{ANSWER_MODEL}]: refused={body['refused']} "
             f"citations={body['citations']}")
        line(f"    {first}")


def case_d():
    line("CASE D  generation timeout -> HTTP mapping (stubbed, no 120 s wait)")
    timeout = inspect.signature(answer.ollama_generate).parameters["timeout"].default
    line(f"  answer.ollama_generate timeout default = {timeout} "
         f"(answer.py:110; urlopen at :126; no num_predict in options -> the "
         f"socket clock is the only cap)")

    import server

    server.Handler.log_message = lambda *_a, **_k: None  # quiet, runtime only
    http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    port = http.server_address[1]
    payload = json.dumps({"mode": "answer", "question": "x"}).encode("utf-8")

    shapes = [
        ("URLError(TimeoutError)  [urlopen phase]",
         urllib.error.URLError(TimeoutError("timed out"))),
        ("TimeoutError            [body read phase]", TimeoutError("timed out")),
        ("RuntimeError           [empty completion]", RuntimeError("empty completion")),
    ]
    try:
        for label, exc in shapes:
            def stub(_book, _question, _exc=exc):
                raise _exc
            server.respond = stub
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/ask", data=payload,
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    status, body = response.status, response.read().decode()
            except urllib.error.HTTPError as error:
                status, body = error.status, error.read().decode()
            line(f"  {label}: HTTP {status} {body}")
    finally:
        http.shutdown()
        http.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", nargs="?", default="all",
                        choices=("a", "b", "c", "d", "all"))
    parser.add_argument("--answer", action="store_true",
                        help="run the live respond() for a/b/c (real Ollama)")
    args = parser.parse_args()

    wanted = "abcd" if args.case == "all" else args.case
    index = load_index() if any(c in wanted for c in "abc") else None
    if "a" in wanted:
        case_a(index, args.answer)
        line()
    if "b" in wanted:
        case_b(index, args.answer)
        line()
    if "c" in wanted:
        case_c(index, args.answer)
        line()
    if "d" in wanted:
        case_d()


if __name__ == "__main__":
    main()
