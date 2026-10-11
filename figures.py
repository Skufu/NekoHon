"""Attach a figure when a kept passage names it. Phase 5.

The answer still must not describe the pixels. This module only names the file.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIGURES = ROOT / "data" / "figures"

FIGURE_RE = re.compile(r"\b(?:Figure|Fig\.)\s+([A-Z]?\d+-\d+)\b", re.I)


def cited_numbers(text):
    return {match.group(1).lower() for match in FIGURE_RE.finditer(text or "")}


def _number_from_id(figure_id):
    match = re.search(r"(\d+-\d+)", figure_id or "")
    return match.group(1) if match else ""


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
        number = _number_from_id(figure.get("id"))
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


def figure_file(figure_id, figures):
    for figure in figures:
        if figure.get("id") == figure_id:
            file_name = figure.get("file") or ""
            path = FIGURES / file_name
            if path.is_file():
                return path
    return None
