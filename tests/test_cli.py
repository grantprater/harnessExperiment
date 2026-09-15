"""Unit tests for the Unified Reticle CLI interface."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class TestReticleCLI(unittest.TestCase):

    def test_cli_version(self):
        cmd = [sys.executable, "-m", "reticle", "version"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn("Reticle Cognitive Harness v", res.stdout)

    def test_cli_help(self):
        cmd = [sys.executable, "-m", "reticle", "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn("run", res.stdout)
        self.assertIn("verify-ast", res.stdout)

    def test_cli_run_mock_json(self):
        # Run with mock key and json output to test structured telemetry output
        cmd = [
            sys.executable, "-m", "reticle", "run",
            "--goal", "Test execution loop",
            "--verify", f"{sys.executable} -c \"import sys; sys.exit(0)\"",
            "--api-key", "mock_key",
            "--max-steps", "1",
            "--json"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.assertIn('"solved": true', res.stdout)
        self.assertIn('"efficiency_metrics"', res.stdout)
        self.assertIn('"total_token_spend"', res.stdout)


if __name__ == "__main__":
    unittest.main()
