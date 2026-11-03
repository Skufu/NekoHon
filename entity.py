"""Who is X: the book's own sentences about that person, one per chapter.

Dense retrieval cannot answer "who is atofe". A name is not a concept, so the
top passages are wherever the name last drifted through a scene, and the model
answers from that scene ("Atofe was here. The narrator states that Atofe is
present at the scene."). The material for a profile is in the book all along:
measured 2026-11-01 on the light novel, `Atofe` appears in 51 chunks across 8
chapters, `Rudeus` in 65 across 11.

Asking the model to write the profile does not work. Measured 2026-11-01: four
prompt shapes (bullets with a trailing tag, tag-first bullets, tag-first with
an explicit rule, tag-first with an example) over `who is rudeus`. The model
wrote a wiki-style entry from its own knowledge ("a character from the epic
fantasy series The Legend of the Northern God", "master of the village of
Superd") and tagged every bullet `[Ch. 1]`, whatever passage the fact came
from. Verification kept 1 bullet of 5, and the other shapes produced no
bullets at all.

So the profile is assembled, not written: this module picks the book's own
sentences that name the person, one per chapter, best first, and the model's
only job is the closing sentence. Every quote is passage text by construction,
which is the same rule the rest of the engine holds.
"""

import re

# A name, not a question: past this many words it is a phrase to look up, and
# the normal retrieval path handles it better.
NAME_WORDS = 4
# Fewer mentions than this and there is no profile to draw.
MIN_CHUNKS = 3
PROFILE_QUOTES = 4
# Five words is enough for a line that names and says something ("Atofe's
# guard cleared the road."); the bar is that the sentence tells a reader who
# this is, not that it is long.
QUOTE_MIN_WORDS = 5
QUOTE_MAX_WORDS = 45
# One citation shows a readable sentence, not a paragraph.
QUOTE_CHARS = 240

# Only "who": "what is X" is a definition question, and the normal retrieval
# path answers it better than a profile would.
_WHO = re.compile(
    r"^\s*who(?:'s|\s+(?:is|are|was|were))\s+(.+?)\s*\?*\s*$", re.I
)
_ABOUT = re.compile(
    r"^\s*(?:tell\s+me\s+about|describe|what\s+do\s+you\s+know\s+about)\s+(.+?)\s*\?*\s*$",
    re.I,
)
# Words that are not a person or a thing: a profile of one of these is not a
# profile, and the normal path should answer it.
_NOT_A_NAME = frozenset({
    "he", "she", "it", "they", "them", "him", "her", "this", "that", "these",
    "those", "the", "a", "an", "there", "here", "you", "i", "we", "us", "me",
    "main character", "protagonist", "author", "narrator", "book", "story",
    "this person", "that person", "this character", "that character",
    "someone", "anyone", "everyone", "person", "character", "the character",
    "difference", "reason", "meaning", "point", "matter", "happen", "happened",
})
# A title or rank next to the name is what makes a sentence describe a person
# rather than mention them in passing.
_TITLE = re.compile(
    r"\b(?:Lord|Lady|Sir|King|Queen|God|Goddess|Emperor|Empress|Prince|"
    r"Princess|Captain|Master|Mistress|Saint|Demon|Immortal|Sword|North|"
    r"South|East|West|Hero|Grand|Duke|Duchess|Count|Countess|Baron|Sage|"
    r"Mage|Knight|Servant|Witch|Warrior|Chief|Elder|Priest|Priestess|"
    r"Disciple|Style)\b"
)
_TRAILING_SCOPE = re.compile(
    r"\s+(?:in\s+(?:this|the)\s+(?:book|series|story|novel|volume)|"
    r"from\s+(?:this|the)\s+(?:book|series|story|novel|volume))\s*$", re.I
)


def subject(question):
    """The name a "who is X" question asks about, or None.

    Returns the phrase as asked when it could be a name in a book; the caller
    decides whether the book knows it. Strips articles, quotes and the scope
    phrase ("in this book"), and refuses pronouns and question words.
    """
    text = (question or "").strip()
    match = _WHO.match(text) or _ABOUT.match(text)
    if match is None:
        return None
    name = match.group(1).strip()
    name = _TRAILING_SCOPE.sub("", name).strip(" .?!,;:")
    name = name.strip("\"'“”‘’")
    name = re.sub(r"^(?:the|a|an)\s+", "", name, flags=re.I).strip()
    if not name or name.lower() in _NOT_A_NAME:
        return None
    if len(name.split()) > NAME_WORDS:
        return None
    if not any(character.isalpha() for character in name):
        return None
    return name


