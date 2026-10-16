import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tfwhy.analyzer import PlanError, load_plan  # noqa: E402
from tfwhy.fixes import FixError, apply_proposal, propose_fix, verify_plan  # noqa: E402
from tfwhy.renderers import render_fix_json, render_fix_markdown, render_fix_terminal, render_verification_json, render_verification_markdown, render_verification_terminal  # noqa: E402


def plan(resources):
    return {"format_version": "1.0", "terraform_version": "1.6.0", "resource_changes": resources}


def replacement(address, previous_address=None, actions=None, before=None, after=None):
    change = {"actions": actions or ["delete", "create"], "replace_paths": [["name"]]}
    if before is not None:
        change["before"] = before
    if after is not None:
        change["after"] = after
    result = {"address": address, "type": "aws_instance", "change": change}
    if previous_address is not None:
        result["previous_address"] = previous_address
    return result


class FixTests(unittest.TestCase):
    def write_plan(self, document):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        with handle:
            json.dump(document, handle)
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def write_dir(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        return directory

    def test_rename_proposal_is_unified_diff_and_dry_run_writes_nothing(self):
        config_dir = self.write_dir()
        plan_path = self.write_plan(plan([replacement("aws_instance.new", "aws_instance.old")]))
        cli_result = subprocess.run([sys.executable, "-m", "tfwhy", "fix", "--finding", "TFWHY-001", "--plan", str(plan_path), "--dir", str(config_dir), "--dry-run", "--format", "json"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(cli_result.returncode, 0)
        self.assertIn('"status": "proposed"', cli_result.stdout)
        self.assertFalse((config_dir / "moved.tf").exists())

        summary = load_plan(plan_path)
        proposal = propose_fix(summary, "TFWHY-001", config_dir)
        self.assertEqual(proposal.status, "proposed")
        self.assertEqual(proposal.kind, "resource_rename")
        self.assertIn("moved {", proposal.diff)
        self.assertIn("from = aws_instance.old", proposal.diff)
        self.assertFalse((config_dir / "moved.tf").exists())

    def test_count_to_for_each_proposal_requires_unambiguous_mapping(self):
        config_dir = self.write_dir()
        summary = load_plan(self.write_plan(plan([replacement("aws_instance.app[\"blue\"]", "aws_instance.app[0]")])))
        proposal = propose_fix(summary, "TFWHY-001", config_dir)
        self.assertEqual(proposal.kind, "count_to_for_each")
        self.assertIn('to   = aws_instance.app["blue"]', proposal.diff)

        ambiguous = load_plan(self.write_plan(plan([replacement("aws_instance.app[" + '"blue"' + "]")])))
        rejected = propose_fix(ambiguous, "TFWHY-001", config_dir)
        self.assertEqual(rejected.status, "inconclusive")
        self.assertIsNone(rejected.diff)

    def test_approval_is_required_and_apply_refuses_overwrite(self):
        config_dir = self.write_dir()
        plan_path = self.write_plan(plan([replacement("aws_instance.new", "aws_instance.old")]))
        result = subprocess.run([sys.executable, "-m", "tfwhy", "fix", "--finding", "TFWHY-001", "--plan", str(plan_path), "--dir", str(config_dir), "--apply"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--approve", result.stderr)
        self.assertFalse((config_dir / "moved.tf").exists())

        contradictory = subprocess.run([sys.executable, "-m", "tfwhy", "fix", "--finding", "TFWHY-001", "--plan", str(plan_path), "--dir", str(config_dir), "--apply", "--approve", "--dry-run"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(contradictory.returncode, 2)
        self.assertIn("cannot be used together", contradictory.stderr)

        proposal = propose_fix(load_plan(plan_path), "TFWHY-001", config_dir)
        target = apply_proposal(proposal, config_dir)
        self.assertTrue(target.exists())
        with self.assertRaisesRegex(FixError, "already exists"):
            apply_proposal(proposal, config_dir)

    def test_verification_distinguishes_verified_not_verified_and_inconclusive(self):
        verified = load_plan(self.write_plan(plan([{"address": "aws_instance.new", "type": "aws_instance", "change": {"actions": ["no-op"]}}])))
        result = verify_plan(verified, "aws_instance.old", "aws_instance.new", "resource_rename")
        self.assertEqual(result.status, "verified")

        not_verified = load_plan(self.write_plan(plan([replacement("aws_instance.new")])))
        result = verify_plan(not_verified, "aws_instance.old", "aws_instance.new", "resource_rename")
        self.assertEqual(result.status, "not_verified")

        inconclusive = load_plan(self.write_plan(plan([])))
        result = verify_plan(inconclusive, "aws_instance.old", "aws_instance.new", "resource_rename")
        self.assertEqual(result.status, "inconclusive")

    def test_malformed_finding_and_plan_are_rejected(self):
        config_dir = self.write_dir()
        summary = load_plan(self.write_plan(plan([])))
        with self.assertRaisesRegex(FixError, "finding ID"):
            propose_fix(summary, "bad", config_dir)
        with self.assertRaises(PlanError):
            load_plan(self.write_plan({"format_version": "1.0", "resource_changes": [{"address": "bad"}]}))

    def test_fix_and_verification_renderers_do_not_leak_values(self):
        secret = "SYNTHETIC_SECRET_MARKER"
        config_dir = self.write_dir()
        summary = load_plan(self.write_plan(plan([replacement("aws_instance.new", "aws_instance.old", before={"password": secret}, after={"password": secret})])))
        proposal = propose_fix(summary, "TFWHY-001", config_dir)
        for output in (render_fix_terminal(proposal), render_fix_markdown(proposal), render_fix_json(proposal)):
            self.assertNotIn(secret, output)
        verification = verify_plan(load_plan(self.write_plan(plan([{"address": "aws_instance.new", "type": "aws_instance", "change": {"actions": ["no-op"]}}]))), "aws_instance.old", "aws_instance.new", "resource_rename")
        for output in (render_verification_terminal(verification), render_verification_markdown(verification), render_verification_json(verification)):
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()