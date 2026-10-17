import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tfwhy.analyzer import PlanError, load_plan  # noqa: E402
from tfwhy.renderers import (  # noqa: E402
    render_drift_json,
    render_drift_markdown,
    render_drift_terminal,
    render_json,
    render_markdown,
    render_terminal,
)


class DriftTests(unittest.TestCase):
    def write_plan(self, document):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        with handle:
            json.dump(document, handle)
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_resource_drift_is_separate_from_planned_changes_with_safe_evidence(self):
        summary = load_plan(ROOT / "tests" / "fixtures" / "phase11_drift" / "refresh_only_like_plan.json")
        findings = {finding.address: finding for finding in summary.drift_findings}
        self.assertEqual(set(findings), {"aws_instance.app", "aws_s3_bucket.logs"})
        self.assertEqual(findings["aws_instance.app"].status, "Detected")
        self.assertIn("planned resource change at this address", " ".join(findings["aws_instance.app"].evidence))
        self.assertIn("tags.DriftMarker", " ".join(findings["aws_instance.app"].evidence))
        self.assertIn("No planned resource change", " ".join(findings["aws_s3_bucket.logs"].evidence))
        self.assertIn("does not identify who", findings["aws_instance.app"].explanation)
        for renderer in (render_terminal, render_markdown, render_json, render_drift_terminal, render_drift_markdown, render_drift_json):
            self.assertNotIn("SYNTHETIC_SECRET_MARKER", renderer(summary))

    def test_absent_resource_drift_is_not_inferred_from_an_ordinary_plan(self):
        summary = load_plan(ROOT / "tests" / "fixtures" / "phase11_drift" / "no_drift_plan.json")
        self.assertEqual(summary.drift_findings, ())
        self.assertIn("No detected remote drift", render_drift_terminal(summary))
        self.assertNotIn("Detected Remote Drift", render_markdown(summary))

    def test_malformed_drift_and_relevance_metadata_are_rejected_without_value_echoes(self):
        base = {"format_version": "1.0", "resource_changes": []}
        cases = [
            ({**base, "resource_drift": {}}, "resource_drift must be an array"),
            ({**base, "resource_drift": [{"address": "SYNTHETIC_SECRET_MARKER"}]}, "resource_drift[0] is missing a valid type"),
            ({**base, "relevant_attributes": [{"resource": "aws_instance.app", "attribute": "SYNTHETIC_SECRET_MARKER"}]}, "relevant_attributes[0] contains malformed"),
        ]
        for document, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(PlanError) as context:
                    load_plan(self.write_plan(document))
                self.assertIn(message, str(context.exception))
                self.assertNotIn("SYNTHETIC_SECRET_MARKER", str(context.exception))

    def test_drift_command_renders_terminal_markdown_and_json_without_cloud_access(self):
        plan = ROOT / "tests" / "fixtures" / "phase11_drift" / "refresh_only_like_plan.json"
        for output_format in ("terminal", "markdown", "json"):
            with self.subTest(output_format=output_format):
                result = subprocess.run(
                    [sys.executable, "-m", "tfwhy", "drift", str(plan), "--format", output_format],
                    cwd=ROOT,
                    env={"PYTHONPATH": str(ROOT / "src")},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("aws_instance.app", result.stdout)
                self.assertNotIn("SYNTHETIC_SECRET_MARKER", result.stdout)

    def test_drift_command_returns_a_safe_error_for_bad_input(self):
        path = self.write_plan({"format_version": "1.0", "resource_drift": "SYNTHETIC_SECRET_MARKER"})
        result = subprocess.run(
            [sys.executable, "-m", "tfwhy", "drift", str(path)],
            cwd=ROOT,
            env={"PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("resource_drift must be an array", result.stderr)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", result.stderr)
