"""EPUB -> data/index.json + data/figures/. No vectors, no Ollama.

Stdlib only. Records are JSON. Pictures stay files. No pickle.
"""

import argparse
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from figures import cited_numbers, number_from_id

ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "books" / "fde.epub"
INDEX = ROOT / "data" / "index.json"
FIGURES = ROOT / "data" / "figures"

CHUNK_MAX_CHARS = 1400
CHUNK_OVERLAP_CHARS = 180

_TOKENIZER = None


def get_tokenizer():
    """Load HuggingFace Tokenizer from local cache with offline fallback."""
    global _TOKENIZER
    if _TOKENIZER is not None:
        return _TOKENIZER
    try:
        import glob
        import os
        from tokenizers import Tokenizer
        pattern = os.path.expanduser("~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/**/tokenizer.json")
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            matches = glob.glob(os.path.expanduser("~/.cache/huggingface/hub/**/tokenizer.json"), recursive=True)
        if matches:
            _TOKENIZER = Tokenizer.from_file(matches[0])
            return _TOKENIZER
    except Exception:
        pass
    return None


def count_tokens(text):
    """Count subword tokens using HuggingFace tokenizer, with fallback to whitespace."""
    tok = get_tokenizer()
    if tok is not None:
        try:
            return len(tok.encode(text or "").ids)
        except Exception:
            pass
    return max(1, len((text or "").split()))

OPF = "{http://www.idpf.org/2007/opf}"
CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"

