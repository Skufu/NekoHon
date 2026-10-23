import functools
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "data" / "figures"

FIGURE_RE = re.compile(r"\b(?:Figure|Fig\.)\s+([A-Z]?\d+[-.]\d+)\b", re.I)
NUMBER_RE = re.compile(r"(?:figure-|fig-)?([a-z]?\d+[-.]\d+)", re.I)


@functools.lru_cache(maxsize=4096)
def _cited_numbers_cached(text):
    return frozenset(
        match.group(1).lower().replace(".", "-")
        for match in FIGURE_RE.finditer(text or "")
    )


def cited_numbers(text):
    return set(_cited_numbers_cached(text or ""))


@functools.lru_cache(maxsize=512)
def number_from_id(figure_id):
    match = NUMBER_RE.search(figure_id or "")
    return match.group(1).lower().replace(".", "-") if match else ""


_FIG_PATH_CACHE = {}


def _figure_path_and_src(figure, figures_dir, book_id=None):
    file_name = figure.get("file") or ""
    cache_key = (file_name, str(figures_dir), book_id)
    if cache_key in _FIG_PATH_CACHE:
        return _FIG_PATH_CACHE[cache_key]

    if not file_name:
        src = figure.get("src") or (f"/figures/{figure['id']}?book_id={book_id}" if book_id else f"/figures/{figure['id']}")
        res = (None, src)
        _FIG_PATH_CACHE[cache_key] = res
        return res

    fig_path = None
    if (figures_dir / file_name).is_file():
        fig_path = figures_dir / file_name
    elif book_id and (figures_dir / book_id / file_name).is_file():
        fig_path = figures_dir / book_id / file_name
    elif book_id and (FIGURES / book_id / file_name).is_file():
        fig_path = FIGURES / book_id / file_name
    elif (FIGURES / file_name).is_file():
        fig_path = FIGURES / file_name
    else:
        for root in (figures_dir, FIGURES):
            if root.is_dir():
                for child in root.iterdir():
                    if child.is_dir() and (child / file_name).is_file():
                        fig_path = child / file_name
                        break
            if fig_path:
                break

    src = figure.get("src")
    if not src:
        if fig_path:
            if fig_path.parent != FIGURES and fig_path.parent.parent == FIGURES:
                src = f"/figures/{figure['id']}?book_id={fig_path.parent.name}"
            elif figures_dir != FIGURES and figures_dir.parent == FIGURES and fig_path.parent == figures_dir:
                src = f"/figures/{figure['id']}?book_id={figures_dir.name}"
            elif book_id and (figures_dir / book_id / file_name).is_file():
                src = f"/figures/{figure['id']}?book_id={book_id}"
            else:
                src = f"/figures/{figure['id']}"
        else:
            if book_id and (figures_dir / file_name).is_file():
                src = f"/figures/{figure['id']}"
            elif book_id:
                src = f"/figures/{figure['id']}?book_id={book_id}"
            else:
                src = f"/figures/{figure['id']}"

    res = (fig_path, src)
    _FIG_PATH_CACHE[cache_key] = res
    return res


def figures_for(passages, figures, limit=5, figures_dir=None, book_id=None):
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
        fig_path, src = _figure_path_and_src(figure, figures_dir, book_id=book_id)
        if not fig_path or not fig_path.is_file():
            continue
        seen.add(figure["id"])
        attached.append({
            "id": figure["id"],
            "chapter": str(figure.get("chapter", "")),
            "caption": figure.get("caption") or "",
            "src": src,
        })
    return attached


def _png_size(path):
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def figure_cards(ids, figures, figures_dir=None, book_id=None):
    figures_dir = Path(figures_dir) if figures_dir else FIGURES
    by_id = {figure.get("id"): figure for figure in figures or []}
    cards = []
    for figure_id in ids or []:
        figure = by_id.get(figure_id)
        if figure is None:
            continue
        fig_path, src = _figure_path_and_src(figure, figures_dir, book_id=book_id)
        card = {
            "id": figure_id,
            "chapter": str(figure.get("chapter", "")),
            "caption": figure.get("caption") or "",
            "src": src,
        }
        size = None
        if fig_path and fig_path.is_file():
            size = _png_size(fig_path)
        elif (figures_dir / (figure.get("file") or "")).is_file():
            size = _png_size(figures_dir / (figure.get("file") or ""))
        if size is not None:
            card["width"], card["height"] = size
        cards.append(card)
    return cards


def figure_file(figure_id, figures, figures_dir=None):
    figures_dir = Path(figures_dir) if figures_dir else FIGURES
    for figure in figures:
        if figure.get("id") == figure_id:
            file_name = figure.get("file") or ""
            path = figures_dir / file_name
            if path.is_file():
                return path
            if (FIGURES / file_name).is_file():
                return FIGURES / file_name
            for root in (figures_dir, FIGURES):
                if root.is_dir():
                    for child in root.iterdir():
                        if child.is_dir() and (child / file_name).is_file():
                            return child / file_name
    return None
