"""Tests for scripts/check_action_input_coverage.py helpers."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
import unittest


def load_module():
    """Load coverage script module from file path."""
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "check_action_input_coverage.py"
    spec = importlib.util.spec_from_file_location("coverage_script", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoverageScriptTests(unittest.TestCase):
    """Unit tests for input parsing and matching."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_parse_action_inputs_supports_hyphen_and_quotes(self):
        """Parser extracts plain, hyphenated, and quoted keys."""
        content = """
name: Example
inputs:
  plain_key:
    description: plain
  kebab-key:
    description: hyphen
  "quoted-key":
    description: quoted
  'single-quoted-key':
    description: quoted
outputs:
  ignored: {}
""".strip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            action_file = Path(tmp_dir) / "action.yml"
            action_file.write_text(content, encoding="utf-8")
            keys = self.module.parse_action_inputs(action_file)

        self.assertEqual(
            keys,
            ["plain_key", "kebab-key", "quoted-key", "single-quoted-key"],
        )

    def test_normalize_input_env_name(self):
        """Normalization maps non-alnum chars to underscores."""
        normalized = self.module.normalize_input_env_name("my-input name")
        self.assertEqual(normalized, "INPUT_MY_INPUT_NAME")

    def test_input_is_covered_by_env_name_for_hyphenated_input(self):
        """Coverage matching finds normalized INPUT_* variable usage."""
        corpus = "run: echo $INPUT_DRY_RUN_MODE"
        self.assertTrue(self.module.input_is_covered("dry-run-mode", corpus))

    def test_strict_gate_fails_when_no_action_repos(self):
        """Strict gate fails when discovery yields no action repositories."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline_file = Path(tmp_dir) / "baseline.json"
            baseline_file.write_text("{}\n", encoding="utf-8")
            exit_code = self.module.strict_gate({}, baseline_file)
        self.assertEqual(exit_code, 1)

    def test_load_baseline_handles_invalid_json(self):
        """Invalid baseline JSON returns empty baseline without crashing."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline_file = Path(tmp_dir) / "baseline.json"
            baseline_file.write_text("{invalid-json", encoding="utf-8")
            baseline = self.module.load_baseline(baseline_file)
        self.assertEqual(baseline, {})


if __name__ == "__main__":
    unittest.main()
