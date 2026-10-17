"""Attach a figure when a kept passage names it.

The answer still must not describe the pixels. This module only names the file.
"""

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIGURES = ROOT / "data" / "figures"

FIGURE_RE = re.compile(r"\b(?:Figure|Fig\.)\s+([A-Z]?\d+-\d+)\b", re.I)
# Same token cited_numbers emits, so figure-a1-2 attaches to "Figure A1-2"
# and does not collide with figure-1-2.
NUMBER_RE = re.compile(r"(?:figure-|fig-)?([a-z]?\d+-\d+)", re.I)


def cited_numbers(text):
    return {match.group(1).lower() for match in FIGURE_RE.finditer(text or "")}


def number_from_id(figure_id):
    """The figure number a passage would cite, letter prefix included.

    `figure-a1-2` and `figure-1-2` stay distinct. A bare `1-2` still matches.
    """
    match = NUMBER_RE.search(figure_id or "")
    return match.group(1).lower() if match else ""


def figures_for(passages, figures, limit=5, figures_dir=None):
    """A figure attaches only if a top passage names its number.

    The embedding score floor is not set. Do not attach by vector score.
    """
    named = set()
    for hit in passages[:limit]:
        named.update(cited_numbers(hit.get("text")))
        named.update(cited_numbers(hit.get("quote")))
    figures_dir = Path(figures_dir) if figures_dir else FIGURES
    attached = []
    seen = set()
    for figure in figures:
        number = number_from_id(figure.get("id"))
        if not number or number not in named or figure["id"] in seen:
            continue
        file_name = figure.get("file") or ""
        if not file_name or not (figures_dir / file_name).is_file():
            continue
        seen.add(figure["id"])
        attached.append({
            "id": figure["id"],
            "chapter": str(figure.get("chapter", "")),
            "caption": figure.get("caption") or "",
            "src": "/figures/" + figure["id"],
        })
    return attached


def _png_size(path):
    """(width, height) from a PNG header, or None. No decode, stdlib only."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def figure_cards(ids, figures, figures_dir=None):
    """The reader's figures: every id the chunk carries, caption, src, size.

    Unlike figures_for, nothing is gated on the passage naming the figure —
    the reader shows what the chunk holds. width/height come from the PNG
    header so the pane can reserve the aspect and never jump on load.
    """
    figures_dir = Path(figures_dir) if figures_dir else FIGURES
    by_id = {figure.get("id"): figure for figure in figures or []}
    cards = []
    for figure_id in ids or []:
        figure = by_id.get(figure_id)
        if figure is None:
            continue
        card = {
            "id": figure_id,
            "chapter": str(figure.get("chapter", "")),
            "caption": figure.get("caption") or "",
            "src": "/figures/" + str(figure_id),
        }
        size = _png_size(figures_dir / (figure.get("file") or ""))
        if size is not None:
            card["width"], card["height"] = size
        cards.append(card)
    return cards


def figure_file(figure_id, figures):
    for figure in figures:
        if figure.get("id") == figure_id:
            file_name = figure.get("file") or ""
            path = FIGURES / file_name
            if path.is_file():
                return path
    return None
