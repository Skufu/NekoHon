_INDEX_MAPS = {}


def _index_maps(index):
    chunks = index.get("chunks") or []
    entry = _INDEX_MAPS.get(id(index))
    if entry is not None and entry[0] is index and entry[1] is chunks and entry[2] == len(chunks):
        return entry[3], entry[4], entry[5]
    by_id = {}
    pos = {}
    by_chapter = {}
    for i, c in enumerate(chunks):
        cid = c.get("chunk_id")
        by_id.setdefault(cid, c)
        pos.setdefault(cid, i)
        by_chapter.setdefault(str(c.get("chapter")), []).append(c)
    if len(_INDEX_MAPS) >= 8:
        _INDEX_MAPS.clear()
    _INDEX_MAPS[id(index)] = (index, chunks, len(chunks), by_id, pos, by_chapter)
    return by_id, pos, by_chapter


def chunk_by_id(index, chunk_id, default=None):
    try:
        return _index_maps(index)[0].get(chunk_id, default)
    except TypeError:
        return default


def chunk_position(index, chunk_id):
    try:
        return _index_maps(index)[1].get(chunk_id)
    except TypeError:
        return None


def chapter_neighbors(index, chapter, lead_chunk_id, limit=4):
    pool = _index_maps(index)[2].get(chapter, ())
    return [c for c in pool if c.get("chunk_id") != lead_chunk_id][:limit]