def _sentences(text):
    flat = re.sub(r"\s+", " ", text or "")
    return [part.strip() for part in re.split(r"(?<=[.!?…])\s+", flat) if part.strip()]


# An exclamation or question thrown at the person, with the sentence that
# actually describes them after it: "Lady Atofe...!" It was Immortal Demon King
# Atofe." The fragment says nothing on its own.
_SHOUT = re.compile(r"^[\"“][^\"”]{0,60}[!?…][\"”]\s*")
# Speech followed by more speech or by narration. The splitter keeps both in
# one sentence because the closing mark is not a period; a profile shows one
# moment, so the quote ends where the speaking does.
_AFTER_SPEECH = re.compile(r"[\"”]\s*\S")


def _clean_quote(sentence, name=""):
    """One readable sentence about the person, or "" when nothing is left.

    The cut after speech happens only when the name is before it: the
    narration that follows a line of dialogue is often the part that says who
    the person is ("... because Immortal Demon King Atofe did not wait").
    """
    text = re.sub(r"\s+", " ", (sentence or "")).strip()
    text = _SHOUT.sub("", text)
    speech = _AFTER_SPEECH.search(text)
    if speech is not None:
        cut = speech.start() + 1
        named_before = bool(name) and re.search(re.escape(name), text[:cut], re.I)
        if named_before or not name:
            text = text[:cut]
    text = text.strip().strip("\"'“”‘’").strip()
    text = re.sub(r"\s+([.,!?…])", r"\1", text)
    # A line of speech that names the person is cut where the character stops
    # talking ("Atofe's guard cleared the road,"), and a comma is not an end.
    # The words are untouched; only the mark becomes a full stop.
    text = re.sub(r",+\s*[”\"]?$", ".", text)
    # Whatever speech marks survive the cut say nothing in a profile line and
    # leave orphans ("Move,” she said, ..."). The words are the book's own;
    # the marks are the app's decoration, so they go.
    # Two lines of speech run together ("... becoming a hero? Exactly!") read
    # as one speaker. The boundary between them becomes a stop.
    text = re.sub(r"[”\"]\s*[“\"]", ". ", text)
    text = re.sub(r"[“”\"]", "", text)
    # The speech boundary above can land next to the line's own stop
    # ("Kalman II.."), and no sentence carries two.
    text = re.sub(r"([.!?])[.!?]+", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > QUOTE_CHARS:
        head = text[:QUOTE_CHARS]
        cut = max(head.rfind(". "), head.rfind("? "), head.rfind("! "))
        text = (head[: cut + 1] if cut > 40 else head[: head.rfind(" ")]).strip()
    if len(text.split()) < QUOTE_MIN_WORDS:
        return ""
    # A quote that stops mid-clause ("... follower of the Dragon God,") reads
    # as a cut. Prefer the candidates that end a statement.
    if not text.endswith((".", "!", "?", "…")):
        return ""
    return text


def mentions(index, name):
    """How many chunks name this person, and in which chapters."""
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.I)
    chunks = index.get("chunks") or []
    named = [chunk for chunk in chunks if pattern.search(chunk.get("text") or "")]
    return len(named), {str(chunk.get("chapter")) for chunk in named}


