"""Phase 2 ingest. Tiny fake EPUB, not the real book."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from engine.ingest import _chapter_number, ingest_epub

CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<body>
<section>
<h1>Chapter 7. Ingestion</h1>
<p>Change data capture streams row-level database changes.</p>
<h2>Batch and streaming</h2>
<p>See <a data-type="xref" href="#fig-7-3">Figure 7-3</a> for the split.</p>
<figure><div class="figure" id="fig-7-3">
<img alt="" src="images/fig-7-3.png"/>
<h6><span class="label">Figure 7-3. </span>Batch and streaming ingestion.</h6>
</div></figure>
<table>
<caption>Table 7-1. Patterns</caption>
<tr><td>batch</td><td>once a day</td></tr>
<tr><td>stream</td><td>row by row</td></tr>
</table>
</section>
</body>
</html>
"""

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<metadata/>
<manifest>
<item id="ch07" href="ch07.html" media-type="application/xhtml+xml"/>
<item id="fig" href="images/fig-7-3.png" media-type="image/png"/>
</manifest>
<spine>
<itemref idref="ch07"/>
</spine>
</package>
"""

# 1x1 png
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_epub(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/ch07.html", CHAPTER)
        zf.writestr("OEBPS/images/fig-7-3.png", PNG)


class IngestTests(unittest.TestCase):
    def test_fake_epub_keeps_table_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            epub = tmp / "fake.epub"
            figures = tmp / "figures"
            _write_epub(epub)
            index = ingest_epub(epub, figures, write_images=True)
            # Keyed by figure id, not the zip basename, so two chapters that
            # both ship images/fig.png do not overwrite each other.
            written_name = index["figures"][0]["file"]
            image_written = written_name != "fig-7-3.png" and (figures / written_name).is_file()

        self.assertGreater(len(index["chunks"]), 0)
        tables = [c for c in index["chunks"] if "batch" in c["text"] and "stream" in c["text"]]
        self.assertEqual(len(tables), 1)
        self.assertIn("once a day", tables[0]["text"])
        self.assertIn("row by row", tables[0]["text"])
        self.assertTrue(tables[0]["text"].startswith("Batch and streaming"))

        cited = [c for c in index["chunks"] if "Figure 7-3" in c["text"]]
        self.assertEqual(len(cited), 1)
        self.assertNotIn("fig-7-3", cited[0]["text"])
        self.assertNotIn("\x00", cited[0]["text"])

        self.assertEqual(len(index["figures"]), 1)
        figure = index["figures"][0]
        for key in ("id", "chapter", "caption", "referencing_paragraph", "file"):
            self.assertIn(key, figure)
        self.assertEqual(figure["caption"], "Batch and streaming ingestion.")
        self.assertIn("Figure 7-3", figure["referencing_paragraph"])
        self.assertEqual(figure["chapter"], "7")
        self.assertTrue(image_written)

    def test_every_chunk_carries_where_it_came_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "fake.epub"
            _write_epub(epub)
            index = ingest_epub(epub, None, write_images=False)

        for chunk in index["chunks"]:
            self.assertEqual(chunk["doc"], "OEBPS/ch07.html")
            self.assertTrue(chunk["section"].startswith("Chapter 7. Ingestion"))
            self.assertIn("anchor", chunk)
            self.assertIn("figures", chunk)

        cited = [c for c in index["chunks"] if "Figure 7-3" in c["text"]][0]
        self.assertEqual(cited["figures"], ["figure-7-3"])
        plain = [c for c in index["chunks"] if "Figure 7-3" not in c["text"]][0]
        self.assertEqual(plain["figures"], [])

    def test_the_trail_is_metadata_and_never_joins_the_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "fake.epub"
            _write_epub(epub)
            index = ingest_epub(epub, None, write_images=False)

        for chunk in index["chunks"]:
            if " > " in chunk["section"]:
                self.assertNotIn(chunk["section"], chunk["text"])
        # The table sits under the h2, so its trail holds both headings.
        tables = [c for c in index["chunks"] if "row by row" in c["text"]][0]
        self.assertEqual(
            tables["section"], "Chapter 7. Ingestion > Batch and streaming"
        )
        self.assertTrue(tables["text"].startswith("Batch and streaming"))


class ChapterNumberTests(unittest.TestCase):
    def test_doc_ids_like_chapter_4_keep_only_the_number(self):
        # The second book's spine ids are `chapter-4` (measured 2026-10-14):
        # the prompt tag must read `[Ch. 4]`, not `[Ch. chapter-4]`.
        self.assertEqual(_chapter_number("chapter-4", ""), "4")
        self.assertEqual(_chapter_number("chapter-12", ""), "12")

    def test_doc_ids_like_ch07_keep_only_the_number(self):
        self.assertEqual(_chapter_number("ch07", ""), "7")

    def test_a_doc_id_without_a_number_is_left_alone(self):
        self.assertEqual(_chapter_number("cover", ""), "cover")

    def test_the_heading_fallback_still_reads_the_label(self):
        self.assertEqual(_chapter_number("part1", "<h1>Chapter 5. CRUD</h1>"), "5")


if __name__ == "__main__":
    unittest.main()
