"""Phase 5. A figure attaches only when a passage names it."""

import tempfile
import unittest
from pathlib import Path

from figures import figures_for

FIGURES = [
    {
        "id": "figure-8-8",
        "chapter": "8",
        "caption": "A watermark marks late data.",
        "file": "fode_0808.png",
    },
    {
        "id": "figure-2-1",
        "chapter": "2",
        "caption": "Not named here.",
        "file": "fode_0201.png",
    },
]


class FigureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / "fode_0808.png").write_bytes(b"png")
        (self.folder / "fode_0201.png").write_bytes(b"png")

    def tearDown(self):
        self.tmp.cleanup()

    def test_named_figure_attaches(self):
        passages = [{
            "text": "A watermark (Figure 8-8) is a threshold used by a window.",
            "quote": "A watermark (Figure 8-8) is a threshold used by a window.",
        }]
        attached = figures_for(passages, FIGURES, figures_dir=self.folder)
        self.assertEqual([item["id"] for item in attached], ["figure-8-8"])
        self.assertEqual(attached[0]["src"], "/figures/figure-8-8")

    def test_unnamed_figure_stays_off(self):
        passages = [{"text": "CRUD stands for create, read, update, and delete.", "quote": ""}]
        self.assertEqual(figures_for(passages, FIGURES, figures_dir=self.folder), [])

    def test_embedding_score_does_not_attach_a_figure(self):
        passages = [{"text": "No figure number here.", "quote": "", "score": 0.99}]
        self.assertEqual(figures_for(passages, FIGURES, figures_dir=self.folder), [])


if __name__ == "__main__":
    unittest.main()
