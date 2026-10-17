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
from tfwhy.replacement import analyze_replacements  # noqa: E402
from tfwhy.renderers import render_json, render_markdown, render_terminal  # noqa: E402


def plan(resources=None, **extra):
    document = {"format_version": "1.0", "terraform_version": "1.6.0", "resource_changes": resources or []}
    document.update(extra)
    return document


def resource(address, resource_type, actions, **change):
    action_reason = change.pop("action_reason", None)
    result = {"address": address, "mode": "managed", "type": resource_type, "change": {"actions": actions, **change}}
    if action_reason is not None:
        result["action_reason"] = action_reason
    return result


class PlanExplainerTests(unittest.TestCase):
    def write_plan(self, content):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        with handle:
            handle.write(content if isinstance(content, str) else json.dumps(content))
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def write_config(self, content):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        (directory / "main.tf").write_text(content, encoding="utf-8")
        return directory

    def write_project(self, files):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        for relative_path, content in files.items():
            target = directory / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return directory

    def test_replacement_fixture_identifies_supported_patterns_and_unknowns(self):
        summary = analyze_replacements(
            load_plan(ROOT / "tests" / "fixtures" / "replacement_plan.json"),
            ROOT / "tests" / "fixtures" / "replacement_config",
        )
        findings = {finding.address: finding for finding in summary.replacement_findings}
        self.assertEqual(set(findings), {
            "aws_instance.user_data",
            "aws_instance.ami",
            "aws_instance.random",
            "aws_instance.indexed[\"blue\"]",
            "aws_instance.unknown",
            "aws_instance.data_source",
        })
        self.assertEqual(findings["aws_instance.user_data"].confidence, "Likely")
        self.assertIn("timestamp", findings["aws_instance.user_data"].explanation)
        self.assertEqual(findings["aws_instance.ami"].confidence, "Likely")
        self.assertIn("data source", findings["aws_instance.ami"].explanation)
        self.assertEqual(findings["aws_instance.random"].confidence, "Likely")
        self.assertIn("random", findings["aws_instance.random"].explanation)
        self.assertEqual(findings["aws_instance.indexed[\"blue\"]"].confidence, "Unknown")
        self.assertIn("does not establish", " ".join(findings["aws_instance.indexed[\"blue\"]"].evidence))
        self.assertEqual(findings["aws_instance.unknown"].confidence, "Unknown")
        self.assertIn("insufficient", findings["aws_instance.unknown"].explanation)
        self.assertEqual(findings["aws_instance.data_source"].confidence, "Likely")
        self.assertIn("data source", findings["aws_instance.data_source"].explanation)

    def test_plan_metadata_and_action_reason_produce_confirmed_evidence(self):
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]], action_reason="replace_because_cannot_update")
        ]))))
        finding = summary.replacement_findings[0]
        self.assertEqual(finding.confidence, "Unknown")
        self.assertIn("action reason", " ".join(finding.evidence))
        self.assertIn("insufficient", finding.explanation)

        confirmed = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.tainted", "aws_instance", ["delete", "create"], replace_paths=[["ami"]], action_reason="replace_because_tainted")
        ]))))
        self.assertEqual(confirmed.replacement_findings[0].confidence, "Confirmed")

    def test_non_replacements_have_no_replacement_findings(self):
        summary = analyze_replacements(load_plan(self.write_plan(plan([resource("aws_instance.app", "aws_instance", ["update"])]))))
        self.assertEqual(summary.replacement_findings, ())

    def test_configuration_values_and_secret_markers_never_enter_findings_or_reports(self):
        secret = "SYNTHETIC_SECRET_MARKER"
        config_dir = self.write_config(f'''resource "aws_instance" "app" {{
  user_data = "{secret}"
}}
''')
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]], before={"user_data": secret}, after={"user_data": secret})
        ]))), config_dir)
        for output in (render_terminal(summary), render_markdown(summary), render_json(summary)):
            self.assertNotIn(secret, output)
        self.assertNotIn(secret, repr(summary.replacement_findings))

    def test_missing_configuration_directory_is_safe_error(self):
        with self.assertRaisesRegex(PlanError, "configuration directory"):
            analyze_replacements(load_plan(self.write_plan(plan())), ROOT / "does-not-exist")

    def test_all_actions_and_safe_metadata_are_reported_consistently(self):
        resources = [
            resource("aws_instance.app", "aws_instance", ["create"]),
            resource("aws_s3_bucket.logs", "aws_s3_bucket", ["update"]),
            resource("aws_iam_role.old", "aws_iam_role", ["delete"]),
            resource("aws_instance.replaced", "aws_instance", ["delete", "create"], replace_paths=[["ami"], ["tags", "Name"]], action_reason="replace_because_cannot_update"),
            resource("data.aws_ami.base", "aws_ami", ["read"]),
            resource("aws_security_group.same", "aws_security_group", ["no-op"]),
        ]
        summary = load_plan(self.write_plan(plan(resources)))
        self.assertEqual(summary.counts(), {"create": 1, "update": 1, "delete": 1, "replace": 1, "read": 1, "no-op": 1})
        self.assertEqual(summary.resources[3].replacement_paths, ("ami", "tags.Name"))
        self.assertIn("replace_because_cannot_update", render_terminal(summary))
        self.assertIn("aws_instance.replaced", render_markdown(summary))
        output = render_json(summary)
        self.assertIn('"category": "replace"', output)
        self.assertNotIn('"change"', output)

    def test_empty_and_resource_less_plans(self):
        summary = load_plan(self.write_plan(plan()))
        self.assertEqual(sum(summary.counts().values()), 0)
        self.assertIn("No resource changes", render_markdown(summary))

    def test_secret_values_never_enter_any_report(self):
        secret = "SYNTHETIC_SECRET_MARKER"
        summary = load_plan(self.write_plan(plan([resource("aws_instance.app", "aws_instance", ["update"], before={"password": secret}, after={"password": secret})])))
        for output in (render_terminal(summary), render_markdown(summary), render_json(summary)):
            self.assertNotIn(secret, output)

    def test_malformed_and_unsupported_inputs_are_errors(self):
        cases = [
            ("{", "malformed JSON"),
            ({"resource_changes": []}, "format_version"),
            (plan(format_version="2.0"), "unsupported plan format major version"),
            (plan(format_version="1"), "malformed plan format_version"),
            (plan(format_version="one.point.zero"), "malformed plan format_version"),
            (plan([{"address": "broken", "type": "aws_instance"}]), "missing a change object"),
            (plan([resource("aws_instance.bad", "aws_instance", ["create", "update"])]), "must be one action"),
            (plan([resource("aws_instance.bad", "aws_instance", ["update"], replace_paths=["not-a-path"])]), "malformed replacement paths"),
            (plan([resource("aws_instance.bad", "aws_instance", ["update"], replace_paths=[[]])]), "malformed replacement paths"),
        ]
        for content, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PlanError, message):
                    load_plan(self.write_plan(content))

    def test_format_version_accepts_compatible_minor_versions(self):
        for format_version in ("1.0", "1.1", "1.99"):
            with self.subTest(format_version=format_version):
                summary = load_plan(self.write_plan(plan(format_version=format_version)))
                self.assertEqual(summary.format_version, format_version)

    def test_phase9_format_1_1_fixture_preserves_safe_module_metadata(self):
        summary = load_plan(ROOT / "tests" / "fixtures" / "phase9_plan_1_1.json")
        self.assertEqual(summary.format_version, "1.1")
        self.assertEqual(summary.terraform_version, "1.9.0")
        self.assertEqual(summary.resources[0].address, "module.child.aws_instance.app")
        self.assertEqual(summary.resources[0].category, "replace")

    def test_plan_errors_do_not_echo_plan_derived_values(self):
        secret = "SYNTHETIC_SECRET_MARKER"
        malformed = plan([{"address": secret, "type": "aws_instance"}])
        with self.assertRaises(PlanError) as context:
            load_plan(self.write_plan(malformed))
        self.assertNotIn(secret, str(context.exception))

    def test_missing_optional_fields_are_supported(self):
        summary = load_plan(self.write_plan({"format_version": "1.0"}))
        self.assertEqual(summary.resources, ())

    def test_unknown_or_malformed_action_reason_is_not_reported(self):
        for action_reason in ("future_reason", {"secret": "value"}):
            summary = load_plan(self.write_plan(plan([resource("aws_instance.app", "aws_instance", ["update"], action_reason=action_reason)])))
            self.assertIsNone(summary.resources[0].action_reason)

    def test_cli_formats_and_errors(self):
        path = self.write_plan(plan([resource("aws_instance.app", "aws_instance", ["create"])]))
        for output_format in ("terminal", "markdown", "json"):
            result = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(path), "--format", output_format], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn("aws_instance.app", result.stdout)
        bad = self.write_plan("not json")
        result = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(bad)], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("malformed JSON", result.stderr)

    def test_cli_integration_exit_codes_and_errors(self):
        valid = self.write_plan(plan([resource("aws_instance.app", "aws_instance", ["create"])]))
        valid_result = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(valid)], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(valid_result.returncode, 0)
        self.assertIn("aws_instance.app", valid_result.stdout)

        missing = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(ROOT / "does-not-exist-SYNTHETIC_SECRET_MARKER.json")], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("plan file not found", missing.stderr)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", missing.stderr)

        unsupported = self.write_plan(plan(format_version="2.0"))
        unsupported_result = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(unsupported)], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(unsupported_result.returncode, 2)
        self.assertIn("unsupported plan format major version", unsupported_result.stderr)

    def test_cli_reports_do_not_leak_secret_markers(self):
        secret = "SYNTHETIC_SECRET_MARKER"
        path = self.write_plan(plan([resource("aws_instance.app", "aws_instance", ["update"], before={"password": secret}, after={"password": secret})]))
        for output_format in ("terminal", "markdown", "json"):
            with self.subTest(output_format=output_format):
                result = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(path), "--format", output_format], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0)
                self.assertNotIn(secret, result.stdout)
                self.assertNotIn(secret, result.stderr)

    def test_cli_dir_reports_findings_in_all_formats(self):
        plan_path = ROOT / "tests" / "fixtures" / "replacement_plan.json"
        config_dir = ROOT / "tests" / "fixtures" / "replacement_config"
        for output_format in ("terminal", "markdown", "json"):
            with self.subTest(output_format=output_format):
                result = subprocess.run([sys.executable, "-m", "tfwhy", "explain", str(plan_path), "--dir", str(config_dir), "--format", output_format], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0)
                self.assertIn("aws_instance.user_data", result.stdout)
                self.assertIn("Likely", result.stdout)
                self.assertNotIn("timestamp()", result.stdout)
                self.assertNotIn("data.aws_ami.base.id", result.stdout)

    def test_repetition_presence_alone_stays_unknown(self):
        config_dir = self.write_config('''resource "aws_instance" "app" {
    for_each = var.instances
    ami      = var.ami
}
''')
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["ami"]])
        ]))), config_dir)
        self.assertEqual(summary.replacement_findings[0].confidence, "Unknown")

    def test_ambiguous_duplicate_matches_stay_unknown(self):
        duplicate_dir = self.write_config('''resource "aws_instance" "app" {
    user_data = timestamp()
}

resource "aws_instance" "app" {
    user_data = random_id.value.hex
}
''')
        duplicate_summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]])
        ]))), duplicate_dir)
        self.assertEqual(duplicate_summary.replacement_findings[0].confidence, "Unknown")

    def test_interpolation_braces_do_not_cross_match_a_later_resource(self):
        config_dir = self.write_config('''resource "aws_instance" "app" {
  user_data = "stable ${var.label}"
}

resource "aws_instance" "unrelated" {
  user_data = timestamp()
}
''')
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]])
        ]))), config_dir)
        finding = summary.replacement_findings[0]
        self.assertEqual(finding.confidence, "Unknown")
        self.assertNotIn("timestamp", " ".join(finding.evidence))

    def test_module_aware_matching_uses_the_called_local_module_only(self):
        config_dir = self.write_project({
            "main.tf": '''module "dynamic" {
  source = "./modules/dynamic"
}

module "static" {
  source = "./modules/static"
}
''',
            "modules/dynamic/main.tf": '''resource "aws_instance" "app" {
  user_data = timestamp()
}
''',
            "modules/static/main.tf": '''resource "aws_instance" "app" {
  user_data = "stable"
}
''',
        })
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("module.dynamic.aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]]),
            resource("module.static.aws_instance.app", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]]),
        ]))), config_dir)
        findings = {finding.address: finding for finding in summary.replacement_findings}
        self.assertEqual(findings["module.dynamic.aws_instance.app"].confidence, "Likely")
        self.assertIn("modules/dynamic/main.tf:2", " ".join(findings["module.dynamic.aws_instance.app"].evidence))
        self.assertEqual(findings["module.static.aws_instance.app"].confidence, "Unknown")

    def test_direct_variable_local_and_resource_references_include_source_locations(self):
        config_dir = self.write_config('''variable "image_id" {
  default = data.aws_ami.base.id
}

locals {
  selected_image = var.image_id
}

resource "terraform_data" "seed" {
  input = "stable"
}

resource "aws_instance" "from_local" {
  ami = local.selected_image
}

resource "aws_instance" "from_resource" {
  user_data = terraform_data.seed.output
}
''')
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.from_local", "aws_instance", ["delete", "create"], replace_paths=[["ami"]]),
            resource("aws_instance.from_resource", "aws_instance", ["delete", "create"], replace_paths=[["user_data"]]),
        ]))), config_dir)
        findings = {finding.address: finding for finding in summary.replacement_findings}
        local_finding = findings["aws_instance.from_local"]
        self.assertEqual(local_finding.confidence, "Likely")
        self.assertIn("directly references local selected_image", " ".join(local_finding.evidence))
        self.assertIn("directly references variable image_id", " ".join(local_finding.evidence))
        self.assertIn("main.tf:2", " ".join(local_finding.evidence))
        resource_finding = findings["aws_instance.from_resource"]
        self.assertEqual(resource_finding.confidence, "Unknown")
        self.assertIn("directly references resource declared at main.tf:9", " ".join(resource_finding.evidence))

    def test_count_for_each_moved_and_indirect_expressions_remain_unknown(self):
        config_dir = self.write_config('''moved {
  from = aws_instance.old
  to   = aws_instance.counted["blue"]
}

resource "aws_instance" "counted" {
  count = 1
  ami   = var.choose_dynamic ? data.aws_ami.base.id : var.ami
}

resource "aws_instance" "each" {
  for_each = var.instances
  ami      = var.ami
}
''')
        summary = analyze_replacements(load_plan(self.write_plan(plan([
            resource("aws_instance.counted[\"blue\"]", "aws_instance", ["delete", "create"], previous_address="aws_instance.counted[0]", replace_paths=[["ami"]]),
            resource("aws_instance.each[\"blue\"]", "aws_instance", ["delete", "create"], replace_paths=[["ami"]]),
        ]))), config_dir)
        findings = {finding.address: finding for finding in summary.replacement_findings}
        self.assertEqual(findings["aws_instance.counted[\"blue\"]"].confidence, "Unknown")
        self.assertIn("declares count", " ".join(findings["aws_instance.counted[\"blue\"]"].evidence))
        self.assertNotIn("data source", findings["aws_instance.counted[\"blue\"]"].explanation)
        self.assertEqual(findings["aws_instance.each[\"blue\"]"].confidence, "Unknown")
        self.assertIn("declares for_each", " ".join(findings["aws_instance.each[\"blue\"]"].evidence))


if __name__ == "__main__":
    unittest.main()