def profile_sentences(index, name, limit=PROFILE_QUOTES):
    """One sentence per chapter that names the person, best first, in order.

    A sentence scores by what it tells a reader who asked who this is: a title
    or rank beside the name, the name opening the sentence, and length up to a
    point. One sentence per chapter keeps a profile from being four views of
    the same scene (measured: without the rule, three of four sentences for
    `Eris` came from one fight).
    """
    chunks = index.get("chunks") or []
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.I)
    scored = []
    for position, chunk in enumerate(chunks):
        chapter = str(chunk.get("chapter", ""))
        if not chapter.isdigit():
            # Front and back matter (ingest marks it section-NNNN) reads as an
            # index or an afterword, not as the story.
            continue
        # The chunk repeats its heading as the first line, and a heading has no
        # final period: left in, it fuses with the sentence after it ("Rudeus
        # AS I FELL, I kept my vision ...").
        text = chunk.get("text") or ""
        heading = (chunk.get("heading") or "").strip()
        if heading and text.lstrip().startswith(heading):
            text = text.lstrip()[len(heading):]
        for sentence in _sentences(text):
            if len(sentence.split()) < QUOTE_MIN_WORDS:
                continue
            if len(sentence.split()) > QUOTE_MAX_WORDS:
                continue
            if not pattern.search(sentence):
                continue
            titles = len(_TITLE.findall(sentence))
            opens = 1 if pattern.match(sentence.lstrip("\"'“”‘’- ")) else 0
            score = titles * 3 + opens * 2 + min(len(sentence.split()), 30) / 30.0
            quote = _clean_quote(sentence, name)
            if not quote or not pattern.search(quote):
                # Trimming can cut the name out ("... I surrendered the title
                # to him."), and a profile sentence that does not name the
                # person is not evidence about them.
                continue
            scored.append({
                "score": score,
                "position": position,
                "chapter": chapter,
                "chunk_id": chunk.get("chunk_id"),
                "quote": quote,
                "text": chunk.get("text") or "",
            })
    scored.sort(key=lambda item: (-item["score"], item["position"]))
    chosen = []
    used_chapters = set()
    used_positions = []
    for item in scored:
        if item["chapter"] in used_chapters:
            continue
        # Skip a chunk next to one already used *in the same chapter*: that is
        # the same scene. A neighbouring chunk in another chapter is a new
        # scene, and two lines of dialogue about one person can sit a chunk
        # apart in chapter 1 and chapter 2 of a short chapter.
        if any(
            chapter == item["chapter"] and abs(position - item["position"]) <= 1
            for position, chapter in used_positions
        ):
            continue
        chosen.append(item)
        used_chapters.add(item["chapter"])
        used_positions.append((item["position"], item["chapter"]))
        if len(chosen) >= limit:
            break
    chosen.sort(key=lambda item: item["position"])
    return chosen


# The title words a book puts in front of a name. Anything else capitalized is
# probably a sentence's first word, not a rank.
_TITLE_WORDS = frozenset(
    word for word in _TITLE.pattern.replace(r"\b(?:", "").replace(")", "").split("|")
)
_NICKNAME = re.compile(r"‘([^’]{2,40})’|'([^']{2,40})'|“([^”]{2,40})”")
# Honorifics say how someone is addressed, not who they are: "Master Rudeus"
# tells a reader nothing, "North God Sandor" and "Sword King Eris" do. A phrase
# needs at least one of the informative ranks to be worth the line.
_HONORIFICS = frozenset({"Master", "Sir", "Lady", "Lord", "Mister", "Miss", "Madam"})


def titles(sentences, name, limit=3):
    """What the book actually calls this person, verbatim.

    A generated summary is where a profile goes wrong: measured 2026-11-01,
    given four tagged sentences the model wrote "Master Rudeus is the ruler of
    the Asura Kingdom" from a passage that says the ruler is *close to* him.
    No word-overlap check catches a misread relation, so nothing is generated
    here. Every phrase below is copied out of a quote, so it cannot be false.
    """
    # The question may spell the name in lower case ("who is atofe"); the book
    # capitalizes it. Take the book's own spelling first, since the title
    # pattern is case-sensitive on purpose.
    spelling = re.search(
        re.escape(name), " ".join(item["quote"] for item in sentences), re.I
    )
    if spelling is not None:
        name = spelling.group(0)
    pattern = re.compile(
        rf"(?<![\w’'-])((?:[A-Z][\w’'-]+\s+){{1,3}}){re.escape(name)}(?:’s)?(?![\w’'-])"
    )
    found = []
    for item in sentences:
        quote = item["quote"]
        for match in pattern.finditer(quote):
            words = match.group(1).split()
            kept = []
            for word in reversed(words):
                if word in _TITLE_WORDS:
                    kept.insert(0, word)
                else:
                    break
            if not kept or all(word in _HONORIFICS for word in kept):
                continue
            phrase = " ".join(kept + [name])
            if phrase.lower() not in {seen.lower() for seen in found}:
                found.append(phrase)
        nickname = _NICKNAME.search(quote)
        if nickname and pattern.search(quote):
            epithet = next(group for group in nickname.groups() if group)
            phrase = f"{name} (“{epithet}”)"
            if phrase.lower() not in {seen.lower() for seen in found}:
                found.append(phrase)
    return found[:limit]
