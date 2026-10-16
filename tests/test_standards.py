import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tfwhy.renderers import render_review_json, render_review_markdown, render_review_terminal  # noqa: E402
from tfwhy.standards import review_configuration  # noqa: E402


class StandardsTests(unittest.TestCase):
    def write_config(self, content):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(directory, ignore_errors=True))
        (directory / "main.tf").write_text(content, encoding="utf-8")
        return directory

    @staticmethod
    def successful_terraform(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "", "")

    def test_positive_standards_and_security_findings(self):
        config_dir = self.write_config('''terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "region" {}
output "public_value" {}

resource "aws_security_group" "Public-Web" {
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ebs_volume" "data_volume" {
  size = 10
}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir, required_tags=("Environment",))
        by_rule = {finding.rule_id: finding for finding in report.findings}
        self.assertIn("TFWHY-TF-002", by_rule)
        self.assertIn("TFWHY-PROVIDER-002", by_rule)
        self.assertIn("TFWHY-DOC-001", by_rule)
        self.assertIn("TFWHY-TAG-001", by_rule)
        self.assertIn("TFWHY-NAME-001", by_rule)
        self.assertEqual(by_rule["TFWHY-SEC-001"].severity, "High")
        self.assertEqual(by_rule["TFWHY-SEC-002"].severity, "Medium")
        self.assertNotIn("TFWHY-FMT-001", by_rule)
        self.assertNotIn("TFWHY-VALIDATE-001", by_rule)

    def test_clean_configuration_has_no_policy_findings(self):
        config_dir = self.write_config('''terraform {
  required_version = "~> 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region" {
  description = "Deployment region"
}

output "id" {
  description = "Resource identifier"
}

resource "aws_ebs_volume" "data_volume" {
  size      = 10
  encrypted = true
  tags = {
    Name = "data"
  }
}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir)
        self.assertEqual(report.findings, ())

    def test_public_ingress_from_literal_variable_default_is_detected(self):
        public_dir = self.write_config('''variable "source_cidr" {
  default = "0.0.0.0/0"
}

resource "aws_security_group" "web" {
  ingress {
    cidr_blocks = [var.source_cidr]
  }
}
''')
        private_dir = self.write_config('''variable "source_cidr" {
  default = "10.0.0.0/8"
}

resource "aws_security_group" "web" {
  ingress {
    cidr_blocks = [var.source_cidr]
  }
}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            public_report = review_configuration(public_dir, required_tags=())
            private_report = review_configuration(private_dir, required_tags=())
        self.assertIn("TFWHY-SEC-001", {finding.rule_id for finding in public_report.findings})
        self.assertNotIn("TFWHY-SEC-001", {finding.rule_id for finding in private_report.findings})

    def test_missing_terraform_is_info_not_a_security_failure(self):
        config_dir = self.write_config("resource \"null_resource\" \"example\" {}\n")
        with patch("tfwhy.standards.subprocess.run", side_effect=FileNotFoundError):
            report = review_configuration(config_dir, required_tags=())
        rule_ids = {finding.rule_id for finding in report.findings}
        self.assertIn("TFWHY-TOOL-001", rule_ids)
        self.assertNotIn("TFWHY-FMT-001", rule_ids)
        self.assertNotIn("TFWHY-VALIDATE-001", rule_ids)
        self.assertEqual(next(f for f in report.findings if f.rule_id == "TFWHY-TOOL-001").severity, "Info")

    def test_terraform_failures_are_distinguished_from_unavailable_tools(self):
        config_dir = self.write_config("terraform {}\n")

        def failed_fmt(command, **kwargs):
            if command[1] == "fmt":
                return subprocess.CompletedProcess(command, 3, "SYNTHETIC_SECRET_MARKER", "details")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch("tfwhy.standards.subprocess.run", side_effect=failed_fmt):
            report = review_configuration(config_dir, required_tags=())
        rule_ids = {finding.rule_id for finding in report.findings}
        self.assertIn("TFWHY-FMT-001", rule_ids)
        self.assertNotIn("TFWHY-TOOL-001", rule_ids)
        self.assertNotIn("SYNTHETIC_SECRET_MARKER", json.dumps(report.as_dict()))

    def test_malformed_configuration_and_custom_policy_controls(self):
        config_dir = self.write_config('''resource "aws_instance" "example" {
  tags = var.tags
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir, required_tags=("Environment",), skip_rules=("TFWHY-CONFIG-001", "TFWHY-TAG-001"))
        self.assertNotIn("TFWHY-CONFIG-001", {finding.rule_id for finding in report.findings})
        self.assertNotIn("TFWHY-TAG-001", {finding.rule_id for finding in report.findings})

    def test_all_review_renderers_and_cli_do_not_leak_secret_values(self):
        secret = "SYNTHETIC_SECRET_MARKER"
        config_dir = self.write_config(f'''resource "aws_instance" "example" {{
  user_data = "{secret}"
}}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir, required_tags=())
        for output in (render_review_terminal(report), render_review_markdown(report), render_review_json(report)):
            self.assertNotIn(secret, output)

        for output_format in ("terminal", "markdown", "json"):
            result = subprocess.run([sys.executable, "-m", "tfwhy", "review", "--dir", str(config_dir), "--format", output_format, "--required-tag", "Environment"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertNotIn(secret, result.stdout)
            self.assertNotIn(secret, result.stderr)

    def test_review_defaults_to_current_directory(self):
        config_dir = self.write_config("terraform {}\n")
        result = subprocess.run([sys.executable, "-m", "tfwhy", "review", "--format", "json"], cwd=config_dir, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn('"findings"', result.stdout)


if __name__ == "__main__":
    unittest.main()