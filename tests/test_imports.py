import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tfwhy.imports import ImportError, apply_import_proposal, propose_import  # noqa: E402
from tfwhy.renderers import render_import_json, render_import_markdown, render_import_terminal  # noqa: E402


class ImportProposalTests(unittest.TestCase):
    def write_dir(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        return directory

    def test_s3_import_preview_includes_only_supported_starter_configuration(self):
        proposal = propose_import("aws_s3_bucket.logs", "example-logs", include_starter=True)
        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(proposal.starter_status, "generated")
        self.assertIn("to = aws_s3_bucket.logs", proposal.content)
        self.assertIn('id = "example-logs"', proposal.content)
        self.assertIn('bucket = "example-logs"', proposal.content)
        self.assertFalse(proposal.can_write)
        for output in (render_import_terminal(proposal), render_import_markdown(proposal), render_import_json(proposal)):
            self.assertIn("aws_s3_bucket.logs", output)
            self.assertIn("starter", output.lower())
        fixture_content = (ROOT / "tests" / "fixtures" / "import_s3" / "main.tf").read_text(encoding="utf-8")
        self.assertIn(proposal.content, fixture_content)

    def test_unsupported_starter_and_malformed_input_are_conservative(self):
        proposal = propose_import("module.app.aws_instance.web", "i-123", include_starter=True)
        self.assertEqual(proposal.starter_status, "unavailable")
        self.assertNotIn('resource "aws_instance"', proposal.content)
        self.assertIn("provider-specific required arguments", proposal.rationale)

        with self.assertRaisesRegex(ImportError, "managed-resource address") as context:
            propose_import("data.aws_ami.base", "SYNTHETIC_SECRET_MARKER")
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", str(context.exception))
        with self.assertRaisesRegex(ImportError, "identifier"):
            propose_import("aws_instance.web", "")

    def test_import_identifier_is_escaped_as_data_not_hcl_code(self):
        proposal = propose_import("aws_s3_bucket.logs", 'example"\nmalicious = true', include_starter=True)
        self.assertIn('id = "example\\"\\nmalicious = true"', proposal.content)
        self.assertNotIn("\nmalicious = true\n", proposal.content)

    def test_explicit_approved_output_is_new_only_and_never_overwritten(self):
        directory = self.write_dir()
        target = directory / "import.tf"
        proposal = propose_import("aws_s3_bucket.logs", "example-logs", target, include_starter=True)
        written = apply_import_proposal(proposal)
        self.assertEqual(written, target)
        self.assertIn("import {", target.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ImportError, "already exists"):
            apply_import_proposal(proposal)

        with self.assertRaisesRegex(ImportError, "explicit --out"):
            apply_import_proposal(propose_import("aws_s3_bucket.other", "other"))

    def test_cli_preview_formats_and_write_guards(self):
        env = {"PYTHONPATH": str(ROOT / "src")}
        for output_format in ("terminal", "markdown", "json"):
            with self.subTest(output_format=output_format):
                result = subprocess.run(
                    [sys.executable, "-m", "tfwhy", "import", "--address", "aws_s3_bucket.logs", "--id", "example-logs", "--starter-config", "--format", output_format],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn("aws_s3_bucket.logs", result.stdout)
        result = subprocess.run(
            [sys.executable, "-m", "tfwhy", "import", "--address", "aws_s3_bucket.logs", "--id", "example-logs", "--apply"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--approve", result.stderr)

        directory = self.write_dir()
        target = directory / "generated-import.tf"
        applied = subprocess.run(
            [sys.executable, "-m", "tfwhy", "import", "--address", "aws_s3_bucket.logs", "--id", "example-logs", "--out", str(target), "--starter-config", "--apply", "--approve"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(applied.returncode, 0)
        self.assertTrue(target.exists())

        malformed = subprocess.run(
            [sys.executable, "-m", "tfwhy", "import", "--address", "not a resource", "--id", "SYNTHETIC_SECRET_MARKER"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(malformed.returncode, 2)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", malformed.stderr)


if __name__ == "__main__":
    unittest.main()
