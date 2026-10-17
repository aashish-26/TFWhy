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
from tfwhy.analyzer import PlanError  # noqa: E402
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

    def test_legacy_terraform_provider_source_has_bounded_migration_guidance(self):
        legacy_dir = self.write_config('''terraform {
  required_version = "~> 1.5"
  required_providers {
    terraform = {
      source  = "hashicorp/terraform"
      version = "~> 2.0"
    }
  }
}
''')
        built_in_dir = self.write_config('''terraform {
  required_version = "~> 1.5"
  required_providers {
    terraform = {
      source  = "terraform.io/builtin/terraform"
      version = "~> 1.0"
    }
  }
  # source = "hashicorp/terraform"
}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            legacy = review_configuration(legacy_dir, required_tags=())
            built_in = review_configuration(built_in_dir, required_tags=())
        legacy_finding = next(finding for finding in legacy.findings if finding.rule_id == "TFWHY-UPGRADE-001")
        self.assertEqual(legacy_finding.severity, "Medium")
        self.assertIn("built-in", legacy_finding.remediation)
        self.assertNotIn("TFWHY-UPGRADE-001", {finding.rule_id for finding in built_in.findings})

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

    def test_iam_and_network_permission_findings_are_static_and_evidence_backed(self):
        config_dir = ROOT / "tests" / "fixtures" / "phase10_permissions"
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir, required_tags=())
        by_rule = {finding.rule_id: finding for finding in report.findings}
        self.assertEqual(by_rule["TFWHY-IAM-001"].severity, "Medium")
        self.assertEqual(by_rule["TFWHY-IAM-002"].severity, "Medium")
        self.assertEqual(by_rule["TFWHY-NET-002"].severity, "Medium")
        self.assertEqual(by_rule["TFWHY-NET-003"].severity, "Medium")
        self.assertIn("does not establish", by_rule["TFWHY-NET-003"].evidence.lower())

    def test_deny_and_narrow_or_computed_permissions_are_not_flagged(self):
        config_dir = self.write_config('''resource "aws_iam_policy" "narrow" {
  policy = jsonencode({
    Statement = [
      {
        Effect   = "Deny"
        Action   = "*"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::example/*"
      }
    ]
  })
}

resource "aws_security_group" "limited_egress" {
  egress {
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_network_acl_rule" "private_ssh" {
  egress      = false
  rule_action = "allow"
  protocol    = "tcp"
  cidr_block  = var.admin_cidr
  from_port   = 22
}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir, required_tags=())
        new_rules = {"TFWHY-IAM-001", "TFWHY-IAM-002", "TFWHY-NET-002", "TFWHY-NET-003"}
        self.assertFalse(new_rules & {finding.rule_id for finding in report.findings})

    def test_permission_fixture_and_interpolation_braces_are_scanned_without_policy_leaks(self):
        config_dir = self.write_config('''resource "aws_iam_policy" "interpolated" {
  policy = jsonencode({
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.logs.arn}/*"
    }]
  })
}

resource "aws_iam_policy" "wildcard" {
  policy = jsonencode({
    Statement = [{
      Effect   = "Allow"
      Action   = "*"
      Resource = "*"
    }]
  })
}
''')
        with patch("tfwhy.standards.subprocess.run", side_effect=self.successful_terraform):
            report = review_configuration(config_dir, required_tags=())
        wildcard_findings = [finding for finding in report.findings if finding.rule_id.startswith("TFWHY-IAM-")]
        self.assertEqual(len(wildcard_findings), 2)
        self.assertNotIn("aws_s3_bucket.logs.arn", json.dumps(report.as_dict()))

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

    def test_blank_required_tag_is_rejected_instead_of_becoming_a_finding(self):
        config_dir = self.write_config('resource "aws_s3_bucket" "logs" {}\n')
        with self.assertRaisesRegex(PlanError, "non-empty"):
            review_configuration(config_dir, required_tags=("",))


if __name__ == "__main__":
    unittest.main()
