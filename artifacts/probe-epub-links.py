"""Does the EPUB carry the links the user remembers? Look at the raw XHTML
around the MAD pointer and the nonrelational passage: internal anchors,
hrefs, and figure links.

Run: python artifacts/probe-epub-links.py
Writes artifacts/probe-epub-links.log
"""

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

EPUB = ROOT / "books" / "fde.epub"
MARKERS = ["MAD) landscape", "Enter nonrelational or NoSQL databases", "Figure 4-1"]


def main():
    lines = []
    with zipfile.ZipFile(EPUB) as archive:
        names = [n for n in archive.namelist() if n.endswith((".xhtml", ".html", ".htm"))]
        lines.append(f"content files: {len(names)}")
        for marker in MARKERS:
            lines.append(f"\n== marker: {marker!r}")
            hits = 0
            for name in names:
                text = archive.read(name).decode("utf-8", errors="replace")
                for match in re.finditer(re.escape(marker), text):
                    hits += 1
                    if hits > 2:
                        break
                    start = max(0, match.start() - 450)
                    end = min(len(text), match.end() + 250)
                    window = text[start:end]
                    lines.append(f"--- {name} @ {match.start()}")
                    lines.append(window)
                    lines.append("")
                if hits > 2:
                    break
            if not hits:
                lines.append("   (no hit)")
        links = 0
        anchors = 0
        for name in names:
            text = archive.read(name).decode("utf-8", errors="replace")
            links += len(re.findall(r"<a\s[^>]*href=", text, re.I))
            anchors += len(re.findall(r'<[^>]*\sid="', text, re.I))
        lines.append(f"total <a href=> across content: {links}; id= anchors: {anchors}")
    log = "\n".join(lines)
    (HERE / "probe-epub-links.log").write_text(log, encoding="utf-8")
    print(log)


if __name__ == "__main__":
    main()
