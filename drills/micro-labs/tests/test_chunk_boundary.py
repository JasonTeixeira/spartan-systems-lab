"""Boundary-aware word counts must agree with the whole-input oracle."""

import importlib.util
import random
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "chunk_boundary", ROOT / "labs/chunk-boundary/system.py"
)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class ChunkBoundaryTests(unittest.TestCase):
    def test_exact_source_counterexample(self):
        r = M.analyze(M.EXAMPLE, 20)
        self.assertEqual(r["naive_words"], 16)
        self.assertEqual(r["whole_words"], 15)
        self.assertEqual(r["repaired_words"], 15)
        self.assertEqual(len(r["chunks"]), 4)
        self.assertEqual(r["chunks"][2][-2:], "fa")
        self.assertTrue(r["chunks"][3].startswith("r"))

    def test_every_size_including_word_in_many_chunks(self):
        for text in ["", " ", "alphabetical", " ab cd ", "a\tb\ncc", "é🙂\u2003z", "a" * 300]:
            for size in range(1, 45):
                r = M.analyze(text, size)
                self.assertEqual(r["repaired_words"], len(re.findall(r"\S+", text)))
                self.assertEqual("".join(r["chunks"]), text)

    def test_summary_associativity_and_identity(self):
        samples = ["", "a", " ", "b c", "\n", "xy", "\t z"]
        for a in samples:
            for b in samples:
                for c in samples:
                    x, y, z = map(M.summarize, (a, b, c))
                    self.assertEqual(M.merge(M.merge(x, y), z), M.merge(x, M.merge(y, z)))
                    self.assertEqual(M.merge(x, y), M.summarize(a + b))

    def test_reordered_chunks_can_change_count(self):
        chunks = ["a", " ", "b"]
        good = M.reduce_chunks(chunks)
        changed = M.reduce_chunks(["a", "b", " "])
        self.assertEqual(good["words"], 2)
        self.assertEqual(changed["words"], 1)

    def test_random_partitions_changed_inputs(self):
        rng = random.Random(91)
        for _ in range(100):
            text = "".join(rng.choice("ab \t\n🙂") for _ in range(rng.randrange(200)))
            r = M.analyze(text, rng.randrange(1, 30))
            self.assertEqual(r["repaired_words"], len(re.findall(r"\S+", text)))

    def test_invalid_input_rejected(self):
        for text, size in [
            (None, 2),
            ("x", True),
            ("x", 0),
            ("x", 257),
            ("x" * 4097, 4),
            ("x", 1.5),
            ("\ud800", 1),
            ("\udfff", 2),
        ]:
            with self.assertRaises(ValueError) as error:
                M.analyze(text, size)
            self.assertIs(type(error.exception), ValueError)


if __name__ == "__main__":
    unittest.main()
