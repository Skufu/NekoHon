"""Unit tests for named technical anchor gating.

Guards:
- Unknown named protocols, theorems, or comparative contrasts must refuse before generation.
- Known technical terms in the book (including lowercase snake_case like data_lake) must not be falsely refused.
- CamelCase and uppercase acronyms absent from the book must refuse.
- Typo single-token identifiers within edit distance 1 of in-book terms must not refuse.
- Generalization: logic operates on abstract indexes, without hardcoded book IDs.
"""

import unittest

import answer as A

SYNTHETIC_INDEX = {
    "book_id": "test_domain",
    "figures": [],
    "chunks": [
        {
            "chunk_id": "test-001",
            "chapter": "1",
            "heading": "Quantum Decoherence",
            "text": "The Lindy effect applies to classical hardware architectures. Shor's algorithm provides polynomial-time factoring on fault-tolerant quantum computers. Apache Hudi handles streaming data lakes and data_lake storage. CRUD operations manage application state.",
        },
        {
            "chunk_id": "test-002",
            "chapter": "2",
            "heading": "Compiler Passes",
            "text": "DeadCodeElimination removes unused SSA instructions. During optimization, ConstantPropagation folds static values.",
        },
    ],
}


class TechnicalAnchorRefusalTest(unittest.TestCase):
    def test_unmentioned_phrase_anchor_refuses(self):
        # Named protocol absent from synthetic index
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What safety guarantees does the Raft Pre-Vote protocol phase ensure?",
            )
        )
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What parity condition does Kawasaki's theorem state?",
            )
        )

    def test_mentioned_phrase_anchor_does_not_refuse(self):
        # Lindy effect is present in chunk test-001
        self.assertFalse(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What principle does the Lindy effect describe?",
            )
        )
        # Shor's algorithm is present in chunk test-001
        self.assertFalse(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "How does Shor's algorithm factor numbers?",
            )
        )

    def test_unmentioned_mixed_case_or_acronym_refuses(self):
        # QuIP# absent from synthetic index
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "How does QuIP# apply randomized orthogonal transformations?",
            )
        )
        # RuBisCO absent from synthetic index
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "Which RuBisCO enzyme catalyzes carbon fixation?",
            )
        )
        # ZooKeeper absent from synthetic index
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "How does ZooKeeper maintain epoch numbers?",
            )
        )
        # Absent TitleCase anchor
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What does Cassandra Ring mean in distributed systems?",
            )
        )

    def test_mentioned_mixed_case_and_valid_acronym_does_not_refuse(self):
        # DeadCodeElimination is present in chunk test-002
        self.assertFalse(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "How does DeadCodeElimination optimize code?",
            )
        )
        # CRUD acronym is present in chunk test-001
        self.assertFalse(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What operations are defined in CRUD?",
            )
        )

    def test_snake_case_data_lake_does_not_refuse(self):
        # Lowercase snake_case identifier must never be matched as absent proper identifier
        self.assertFalse(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What does data_lake mean?",
            )
        )

    def test_typo_within_edit_distance_does_not_refuse(self):
        # DeadCodeEliminaton is edit-distance 1 from DeadCodeElimination
        self.assertFalse(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "What is DeadCodeEliminaton?",
            )
        )

    def test_unmentioned_comparative_contrast_refuses(self):
        # Both two-phase commit and two-phase locking are absent from synthetic index
        self.assertTrue(
            A.has_unmentioned_technical_anchor(
                SYNTHETIC_INDEX,
                "How do two-phase commit and two-phase locking differ fundamentally in their purpose?",
            )
        )


if __name__ == "__main__":
    unittest.main()
