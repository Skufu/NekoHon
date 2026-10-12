"""Caption-seeded recall checks. Fake embedder. No Ollama."""

import unittest

from captions import caption_seed


def fake_embed(texts, model):
    vectors = []
    for text in texts:
        lowered = text.lower()
        if "mad" in lowered or "turck" in lowered:
            vectors.append([1.0, 0.0])
        elif "data mesh" in lowered:
            vectors.append([0.0, 1.0])
        else:
            vectors.append([0.5, 0.5])
    return vectors


def chunk(chunk_id, text, vector):
    return {
        "chunk_id": chunk_id,
        "chapter": "4",
        "heading": "",
        "text": text,
        "embedding": vector,
    }


def figure(figure_id, caption, vector):
    return {
        "id": figure_id,
        "chapter": "4",
        "caption": caption,
        "embedding": vector,
    }


def passage(chunk_id, score):
    return {
        "chunk_id": chunk_id,
        "chapter": "4",
        "heading": "",
        "text": "",
        "source": "",
        "score": score,
    }


def mad_index(figures):
    return {
        "chunks": [
            chunk("ch03-102", "Data Mesh\nThe data mesh is a recent response.", [0.0, 1.0]),
            chunk("ch04-019", "Knockout was popular (Figure 4-1).", [0.7, 0.3]),
            chunk(
                "ch04-020",
                "Matt Turck's depictions of the ML, AI, and data (MAD) landscape (Figure 4-1).",
                [1.0, 0.0],
            ),
        ],
        "figures": figures,
    }


DENSE = [
    passage("ch03-102", 0.671),
    passage("ch02-037", 0.63),
    passage("ch03-112", 0.63),
    passage("ch11-021", 0.628),
    passage("ch03-087", 0.628),
]


class CaptionSeedTests(unittest.TestCase):
    def test_a_strong_caption_seeds_the_naming_chunk(self):
        figures = [figure("figure-4-1", "Matt Turck's 2021 MAD data landscape", [1.0, 0.0])]
        seeded = caption_seed(
            mad_index(figures), "MAD data landscape", DENSE, embed_fn=fake_embed
        )
        self.assertEqual(seeded[0]["chunk_id"], "ch04-020")
        self.assertEqual(seeded[0]["score"], 1.0)
        self.assertEqual(len(seeded), len(DENSE))
        self.assertEqual([hit["chunk_id"] for hit in seeded[1:]],
                         [hit["chunk_id"] for hit in DENSE[:-1]])

    def test_the_naming_chunk_is_chosen_by_relevance_not_position(self):
        figures = [figure("figure-4-1", "Matt Turck's 2021 MAD data landscape", [1.0, 0.0])]
        seeded = caption_seed(
            mad_index(figures), "MAD data landscape", DENSE, embed_fn=fake_embed
        )
        self.assertNotEqual(seeded[0]["chunk_id"], "ch04-019")

    def test_a_weak_caption_leaves_everything_alone(self):
        figures = [figure("figure-4-1", "Matt Turck's 2021 MAD data landscape", [0.2, 0.98])]
        seeded = caption_seed(
            mad_index(figures), "MAD data landscape", DENSE, embed_fn=fake_embed
        )
        self.assertEqual(seeded, DENSE)

    def test_a_present_chunk_is_not_duplicated(self):
        figures = [figure("figure-4-1", "Matt Turck's 2021 MAD data landscape", [1.0, 0.0])]
        passages = [passage("ch04-020", 0.9)] + DENSE[:4]
        seeded = caption_seed(
            mad_index(figures), "MAD data landscape", passages, embed_fn=fake_embed
        )
        self.assertEqual(seeded, passages)

    def test_a_figure_without_a_naming_chunk_is_ignored(self):
        figures = [figure("figure-9-9", "Some other figure", [1.0, 0.0])]
        seeded = caption_seed(
            mad_index(figures), "MAD data landscape", DENSE, embed_fn=fake_embed
        )
        self.assertEqual(seeded, DENSE)

    def test_no_figures_never_embeds(self):
        def refuse(*args, **kwargs):
            raise AssertionError("must not embed without figures")

        seeded = caption_seed(
            mad_index([]), "MAD data landscape", DENSE, embed_fn=refuse
        )
        self.assertEqual(seeded, DENSE)


if __name__ == "__main__":
    unittest.main()
