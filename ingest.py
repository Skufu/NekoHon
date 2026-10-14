"""EPUB -> data/index.json + data/figures/. No vectors, no Ollama.

Stdlib only. Records are JSON. Pictures stay files. No pickle.
"""

import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from figures import cited_numbers

ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "books" / "fde.epub"
INDEX = ROOT / "data" / "index.json"
FIGURES = ROOT / "data" / "figures"

CHUNK_MAX_CHARS = 1400
CHUNK_OVERLAP_CHARS = 180

OPF = "{http://www.idpf.org/2007/opf}"
CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"

SKIP_TAGS = {"script", "style", "head"}
HEADING_TAGS = {"h1", "h2", "h3", "h4"}
BLOCK_TAGS = {"p", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5"}

# Non-teaching docs: the index and front matter steal search slots. Preface,
# part openers, chapters, and appendices stay.
NON_TEACHING_IDS = {
    "cover",
    "dedication01",
    "titlepage01",
    "copyright-page01",
    "ix01",
    "colophon01",
    "colophon02",
}

# A hidden marker wraps a figure's xref href so the citing-paragraph search can
# find the figure. Stored text drops it and keeps the link words.
MARKER = "\x00"
_MARKER_RE = re.compile(f"{MARKER}[^{MARKER}]*{MARKER}")


def _marked(machine_id):
    return f"{MARKER}{machine_id}{MARKER}"


def _unmarked(text):
    return _MARKER_RE.sub("", text)


class ChapterParser(HTMLParser):
    """Walk one spine document into blocks, tables, and figure records.

    A block is a heading or a paragraph. A table is one whole block, never split.
    A figure keeps its caption (h6 inside the figure, else img alt, else "").
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.figures = []
        self._skip = 0
        self._stack = []
        self._text = []
        self._in_figure = 0
        self._fig = None
        self._capture = None
        self._heading_id = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "figure":
            self._in_figure += 1
            if self._in_figure == 1:
                self._fig = {
                    "anchor": "",
                    "src": "",
                    "alt": "",
                    "label": "",
                    "caption": "",
                }
            return
        if self._in_figure:
            if tag == "div" and attr.get("id") and not self._fig["anchor"]:
                self._fig["anchor"] = attr["id"]
            elif tag == "img":
                self._fig["src"] = attr.get("src", "")
                self._fig["alt"] = (attr.get("alt") or "").strip()
            elif tag == "h6":
                self._capture = "caption"
                self._text = []
            elif tag == "span" and attr.get("class") == "label" and self._capture == "caption":
                self._capture = "label"
            return
        if tag == "table":
            self._capture = "table"
            self._text = []
            self._stack.append(tag)
            return
        if tag == "a" and attr.get("data-type") == "xref":
            self._text.append(_marked(attr.get("href", "").lstrip("#")))
            return
        if tag in BLOCK_TAGS or tag in ("ul", "ol", "dl"):
            self._stack.append(tag)
            if tag in BLOCK_TAGS and self._capture is None:
                self._capture = tag
                self._text = []
                # The heading's own id, so a chunk can point back at the spot
                # in the reader. Nothing else on a block carries one.
                self._heading_id = attr.get("id", "") if tag in HEADING_TAGS else ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag == "figure" and self._in_figure:
            self._in_figure -= 1
            if self._in_figure == 0 and self._fig and self._fig["src"]:
                caption = self._fig["caption"].strip()
                if not caption:
                    caption = self._fig["alt"]
                self.figures.append({
                    "anchor": self._fig["anchor"],
                    "label": self._fig["label"].strip(),
                    "caption": caption,
                    "src": self._fig["src"],
                })
                self._fig = None
            return
        if self._in_figure:
            if tag == "h6" and self._capture == "caption":
                self._fig["caption"] = _clean("".join(self._text))
                self._capture = None
                self._text = []
            elif tag == "span" and self._capture == "label":
                self._fig["label"] = _clean("".join(self._text))
                self._capture = "caption"
                self._text = []
            return
        if tag == "table" and self._capture == "table":
            text = _clean("".join(self._text))
            if text:
                self.blocks.append({"kind": "table", "text": text})
            self._capture = None
            self._text = []
            if self._stack and self._stack[-1] == "table":
                self._stack.pop()
            return
        if tag in BLOCK_TAGS and self._capture == tag:
            text = _clean("".join(self._text))
            if text:
                kind = "heading" if tag in HEADING_TAGS else "para"
                self.blocks.append({
                    "kind": kind,
                    "tag": tag,
                    "text": text,
                    "id": self._heading_id,
                })
            self._capture = None
            self._text = []
            self._heading_id = ""
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()

    def handle_data(self, data):
        if self._skip or self._capture is None:
            return
        self._text.append(data)


def _clean(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chapter_number(doc_id, html_text):
    match = re.match(r"ch(\d+)", doc_id)
    if match:
        return str(int(match.group(1)))
    label = re.search(r"Chapter\s+(\d+)", html_text[:800])
    if label:
        return label.group(1)
    return doc_id


def _spine(zf):
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = container.find(f".//{CONTAINER}rootfile")
    opf_path = rootfile.get("full-path")
    opf_dir = str(Path(opf_path).parent).replace("\\", "/")
    if opf_dir == ".":
        opf_dir = ""
    opf = ET.fromstring(zf.read(opf_path))
    manifest = {}
    for item in opf.find(f"{OPF}manifest"):
        manifest[item.get("id")] = item.get("href")
    docs = []
    for itemref in opf.find(f"{OPF}spine"):
        href = manifest[itemref.get("idref")]
        path = f"{opf_dir}/{href}" if opf_dir else href
        doc_id = Path(href).stem
        docs.append((doc_id, path))
    return docs


def _figure_id(label, chapter, index):
    match = re.search(r"((?:Figure|Table|Fig\.)\s*[A-Z]?\d+-\d+)", label or "", re.I)
    if match:
        raw = match.group(1).lower().replace(" ", "-").replace(".", "")
        return raw
    return f"fig-{chapter}-{index}"


def _cites(text):
    return set(re.findall(r"\x00([^\x00]+)\x00", text))


def _visible(text):
    return _unmarked(text).strip()


def _stored(text):
    return _clean(_visible(text))


def _mentions_figure(text):
    visible = _visible(text)
    return bool(re.search(r"\b(Figure|Fig\.)\b", visible))


SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A sentence does not end inside these. Being liberal here is the safe side:
# a missed merge only makes a piece longer, while a false split becomes a
# chunk that starts mid-sentence.
ABBREVIATIONS = (
    "e.g.", "i.e.", "et al.", "vs.", "etc.", "cf.", "approx.", "Fig.", "Figs.",
    "Dr.", "Mr.", "Ms.", "Mrs.", "Jr.", "Sr.", "St.", "Inc.", "Ltd.", "Co.",
)
INITIAL = re.compile(r"(?:^|\s)[A-Z]\.$")


def _sentences(text):
    """Sentences of a block. Known abbreviations and initials do not end one.

    A false boundary here matters: pieces are cut only where this function says
    a sentence ends, so a wrong split becomes a chunk that starts mid-sentence.
    """
    sentences = []
    for part in SENTENCE_END.split((text or "").strip()):
        part = part.strip()
        if not part:
            continue
        if sentences and (
            sentences[-1].endswith(ABBREVIATIONS) or INITIAL.search(sentences[-1])
        ):
            sentences[-1] = sentences[-1] + " " + part
        else:
            sentences.append(part)
    return sentences


def _by_words(text):
    """Fallback for one sentence past the cap: it has to be cut somewhere."""
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_MAX_CHARS, len(text))
        if end < len(text):
            cut = text.rfind(" ", start, end)
            if cut > start + CHUNK_MAX_CHARS // 2:
                end = cut
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end
    return pieces


def _pieces(text):
    """Text as pieces no longer than the cap, cut only at sentence ends."""
    if len(text) <= CHUNK_MAX_CHARS:
        return [text]
    pieces = []
    current = ""
    for sentence in _sentences(text):
        if len(sentence) > CHUNK_MAX_CHARS:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_by_words(sentence))
            continue
        if current and len(current) + len(sentence) + 1 > CHUNK_MAX_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        pieces.append(current)
    return pieces


def _sentence_tail(text, limit):
    """Trailing whole sentences, up to the limit. Never a mid-sentence cut.

    A single trailing sentence longer than the limit yields nothing. A citation
    list has no sentence ends at all, so its whole text reads as one sentence;
    taking that as the overlap made every chunk the previous chunk plus more,
    which is how chunks grew past 5000 characters.
    """
    kept = []
    size = 0
    for sentence in reversed(_sentences(text)):
        if len(sentence) > limit:
            break
        if kept and size + len(sentence) + 1 > limit:
            break
        kept.append(sentence)
        size += len(sentence) + 1
    return " ".join(reversed(kept))


def _section_chunks(heading, body_blocks):
    """One section. Overlap only when the section is longer than the cap.

    Tables stay one piece even if they are longer than the cap.
    """
    pieces = []
    for block in body_blocks:
        text = _stored(block["text"])
        # A table stays one piece even past the cap: a cut table is worse than
        # a long chunk.
        if block["kind"] == "table":
            pieces.append(text)
            continue
        pieces.extend(_pieces(text))

    if not pieces and not heading:
        return []

    chunks = []
    current = []
    current_len = 0
    last_body = ""
    heading = _stored(heading)
    heading_prefix = (heading + "\n") if heading else ""
    budget = max(CHUNK_MAX_CHARS - len(heading_prefix), 200)

    def flush():
        nonlocal current, current_len, last_body
        if not current and not heading:
            return
        body = "\n\n".join(current).strip()
        text = (heading_prefix + body).strip()
        if text:
            chunks.append(text)
            last_body = body
        current = []
        current_len = 0

    for piece in pieces:
        extra = len(piece) + (2 if current else 0)
        if current and current_len + extra > budget:
            flush()
            # Overlap only because this section did not fit in one chunk. The
            # tail comes from the body, not the chunk: a heading in the
            # overlap would repeat the heading inside the next chunk.
            if chunks:
                tail = _sentence_tail(last_body, CHUNK_OVERLAP_CHARS)
                if tail:
                    current = [tail]
                    current_len = len(tail)
        current.append(piece)
        current_len += extra
    flush()
    return chunks


def _heading_level(block):
    tag = block.get("tag") or ""
    return int(tag[1]) if tag[:1] == "h" and tag[1:].isdigit() else 1


def _trail_text(trail):
    return " > ".join(text for _, text in trail)


def _chunk_chapter(blocks):
    """Sections as units: the chunk text plus where it came from.

    `section` is the heading trail and `anchor` is the heading's own id. Both
    are metadata only: joining them to the text would move every vector that
    was built from it.
    """
    sections = []
    trail = []
    heading = ""
    anchor = ""
    body = []
    for block in blocks:
        if block["kind"] == "heading":
            if heading or body:
                sections.append((heading, anchor, _trail_text(trail), body))
            level = _heading_level(block)
            trail = [(height, text) for height, text in trail if height < level]
            trail.append((level, block["text"]))
            heading = block["text"]
            anchor = block.get("id", "")
            body = []
        else:
            body.append(block)
    if heading or body:
        sections.append((heading, anchor, _trail_text(trail), body))

    units = []
    for heading, anchor, trail_text, body in sections:
        for text in _section_chunks(heading, body):
            units.append({"text": text, "section": trail_text, "anchor": anchor})
    return units


def _attach_paragraphs(figures, blocks):
    """Nearest paragraph that points at the figure, else empty.

    A pointer is an xref href matching the figure anchor, or the words
    Figure / Fig. in the same stretch of text.
    """
    paras = [b for b in blocks if b["kind"] == "para"]
    for figure in figures:
        anchor = figure["anchor"]
        best = ""
        best_distance = None
        for index, para in enumerate(paras):
            cited = anchor and anchor in _cites(para["text"])
            named = _mentions_figure(para["text"]) and (
                not anchor or cited or _label_in_text(figure["label"], para["text"])
            )
            if not cited and not named:
                continue
            if best_distance is None or index < best_distance:
                best = _visible(para["text"])
                best_distance = index
                if cited:
                    break
        figure["referencing_paragraph"] = best


def _label_in_text(label, text):
    match = re.search(r"(\d+-\d+)", label or "")
    if not match:
        return False
    return match.group(1) in _visible(text)


def ingest_epub(epub_path, figures_dir=None, write_images=True):
    """Return the index dict. Write images when figures_dir is set."""
    epub_path = Path(epub_path)
    chunks = []
    figures = []
    with zipfile.ZipFile(epub_path) as zf:
        names = set(zf.namelist())
        for doc_id, path in _spine(zf):
            if doc_id in NON_TEACHING_IDS or path not in names:
                continue
            raw = zf.read(path).decode("utf-8")
            parser = ChapterParser()
            parser.feed(raw)
            parser.close()
            chapter = _chapter_number(doc_id, raw)
            units = _chunk_chapter(parser.blocks)
            if not units and not parser.figures:
                continue
            _attach_paragraphs(parser.figures, parser.blocks)
            for index, unit in enumerate(units, start=1):
                text = unit["text"]
                heading = text.split("\n", 1)[0]
                chunks.append({
                    "chunk_id": f"{doc_id}-{index:03d}",
                    "chapter": chapter,
                    "heading": heading,
                    "text": text,
                    "source": doc_id,
                    "doc": path,
                    "section": unit["section"],
                    "anchor": unit["anchor"],
                })
            for index, figure in enumerate(parser.figures, start=1):
                file_name = ""
                src = figure["src"]
                image_path = str(Path(path).parent / src).replace("\\", "/")
                if write_images and figures_dir and image_path in names:
                    figures_dir = Path(figures_dir)
                    figures_dir.mkdir(parents=True, exist_ok=True)
                    file_name = Path(src).name
                    (figures_dir / file_name).write_bytes(zf.read(image_path))
                figures.append({
                    "id": _figure_id(figure["label"], chapter, index),
                    "chapter": chapter,
                    "caption": figure["caption"],
                    "referencing_paragraph": figure["referencing_paragraph"],
                    "file": file_name or Path(src).name,
                    "anchor": figure["anchor"],
                    "source": doc_id,
                })
    by_number = {}
    for figure in figures:
        match = re.search(r"(\d+-\d+)", figure.get("id") or "")
        if match:
            by_number[match.group(1)] = figure["id"]
    for chunk in chunks:
        # Which figures this chunk names. Derived from the text with the same
        # rule the answer layer uses, so a split chunk cannot lose a figure.
        chunk["figures"] = sorted({
            by_number[number]
            for number in cited_numbers(chunk["text"])
            if number in by_number
        })
    return {
        "book_id": "fde",
        "chunks": chunks,
        "figures": figures,
    }


def main():
    if not BOOK.is_file():
        raise SystemExit(f"missing book: {BOOK}")
    if FIGURES.is_dir():
        for old in FIGURES.iterdir():
            if old.is_file():
                old.unlink()
    FIGURES.mkdir(parents=True, exist_ok=True)
    index = ingest_epub(BOOK, FIGURES, write_images=True)
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")
    reloaded = json.loads(INDEX.read_text(encoding="utf-8"))
    captions = [f["caption"] for f in reloaded["figures"] if f["caption"]][:3]
    print(f"chunks {len(reloaded['chunks'])}")
    print(f"figures {len(reloaded['figures'])}")
    for caption in captions:
        print(f"caption: {caption}")


if __name__ == "__main__":
    main()
