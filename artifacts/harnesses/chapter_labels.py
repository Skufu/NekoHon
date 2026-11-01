"""Chapter-label keys shared by the dataset validator and the response evaluator.

A key is a string in one of three spaces:

- ``"4"``            chapter 4: ``4``, ``04``, ``Chapter 4``, ``chapter-4``,
                     ``Chapter 4. Storage``
- ``"appendix:a"``   appendix A: ``Appendix A``, ``appendix-a``,
                     ``Appendix A: Tables``
- ``"frontmatter"``  a named section, with case, spaces, and hyphens folded
                     (``Front Matter``, ``FrontMatter``, ``front-matter``)

The spaces never mix, so a ``[Ch. 4]`` tag cannot resolve a source whose
chapter is ``Appendix 4``. A structured ``Chapter``/``Appendix`` prefix drops
the body title after its designator; a bare label keeps its text, so ``4.2``
is not chapter 4. Only a tag expands a numeric range (``4-5`` names chapters 4
and 5), and only within a bounded span: a longer or descending span keys
literally instead of being enumerated.

This is tag/citation resolution only. A record's source identity still checks
``source_ref.chapter`` against the index string exactly.

Stdlib only. No book id, chapter list, or appendix letter is written here.
"""

import re

RANGE_CAP = 32

_PREFIX = re.compile(
    r"^(?P<word>chapters|chapter|ch|appendix|app)(?=$|[.:\s_#-]|\d)[.:\s_#-]*(?P<rest>.*)$",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"^0*(\d+)(?=$|[\s.:,;()\[\]/\\\-–—]+(?!\d))")
_LETTER = re.compile(r"^([a-z])(?=$|[\s.:,;()\[\]/\\\-–—]+(?!\d))", re.IGNORECASE)
_RANGE = re.compile(r"^(?:(?:chapters?|ch\.?)\s*)?0*(\d+)\s*[-–—]\s*0*(\d+)$", re.IGNORECASE)
_BARE_NUMBER = re.compile(r"^0*(\d+)$")
_BARE_LETTER = re.compile(r"^([A-Za-z])$")
_SEPARATOR = re.compile(r"[,;/]| and ", re.IGNORECASE)
_MARKER = re.compile(r"^\s*ch\.\s*", re.IGNORECASE)
_CHUNK_ID = re.compile(
    r"^(?:[A-Za-z]+\d+-\d[A-Za-z0-9-]*|[A-Za-z]+-\d+-\d[A-Za-z0-9-]*)$"
)
_FOLDED_SEPARATORS = re.compile(r"[\s_-]+")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _named(text):
    """A named label: case folded; separators dropped unless digits are present.

    A digit-bearing name keeps its separators so ``4.2`` and ``4-2`` never
    collapse into the chapter number ``42``.
    """
    folded = " ".join(str(text).strip().casefold().split())
    if any(character.isdigit() for character in folded):
        return folded
    return _FOLDED_SEPARATORS.sub("", folded)


def chapter_key(label):
    """The key for one chapter label, or ``None`` when there is no label."""
    if isinstance(label, bool):
        return None
    if isinstance(label, int):
        label = str(label)
    if not _text(label):
        return None
    text = " ".join(label.strip().split())
    prefix = _PREFIX.match(text)
    if prefix:
        word = prefix.group("word").casefold()
        rest = prefix.group("rest").strip()
        appendix = word in ("appendix", "app")
        if not rest:
            return _named(word)
        number = _NUMBER.match(rest)
        if number:
            value = str(int(number.group(1)))
            return "appendix:" + value if appendix else value
        letter = _LETTER.match(rest)
        if letter:
            return "appendix:" + letter.group(1).casefold() if appendix else letter.group(1).casefold()
        return "appendix:" + _named(rest) if appendix else _named(rest)
    number = _BARE_NUMBER.fullmatch(text)
    if number:
        return str(int(number.group(1)))
    letter = _BARE_LETTER.fullmatch(text)
    if letter:
        return letter.group(1).casefold()
    return _named(text)


def chapter_keys(label):
    """Every key a tag label names. Only an ascending numeric range expands."""
    if not _text(label):
        return set()
    text = " ".join(label.strip().split())
    span = _RANGE.fullmatch(text)
    if span:
        start, end = int(span.group(1)), int(span.group(2))
        if 0 <= end - start <= RANGE_CAP:
            return {str(number) for number in range(start, end + 1)}
    key = chapter_key(text)
    return {key} if key else set()


def tag_labels(text):
    """Split the chapter-label part of a tag into labels.

    ``Ch. 4/5`` -> ``["4", "5"]``; ``Ch. Front Matter`` -> ``["Front Matter"]``.
    """
    labels = []
    for part in _SEPARATOR.split(text or ""):
        label = _MARKER.sub("", part).strip()
        if label:
            labels.append(label)
    return labels


def chunk_tokens(text):
    """Chunk-id tokens in a tag. A label such as ``chapter-4`` is not one."""
    return [
        token
        for token in re.split(r"[\s,;]+", text or "")
        if token and _CHUNK_ID.fullmatch(token)
    ]