SKIP_TAGS = {"script", "style", "head"}
HEADING_TAGS = {"h1", "h2", "h3", "h4"}
BLOCK_TAGS = {"p", "li", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5"}

# Non-teaching docs: the index and front matter steal search slots. Preface,
# part openers, chapters, and appendices stay.
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

NON_TEACHING_HEADING_RE = re.compile(
    r"^(?:index|colophon|about the authors?|dedication|copyright|title\s*page|table of contents|contents|revision history|welcome|acknowledgments?)\b",
    re.I,
)

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
        self._fig_div_depth = 0
        self._fig = None
        self._capture = None
        self._heading_id = ""
        self._last_h5_fig = None
        self._pre_markup = 0
        self._table_rows = []
        self._table_row = None
        self._table_cell = None
        self._table_caption = []
        self._table_in_caption = False
        self._table_raw = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return

        classes = attr.get("class", "").lower().split()
        is_fig_div = tag == "div" and any(c in ("figure-container", "mediaobject") for c in classes)

        if tag == "figure" or is_fig_div:
            self._in_figure += 1
            if tag == "div":
                self._fig_div_depth += 1
            if self._in_figure == 1:
                self._fig = {
                    "anchor": attr.get("id", ""),
                    "src": "",
                    "alt": "",
                    "label": "",
                    "caption": "",
                }
                if self._last_h5_fig:
                    self._fig["label"], self._fig["caption"] = self._last_h5_fig
                    self._last_h5_fig = None
            return

        if self._in_figure:
            if tag == "div":
                if self._fig_div_depth > 0:
                    self._fig_div_depth += 1
                if attr.get("id") and not self._fig["anchor"]:
                    self._fig["anchor"] = attr["id"]
            elif tag == "img":
                self._fig["src"] = attr.get("src", "")
                alt = attr.get("alt") or attr.get("data-alt") or ""
                self._fig["alt"] = alt.strip()
            elif tag in ("h5", "h6"):
                self._capture = "caption"
                self._text = []
            elif tag == "span" and attr.get("class") == "label" and self._capture == "caption":
                self._capture = "label"
            return

        if tag == "table":
            self._capture = "table"
            self._text = []
            self._table_rows = []
            self._table_row = None
            self._table_cell = None
            self._table_caption = []
            self._table_in_caption = False
            self._table_raw = []
            self._stack.append(tag)
            return
        if self._capture == "table":
            if tag == "caption":
                self._table_in_caption = True
            elif tag == "tr":
                self._table_row = []
            elif tag in ("td", "th"):
                self._table_cell = []
            return
        if tag == "a" and attr.get("data-type") == "xref":
            self._text.append(f"\x00{attr.get('href', '').lstrip('#')}\x00")
            return
        if tag in BLOCK_TAGS or tag in ("ul", "ol", "dl"):
            self._stack.append(tag)
            if tag in BLOCK_TAGS and self._capture is None:
                self._capture = tag
                self._text = []
                self._heading_id = attr.get("id", "") if tag in HEADING_TAGS else ""
                if tag == "pre":
                    self._pre_markup = 0
            return
        if self._capture == "pre" and tag in ("code", "span"):
            # DDIA wraps every syntax-highlighted token in its own <code>
            # element, separated by blank lines. That markup is layout, not
            # code: count it so </pre> can reflow it back into one listing.
            self._pre_markup += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return

        if self._capture == "table":
            if tag == "caption":
                self._table_in_caption = False
                return
            if tag in ("td", "th"):
                if self._table_row is not None and self._table_cell is not None:
                    self._table_row.append(_clean_cell("".join(self._table_cell)))
                self._table_cell = None
                return
            if tag == "tr":
                if self._table_row:
                    self._table_rows.append(self._table_row)
                self._table_row = None
                return
            if tag == "table":
                rows = [row for row in self._table_rows if any(row)]
                caption = _clean_cell("".join(self._table_caption))
                rows_text = "\n".join(" | ".join(row) for row in rows)
                text = "\n".join(part for part in (caption, rows_text) if part)
                if text:
                    self.blocks.append({
                        "kind": "table",
                        "text": text,
                        # Keep the publisher's flat text for chunk packing:
                        # changing it moves every later chunk id in the book.
                        "pack": _clean("".join(self._table_raw)),
                    })
                self._capture = None
                self._text = []
                self._table_rows = []
                self._table_row = None
                self._table_cell = None
                self._table_caption = []
                self._table_in_caption = False
                self._table_raw = []
                if self._stack and self._stack[-1] == "table":
                    self._stack.pop()
                return
            return

        if self._in_figure:
            if self._fig_div_depth > 0 and tag == "div":
                self._fig_div_depth -= 1
                if self._fig_div_depth == 0:
                    self._in_figure -= 1
            elif tag == "figure":
                self._in_figure -= 1

            if self._in_figure == 0:
                if self._fig and self._fig["src"]:
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

            if tag in ("h5", "h6") and self._capture == "caption":
                cap_text = _clean("".join(self._text))
                self._fig["caption"] = cap_text
                m = re.match(r"^(Figure\s+[A-Z]?\d+[-.]\d+)", cap_text, re.I)
                if m and not self._fig["label"]:
                    self._fig["label"] = m.group(1)
                self._capture = None
                self._text = []
            elif tag == "span" and self._capture == "label":
                self._fig["label"] = _clean("".join(self._text))
                self._capture = "caption"
                self._text = []
            return

        if tag == "h5" and self._capture == "h5":
            h5_text = _clean("".join(self._text))
            m = re.match(r"^(Figure\s+[A-Z]?\d+[-.]\d+)", h5_text, re.I)
            if m:
                self._last_h5_fig = (m.group(1), h5_text)
            else:
                self._last_h5_fig = None

        if tag in BLOCK_TAGS and self._capture == tag:
            if tag == "pre":
                raw = "".join(self._text)
                text = (
                    _clean_program_listing(raw)
                    if self._pre_markup > 1
                    else _clean_code(raw)
                )
                kind = "code"
                pack = _clean(raw)
            else:
                text = _clean("".join(self._text))
                kind = "heading" if tag in HEADING_TAGS else "para"
                pack = text
            if text:
                self.blocks.append({
                    "kind": kind,
                    "tag": tag,
                    "text": text,
                    "pack": pack,
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
        if self._capture == "table":
            self._table_raw.append(data)
            if self._table_in_caption:
                self._table_caption.append(data)
            elif self._table_cell is not None:
                self._table_cell.append(data)
            return
        self._text.append(data)


def _clean(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_program_listing(text):
    """A listing whose markup put one token on every line, with blank lines.

    Syntax highlighters (DDIA's EPUB) split a listing into per-token <code>
    elements. Reflow the token stream into one readable line; any spacing
    left by the markup is not code layout.
    """
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    return re.sub(r"\s+([,;:)\]])", r"\1", text)


def _clean_code(text):
    """A literal <pre>: keep line breaks and indentation, drop blank runs."""
    text = (
        text.replace("\xa0", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    kept = []
    for line in lines:
        if line.strip():
            kept.append(line)
        elif kept and kept[-1] != "":
            kept.append("")
    return "\n".join(kept)


def _clean_cell(text):
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _chapter_number(doc_id, html_text):
    match = re.match(r"ch(?:apter)?[\s_-]*(\d+)", doc_id, re.I)
    if match:
        return str(int(match.group(1)))
    label = re.search(r"Chapter\s+(\d+)", html_text[:800])
    if label:
        return label.group(1)
    m_head = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html_text[:2000], re.I | re.S)
    if m_head:
        h_clean = re.sub(r"<[^>]+>", "", m_head.group(1)).strip().lower()
        if h_clean.startswith("preface"):
            return "preface"
        if h_clean.startswith("glossary"):
            return "glossary"
        if h_clean.startswith("appendix"):
            return "appendix"
    return doc_id


def read_metadata(zf, opf_path):
    opf_dir = str(Path(opf_path).parent).replace("\\", "/")
    if opf_dir == ".":
        opf_dir = ""
    opf = ET.fromstring(zf.read(opf_path))
    title = ""
    creator = ""
    for el in opf.iter():
        if el.tag.endswith("title") and not title and el.text:
            title = el.text.strip()
        if el.tag.endswith("creator") and not creator and el.text:
            creator = el.text.strip()
    title = re.sub(r"\s*\(\d{10,13}\)\s*$", "", title).strip()

    manifest = {}
    manifest_items = {}
    manifest_el = opf.find(f"{OPF}manifest")
    if manifest_el is not None:
        for item in manifest_el:
            mid = item.get("id")
            href = item.get("href")
            manifest[mid] = href
            manifest_items[mid] = item.attrib

    cover_href = None
    for mid, attr in manifest_items.items():
        props = attr.get("properties", "").split()
        if "cover-image" in props:
            cover_href = attr.get("href")
            break
    if not cover_href:
        for meta in opf.iter():
            if meta.tag.endswith("meta") and meta.get("name") == "cover":
                cid = meta.get("content")
                if cid in manifest:
                    cover_href = manifest[cid]
                    break
    if not cover_href:
        for mid, attr in manifest_items.items():
            mtype = attr.get("media-type", "")
            if mtype.startswith("image/") and mid.lower() in ("cover-image", "cover", "cover-img"):
                cover_href = attr.get("href")
                break

    cover_relpath = None
    if cover_href:
        cover_relpath = f"{opf_dir}/{cover_href}" if opf_dir else cover_href

    return {
        "title": title,
        "author": creator,
        "cover_relpath": cover_relpath,
        "manifest": manifest,
        "manifest_items": manifest_items,
        "opf": opf,
        "opf_dir": opf_dir,
    }


def _spine(zf):
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = container.find(f".//{CONTAINER}rootfile")
    opf_path = rootfile.get("full-path")
    meta = read_metadata(zf, opf_path)
    opf = meta["opf"]
    opf_dir = meta["opf_dir"]
    manifest = meta["manifest"]
    manifest_items = meta["manifest_items"]

    docs = []
    spine_el = opf.find(f"{OPF}spine")
    if spine_el is not None:
        for itemref in spine_el:
            idref = itemref.get("idref")
            if idref not in manifest:
                continue
            href = manifest[idref]
            path = f"{opf_dir}/{href}" if opf_dir else href
            doc_id = Path(href).stem
            is_linear = itemref.get("linear", "yes").lower() != "no"
            item_attr = manifest_items.get(idref, {})
            is_nav = "nav" in item_attr.get("properties", "").split()
            docs.append((doc_id, path, is_linear, is_nav))
    return docs, meta


def _figure_id(label, chapter, index):
    match = re.search(r"(Figure\s+(\d+)[-.](\d+))", label or "", re.I)
    if match:
        return f"figure-{match.group(2)}-{match.group(3)}"
    match2 = re.search(r"((?:Figure|Table|Fig\.)\s*[A-Z]?\d+[-.]\d+)", label or "", re.I)
    if match2:
        raw = match2.group(1).lower().replace(" ", "-").replace(".", "-")
        raw = re.sub(r"-+", "-", raw)
        if raw.startswith("fig-"):
            raw = "figure-" + raw[4:]
        return raw
    return f"fig-{chapter}-{index}"


def _cites(text):
    return set(re.findall(r"\x00([^\x00]+)\x00", text))


def _visible(text):
    return _unmarked(text).strip()


def _stored(text):
    return _clean(_visible(text))


def _stored_block(block):
    text = _unmarked(block.get("text") or "")
    return _clean_code(text) if block.get("kind") == "code" else _clean(text)


def _pack_text(block):
    """The text used to decide chunk boundaries.

    Display text for code and tables is cleaner than the publisher's flat
    text, but packing by it would move every later chunk id in the book. The
    reader gets the clean text; the boundaries stay where they were.
    """
    return _stored(block.get("pack") or block.get("text") or "")


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


def _pieces_by_tokens(text, max_tokens):
    """Text as pieces no longer than max_tokens subword tokens."""
    if count_tokens(text) <= max_tokens:
        return [text]
    pieces = []
    current = ""
    for sentence in _sentences(text):
        if count_tokens(sentence) > max_tokens:
            if current:
                pieces.append(current)
                current = ""
            words_list = sentence.split()
            sub = []
            for w in words_list:
                cand = " ".join(sub + [w])
                if sub and count_tokens(cand) > max_tokens:
                    pieces.append(" ".join(sub))
                    sub = [w]
                else:
                    sub.append(w)
            if sub:
                pieces.append(" ".join(sub))
            continue
        cand = (current + " " + sentence).strip()
        if current and count_tokens(cand) > max_tokens:
            pieces.append(current)
            current = sentence
        else:
            current = cand
    if current:
        pieces.append(current)
    return pieces


def _section_chunks(heading, body_blocks, max_tokens=None, with_blocks=False):
    """One section. Overlap only when the section is longer than the cap.

    Tables and code stay one piece even if they are longer than the cap
    (unless max_tokens is set): a cut table or a cut listing is worse than a
    long chunk. With `with_blocks`, each chunk also carries the body blocks
    that produced it, so the reader can render code and tables as blocks
    instead of one paragraph per source line.
    """
    heading = _stored(heading)
    heading_prefix = (heading + "\n") if heading else ""
    budget = max(CHUNK_MAX_CHARS - len(heading_prefix), 200)

    pieces = []
    for block in body_blocks:
        text = _stored_block(block)
        pack = _pack_text(block)
        kind = block.get("kind") or "para"
        if kind == "paragraph":
            kind = "para"
        if kind in ("table", "code") and max_tokens is None:
            pieces.append({"text": text, "pack": pack, "kind": kind})
            continue
        if max_tokens is not None:
            h_tokens = count_tokens(heading_prefix) if heading_prefix else 0
            body_budget = max(5, max_tokens - h_tokens - 4)  # 4 token safety margin for formatting
            pieces.extend({"text": text, "pack": text, "kind": kind} for text in _pieces_by_tokens(text, body_budget))
        else:
            pieces.extend({"text": text, "pack": text, "kind": kind} for text in _pieces(text))

    if not pieces and not heading:
        return []

    chunks = []
    current = []
    current_len = 0
    last_body = ""

    def flush():
        nonlocal current, current_len, last_body
        if not current and not heading:
            return
        body = "\n\n".join(piece["text"] for piece in current).strip()
        text = (heading_prefix + body).strip()
        if text:
            chunks.append({
                "text": text,
                "blocks": [
                    {"kind": piece["kind"], "text": piece["text"]}
                    for piece in current
                ],
            })
            last_body = body
        current = []
        current_len = 0

    for piece in pieces:
        extra = len(piece.get("pack", piece["text"])) + (2 if current else 0)
        exceeded = False
        if max_tokens is not None:
            cand = (heading_prefix + "\n\n".join(p.get("pack", p["text"]) for p in current + [piece])).strip()
            if count_tokens(cand) > max_tokens:
                exceeded = True
        elif current and current_len + extra > budget:
            exceeded = True

        if current and exceeded:
            flush()
            # Overlap only because this section did not fit in one chunk. The
            # tail comes from the body, not the chunk: a heading in the
            # overlap would repeat the heading inside the next chunk.
            if chunks:
                tail = _sentence_tail(last_body, CHUNK_OVERLAP_CHARS)
                if tail:
                    if max_tokens is not None:
                        # Only keep overlap if tail + piece fits within max_tokens
                        cand_overlap = (heading_prefix + tail + "\n\n" + piece.get("pack", piece["text"])).strip()
                        if count_tokens(cand_overlap) <= max_tokens:
                            current = [{"text": tail, "pack": tail, "kind": "para"}]
                            current_len = len(tail)
                    else:
                        current = [{"text": tail, "pack": tail, "kind": "para"}]
                        current_len = len(tail)
        current.append(piece)
        current_len += extra
    flush()
    if with_blocks:
        return chunks
    return [chunk["text"] for chunk in chunks]


def _heading_level(block):
    tag = block.get("tag") or ""
    return int(tag[1]) if tag[:1] == "h" and tag[1:].isdigit() else 1


def _trail_text(trail):
    return " > ".join(text for _, text in trail)


def _chunk_chapter(blocks, max_tokens=None, with_blocks=False):
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
        for chunk in _section_chunks(
            heading, body, max_tokens=max_tokens, with_blocks=with_blocks
        ):
            if with_blocks:
                units.append({
                    "text": chunk["text"],
                    "blocks": chunk["blocks"],
                    "section": trail_text,
                    "anchor": anchor,
                })
            else:
                units.append({
                    "text": chunk,
                    "section": trail_text,
                    "anchor": anchor,
                })
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
    match = re.search(r"(\d+)[-.](\d+)", label or "")
    if not match:
        return False
    c1, c2 = match.group(1), match.group(2)
    vis = _visible(text)
    return f"{c1}-{c2}" in vis or f"{c1}.{c2}" in vis


def update_books_catalog(book_id, title, author, index_path, figures_dir, chunks, figures, cover_file="cover.png"):
    catalog_path = ROOT / "data" / "books.json"
    catalog = []
    if catalog_path.is_file():
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog = raw if isinstance(raw, list) else raw.get("books", [])
        except Exception:
            catalog = []

    unique_chapters = len({c.get("chapter") for c in chunks if c.get("chapter") is not None})
    cover_url = f"/figures/cover?book_id={book_id}" if book_id != "fde" else "/figures/cover"

    entry = {
        "book_id": book_id,
        "title": title,
        "author": author,
        "chapter_count": unique_chapters,
        "chunk_count": len(chunks),
        "figure_count": len(figures),
        "cover_url": cover_url,
        "index_path": (str(Path(index_path).resolve().relative_to(ROOT.resolve())).replace("\\", "/") if Path(index_path).is_absolute() else str(index_path).replace("\\", "/")),
        "figures_dir": (str(Path(figures_dir).resolve().relative_to(ROOT.resolve())).replace("\\", "/") if Path(figures_dir).is_absolute() else str(figures_dir).replace("\\", "/")),
    }

    updated = False
    for i, b in enumerate(catalog):
        if b.get("book_id") == book_id:
            catalog[i] = entry
            updated = True
            break
    if not updated:
        catalog.append(entry)

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return entry


def ingest_epub(epub_path=BOOK, figures_dir=None, write_images=True, book_id=None):
    """Return the index dict. Write images when figures_dir is set."""
    epub_path = Path(epub_path)
    if book_id is None:
        if str(epub_path.resolve()) == str(BOOK.resolve()):
            book_id = "fde"
        else:
            book_id = epub_path.stem

    if figures_dir is None:
        figures_dir = FIGURES if book_id == "fde" else (ROOT / "data" / "figures" / book_id)
    figures_dir = Path(figures_dir)

    chunks = []
    figures = []
    cover_file = ""
    with zipfile.ZipFile(epub_path) as zf:
        names = set(zf.namelist())
        spine_docs, meta = _spine(zf)

        # Cover extraction
        cover_relpath = meta.get("cover_relpath")
        if cover_relpath and cover_relpath in names:
            cover_ext = Path(cover_relpath).suffix.lower() or ".png"
            cover_file = f"cover{cover_ext}"
            if write_images:
                figures_dir.mkdir(parents=True, exist_ok=True)
                (figures_dir / cover_file).write_bytes(zf.read(cover_relpath))

        for doc_id, path, is_linear, is_nav in spine_docs:
            if doc_id in NON_TEACHING_IDS or path not in names:
                continue
            if is_nav or not is_linear:
                continue
            if doc_id.lower().startswith("ix") or doc_id.lower().startswith("index"):
                continue

            raw = zf.read(path).decode("utf-8")

            # Skip non-teaching sections by data-type or heading/title
            if re.search(r'data-type=["\'](?:titlepage|copyright-page|dedication|colophon|toc)["\']', raw[:1500], re.I):
                continue

            m_head = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", raw[:2000], re.I | re.S)
            head_text = re.sub(r"<[^>]+>", "", m_head.group(1)).strip() if m_head else ""
            m_title = re.search(r"<title[^>]*>(.*?)</title>", raw[:2000], re.I | re.S)
            title_text = re.sub(r"<[^>]+>", "", m_title.group(1)).strip() if m_title else ""

            if head_text and NON_TEACHING_HEADING_RE.search(head_text):
                continue
            if not head_text and title_text and NON_TEACHING_HEADING_RE.search(title_text):
                continue

            parser = ChapterParser()
            parser.feed(raw)
            parser.close()
            chapter = _chapter_number(doc_id, raw)
            units = _chunk_chapter(parser.blocks, with_blocks=True)
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
                    "blocks": unit.get("blocks") if any(
                        block.get("kind") != "para" for block in unit.get("blocks", [])
                    ) else None,
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
                    figures_dir.mkdir(parents=True, exist_ok=True)
                    figure_id = _figure_id(figure["label"], chapter, index)
                    suffix = Path(src).suffix.lower() or ".bin"
                    file_name = figure_id + suffix
                    blob = zf.read(image_path)
                    target = figures_dir / file_name
                    if target.exists() and target.read_bytes() != blob:
                        file_name = f"{figure_id}-{doc_id}{suffix}"
                        target = figures_dir / file_name
                    target.write_bytes(blob)
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
        number = number_from_id(figure.get("id"))
        if number:
            by_number[number] = figure["id"]
    for chunk in chunks:
        chunk["figures"] = sorted({
            by_number[number]
            for number in cited_numbers(chunk["text"])
            if number in by_number
        })
    return {
        "book_id": book_id,
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "cover_file": cover_file,
        "chunks": chunks,
        "figures": figures,
    }




def ingest_pdf(pdf_path, max_tokens=None):
    """Extract chapters and pages from a PDF file using PyMuPDF (fitz).

    Returns a list of chunk dicts following the canonical schema:
    [{"chunk_id": ..., "chapter": ..., "heading": ..., "text": ..., "source": ...}]
    """
    import fitz

    if isinstance(pdf_path, (bytes, bytearray)):
        doc = fitz.open("pdf", pdf_path)
    else:
        doc = fitz.open(str(pdf_path))

    toc = doc.get_toc()
    toc_by_page = {}
    if toc:
        for item in toc:
            lvl, title, page_num = item[0], item[1], item[2]
            if page_num not in toc_by_page or lvl == 1:
                toc_by_page[page_num] = title.strip()

    chunks = []
    current_chapter = "1"
    current_heading = ""
    chunk_index = 0

    for page_num in range(1, len(doc) + 1):
        page = doc[page_num - 1]
        text = (page.get_text() or "").strip()
        if not text:
            continue

        if page_num in toc_by_page:
            current_heading = toc_by_page[page_num]
            m = re.search(r"chapter\s+(\d+)", current_heading, re.I)
            if m:
                current_chapter = m.group(1)

        lines = text.splitlines()
        first_line = lines[0].strip() if lines else ""
        if page_num in toc_by_page:
            current_heading = toc_by_page[page_num]
            heading_to_use = current_heading
        elif len(first_line) < 80 and not first_line.endswith("."):
            heading_to_use = first_line
        else:
            heading_to_use = current_heading or f"Page {page_num}"

        m = re.search(r"chapter\s+(\d+)", heading_to_use, re.I)
        if m:
            current_chapter = m.group(1)

        stored_text = _stored(text)
        blocks = [{"kind": "paragraph", "text": stored_text}]
        units = _section_chunks(current_heading, blocks, max_tokens=max_tokens)
        if not units and stored_text:
            units = [f"{current_heading}\n{stored_text}".strip()]

        for u in units:
            chunk_index += 1
            cid = f"pdf-p{page_num:03d}-{chunk_index:03d}"
            chunks.append({
                "chunk_id": cid,
                "chapter": str(current_chapter),
                "heading": heading_to_use,
                "text": u,
                "source": f"p.{page_num}",
            })

    return chunks

def main():
    parser = argparse.ArgumentParser(description="Ingest EPUB into JSON index and extracted figure files.")
    parser.add_argument("--epub", default=str(BOOK), help="Path to input EPUB file (default: books/fde.epub)")
    parser.add_argument("--book-id", default=None, help="Book ID (default: fde, or stem of --epub)")
    parser.add_argument("--index", default=None, help="Path to output index JSON")
    parser.add_argument("--figures-dir", default=None, help="Directory to extract figures to")
    args = parser.parse_args()

    epub_path = Path(args.epub)
    if not epub_path.is_file():
        raise SystemExit(f"missing book: {epub_path}")

    if args.book_id:
        book_id = args.book_id
    elif str(epub_path.resolve()) != str(BOOK.resolve()):
        book_id = epub_path.stem
    else:
        book_id = "fde"

    if args.index:
        index_path = Path(args.index)
    elif book_id != "fde":
        index_path = ROOT / "data" / f"index.{book_id}.json"
    else:
        index_path = INDEX

    if args.figures_dir:
        figures_dir = Path(args.figures_dir)
    elif book_id != "fde":
        figures_dir = ROOT / "data" / "figures" / book_id
    else:
        figures_dir = FIGURES

    if figures_dir.is_dir():
        for old in figures_dir.iterdir():
            if old.is_file():
                old.unlink()
    figures_dir.mkdir(parents=True, exist_ok=True)

    index = ingest_epub(epub_path, figures_dir, write_images=True, book_id=book_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    update_books_catalog(
        book_id,
        index.get("title", ""),
        index.get("author", ""),
        index_path,
        figures_dir,
        index.get("chunks", []),
        index.get("figures", []),
        cover_file=index.get("cover_file", "cover.png"),
    )

    reloaded = json.loads(index_path.read_text(encoding="utf-8"))
    captions = [f["caption"] for f in reloaded["figures"] if f["caption"]][:3]
    print(f"chunks {len(reloaded['chunks'])}")
    print(f"figures {len(reloaded['figures'])}")
    for caption in captions:
        print(f"caption: {caption}")


if __name__ == "__main__":
    main()
