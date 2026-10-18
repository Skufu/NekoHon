"""Unit tests for DEFECT-1 (keywords.postings immutability & cache ratio)
and DEFECT-2 (scripts/launch.py safe port hygiene).
"""

import os
import sys
import time
import types
import unittest
from unittest.mock import MagicMock, patch

from keywords import _PostingPositions, postings
from scripts.launch import clear_port_8000, is_server_process


def make_sample_index(num_chunks=30):
    chunks = [
        {
            "chunk_id": f"c_{i}",
            "chapter": str(i // 5 + 1),
            "heading": f"Section {i}",
            "text": f"This is chunk number {i} discussing distributed systems, storage, and networks with keyword_{i % 7}."
        }
        for i in range(num_chunks)
    ]
    return {"chunks": chunks, "figures": []}


class TestPostingsImmutabilityAndPerf(unittest.TestCase):
    def test_postings_returns_mapping_proxy(self):
        index = make_sample_index(5)
        table = postings(index)
        self.assertIsInstance(table, types.MappingProxyType)

    def test_mutation_of_returned_mapping_raises_type_error(self):
        index = make_sample_index(5)
        table = postings(index)
        with self.assertRaises(TypeError):
            table["new_term"] = (0,)
        with self.assertRaises(TypeError):
            del table[next(iter(table))]

    def test_mutation_of_posting_value_raises_type_error(self):
        index = make_sample_index(5)
        table = postings(index)
        first_word = next(iter(table))
        pos_tuple = table[first_word]
        self.assertIsInstance(pos_tuple, tuple)
        with self.assertRaises(TypeError):
            pos_tuple[0] = 999
        with self.assertRaises(TypeError):
            del pos_tuple[0]

    def test_posting_positions_equality_contract(self):
        pos = _PostingPositions([0, 2])
        self.assertEqual(pos, [0, 2])
        self.assertEqual(pos, (0, 2))
        self.assertEqual([0, 2], pos)
        self.assertEqual((0, 2), pos)
        self.assertNotEqual(pos, [0, 1])

    def test_repeated_calls_return_identical_content_and_identity(self):
        index = make_sample_index(10)
        table1 = postings(index)
        table2 = postings(index)
        self.assertIs(table1, table2)
        self.assertEqual(dict(table1), dict(table2))

    def test_postings_cached_time_under_sane_bound_ratio(self):
        index = make_sample_index(50)
        # Cold build / rebuild without using cached _postings:
        rebuild_index = {"chunks": list(index["chunks"])}
        t0 = time.perf_counter()
        postings(rebuild_index)
        t_rebuild = max(time.perf_counter() - t0, 1e-6)

        # Repeated cached calls:
        iterations = 1000
        t0 = time.perf_counter()
        for _ in range(iterations):
            _ = postings(rebuild_index)
        t_cached_total = time.perf_counter() - t0
        t_cached_per_call = t_cached_total / iterations

        ratio = t_cached_per_call / t_rebuild
        # Cached lookup must be at least 10x faster than rebuild (ratio < 0.10)
        self.assertLess(
            ratio,
            0.10,
            f"Cached call was too slow relative to rebuild: ratio={ratio:.5f} (rebuild={t_rebuild*1e3:.3f}ms, cached={t_cached_per_call*1e3:.5f}ms)",
        )


class TestLaunchPortHygiene(unittest.TestCase):
    def test_is_server_process_identifies_python_server(self):
        self.assertTrue(is_server_process("python server.py"))
        self.assertTrue(is_server_process("python.exe server.py"))
        self.assertTrue(is_server_process('"C:\\Python312\\python.exe" server.py --open'))
        self.assertTrue(is_server_process("/usr/bin/python3 /repo/server.py --block-warmup"))

    def test_is_server_process_rejects_non_server(self):
        self.assertFalse(is_server_process("node server.js"))
        self.assertFalse(is_server_process("nginx: master process"))
        self.assertFalse(is_server_process("python background_worker.py"))
        self.assertFalse(is_server_process(""))
        self.assertFalse(is_server_process(None))

    @patch("scripts.launch.find_listening_pids", return_value=[12345])
    @patch("scripts.launch.get_process_cmdline", return_value="node index.js")
    @patch("subprocess.run")
    def test_clear_port_refuses_to_kill_non_server_process(self, mock_run, mock_cmdline, mock_pids):
        with self.assertRaises(SystemExit) as cm:
            clear_port_8000(port=8000, dry_run=False)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @patch("scripts.launch.find_listening_pids", return_value=[12345])
    @patch("scripts.launch.get_process_cmdline", return_value="python.exe server.py")
    @patch("subprocess.run")
    def test_clear_port_dry_run_does_not_kill_server(self, mock_run, mock_cmdline, mock_pids):
        clear_port_8000(port=8000, dry_run=True)
        mock_run.assert_not_called()

    @patch("scripts.launch.find_listening_pids", return_value=[12345])
    @patch("scripts.launch.get_process_cmdline", return_value="python.exe server.py")
    @patch("subprocess.run")
    def test_clear_port_kills_verified_server_process(self, mock_run, mock_cmdline, mock_pids):
        clear_port_8000(port=8000, dry_run=False)
        mock_run.assert_called_once()

    @patch("scripts.launch.find_listening_pids", return_value=[])
    def test_clear_port_respects_env_var(self, mock_pids):
        with patch.dict(os.environ, {"PORT": "8443"}):
            clear_port_8000()
            mock_pids.assert_called_with(8443)


if __name__ == "__main__":
    unittest.main()
