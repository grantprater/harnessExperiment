"""Unit tests for upgraded perception engine."""
import unittest
from pathlib import Path
import tempfile

from perception import (
    extract_outline,
    extract_symbol,
    extract_elastic,
    find_symbol_topology,
    extract_contract_skeleton,
    inspect_region,
    list_symbols,
    strip_header_boilerplate
)

SAMPLE_CODE = """# Copyright (c) 2026 Test Organization
# All rights reserved.
# SPDX-License-Identifier: MIT
\"\"\"Module for sample math operations.\"\"\"

from dataclasses import dataclass

MAX_LIMIT = 1000

@dataclass
class Vector2D:
    \"\"\"Represents a 2D vector.\"\"\"
    x: float
    y: float

    def magnitude(self) -> float:
        \"\"\"Calculate Euclidean length.\"\"\"
        return (self.x ** 2 + self.y ** 2) ** 0.5


def add_numbers(a: int, b: int) -> int:
    \"\"\"Add two numbers safely.\"\"\"
    # invariant check
    if a > MAX_LIMIT:
        raise ValueError("Too large")
    return a + b

async def async_fetch(item_id: str) -> dict:
    \"\"\"Fetch item asynchronously.\"\"\"
    return {"id": item_id}
"""


class PerceptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temp_dir.name) / "sample.py"
        self.file_path.write_text(SAMPLE_CODE, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_strip_header_boilerplate(self):
        cleaned, count = strip_header_boilerplate(SAMPLE_CODE)
        self.assertGreater(count, 0)
        self.assertNotIn("Copyright", cleaned)
        self.assertTrue(cleaned.startswith('"""Module for sample math operations."""'))

    def test_list_symbols(self):
        symbols = list_symbols(self.file_path)
        names = [s.name for s in symbols]
        self.assertIn("Vector2D", names)
        self.assertIn("Vector2D.magnitude", names)
        self.assertIn("add_numbers", names)
        self.assertIn("async_fetch", names)

    def test_extract_outline_semantic(self):
        outline = extract_outline(self.file_path, mode="semantic", inline_small=False)
        self.assertIn("class Vector2D", outline)
        self.assertIn("Represents a 2D vector...", outline)
        self.assertIn("def add_numbers(a: int, b: int) -> int", outline)
        self.assertIn("async def async_fetch", outline)

    def test_extract_outline_bare(self):
        outline = extract_outline(self.file_path, mode="bare", inline_small=False)
        self.assertIn("class Vector2D", outline)
        self.assertNotIn("Represents a 2D vector", outline)
        self.assertNotIn("Add two numbers safely", outline)

    def test_extract_outline_folded(self):
        outline = extract_outline(self.file_path, mode="folded", inline_small=False)
        self.assertIn("MAX_LIMIT = 1000", outline)
        self.assertIn("class Vector2D", outline)

    def test_extract_outline_auto_inlining(self):
        # File is 35 lines <= default threshold (50)
        outline = extract_outline(self.file_path, inline_small=True, inline_threshold=50)
        self.assertIn("Full source shown", outline)
        self.assertIn("def magnitude(self) -> float:", outline)
        self.assertIn("return (self.x ** 2 + self.y ** 2) ** 0.5", outline)

    def test_extract_symbol_function(self):
        view = extract_symbol(self.file_path, "add_numbers")
        self.assertIn("def add_numbers(a: int, b: int) -> int:", view)
        self.assertIn("return a + b", view)

    def test_extract_symbol_method(self):
        view = extract_symbol(self.file_path, "Vector2D.magnitude")
        self.assertIn("def magnitude(self) -> float:", view)
        self.assertIn("return (self.x ** 2 + self.y ** 2) ** 0.5", view)

    def test_extract_symbol_short_method_lookup(self):
        view = extract_symbol(self.file_path, "magnitude")
        self.assertIn("def magnitude(self) -> float:", view)

    def test_inspect_region(self):
        region = inspect_region(self.file_path, 10, 15)
        self.assertIn("Vector2D", region)
        self.assertIn("Saccade View", region)

    def test_extract_elastic_overview(self):
        elastic = extract_elastic(self.file_path)
        self.assertIn("from dataclasses import dataclass", elastic)
        self.assertIn("MAX_LIMIT = 1000", elastic)
        self.assertIn("lines folded", elastic)

    def test_extract_elastic_target_focus(self):
        elastic = extract_elastic(self.file_path, target_symbol="add_numbers")
        self.assertIn("MAX_LIMIT = 1000", elastic)
        self.assertIn("def add_numbers(a: int, b: int) -> int:", elastic)
        self.assertIn("raise ValueError(\"Too large\")", elastic)
        self.assertIn("Vector2D", elastic)
        self.assertIn("lines folded", elastic)

    def test_find_symbol_topology(self):
        caller_file = Path(self.temp_dir.name) / "caller.py"
        caller_file.write_text("from sample import add_numbers\ndef run():\n    return add_numbers(5, 10)\n", encoding="utf-8")
        topo = find_symbol_topology(self.temp_dir.name, "add_numbers")
        self.assertIn("Topology Map for: 'add_numbers'", topo)
        self.assertIn("Callers", topo)
        self.assertIn("caller.py", topo)
        self.assertIn("run()", topo)

    def test_extract_contract_skeleton(self):
        contract = extract_contract_skeleton(self.file_path)
        self.assertIn("Contract Skeleton", contract)
        self.assertIn("def add_numbers(a: int, b: int) -> int:", contract)
        self.assertIn("raise ValueError(\"Too large\")", contract)
        self.assertIn("return a + b", contract)


if __name__ == "__main__":
    unittest.main()
