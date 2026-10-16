"""Deterministic Terraform configuration standards and security checks."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .analyzer import PlanError, StandardFinding

DEFAULT_REQUIRED_TAGS = ("Name",)
_NAMED_BLOCK = re.compile(r'^\s*(resource|variable|output|provider)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{')
_PLAIN_BLOCK = re.compile(r'^\s*(terraform)\s*\{')
_ATTRIBUTE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")
_PUBLIC_IPV4 = re.compile(r"\b0\.0\.0\.0/0\b")
_PUBLIC_IPV6 = re.compile(r"\b::/0\b")


@dataclass(frozen=True)
class StandardsReport:
    findings: tuple[StandardFinding, ...]

    def as_dict(self) -> dict[str, object]:
        return {"findings": [finding.__dict__ for finding in self.findings]}


@dataclass(frozen=True)
class _Block:
    kind: str
    first_label: str | None
    second_label: str | None
    path: Path
    line: int
    body: str


def review_configuration(
    config_dir: Path,
    required_tags: Iterable[str] | None = None,
    skip_rules: Iterable[str] = (),
) -> StandardsReport:
    if not config_dir.is_dir():
        raise PlanError("configuration directory not found or is not a directory")
    blocks, malformed_files = _load_blocks(config_dir)
    skipped = set(skip_rules)
    required = tuple(required_tags) if required_tags is not None else DEFAULT_REQUIRED_TAGS
    findings: list[StandardFinding] = []
    findings.extend(_malformed_findings(malformed_files, skipped))
    findings.extend(_version_findings(blocks, skipped))
    findings.extend(_configuration_findings(blocks, required, skipped))
    findings.extend(_terraform_tool_findings(config_dir, skipped))
    return StandardsReport(tuple(findings))


def _load_blocks(config_dir: Path) -> tuple[tuple[_Block, ...], tuple[Path, ...]]:
    blocks: list[_Block] = []
    malformed: list[Path] = []
    try:
        files = sorted(path for path in config_dir.rglob("*.tf") if ".terraform" not in path.parts)
    except OSError as exc:
        raise PlanError("could not inspect configuration directory") from exc
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            malformed.append(path)
            continue
        for index, line in enumerate(lines):
            match = _NAMED_BLOCK.match(line) or _PLAIN_BLOCK.match(line)
            if not match:
                continue
            kind = match.group(1)
            first_label = match.group(2) if kind != "terraform" else None
            second_label = match.group(3) if kind == "resource" else None
            depth = line.count("{") - line.count("}")
            body_lines = [line]
            cursor = index + 1
            while depth > 0 and cursor < len(lines):
                body_lines.append(lines[cursor])
                depth += lines[cursor].count("{") - lines[cursor].count("}")
                cursor += 1
            if depth != 0:
                malformed.append(path)
                continue
            blocks.append(_Block(kind, first_label, second_label, path.relative_to(config_dir), index + 1, "\n".join(body_lines)))
    return tuple(blocks), tuple(dict.fromkeys(malformed))


def _malformed_findings(paths: tuple[Path, ...], skipped: set[str]) -> list[StandardFinding]:
    if "TFWHY-CONFIG-001" in skipped:
        return []
    return [StandardFinding("TFWHY-CONFIG-001", "Medium", str(path), "Terraform configuration could not be parsed as a balanced block.", "Unbalanced or unreadable .tf file structure detected.", "Correct the configuration syntax and rerun the review.") for path in paths]


def _version_findings(blocks: tuple[_Block, ...], skipped: set[str]) -> list[StandardFinding]:
    findings: list[StandardFinding] = []
    terraform_blocks = [block for block in blocks if block.kind == "terraform"]
    if not terraform_blocks and "TFWHY-TF-001" not in skipped:
        findings.append(StandardFinding("TFWHY-TF-001", "Medium", None, "No Terraform required_version constraint was found.", "No terraform block with required_version was detected.", "Add a bounded required_version constraint."))
    for block in terraform_blocks:
        constraint = _attribute_value(block.body, "required_version")
        if constraint is None and "TFWHY-TF-001" not in skipped:
            findings.append(StandardFinding("TFWHY-TF-001", "Medium", str(block.path), "The Terraform block has no required_version constraint.", "required_version is absent.", "Add a bounded required_version constraint."))
        elif constraint is not None and _is_unbounded(constraint) and "TFWHY-TF-002" not in skipped:
            findings.append(StandardFinding("TFWHY-TF-002", "Low", str(block.path), "The Terraform version constraint is not bounded.", "The constraint has no upper compatibility bound.", "Use a bounded constraint such as ~> or an explicit upper bound."))

        if "required_providers" not in block.body and "TFWHY-PROVIDER-001" not in skipped:
            findings.append(StandardFinding("TFWHY-PROVIDER-001", "Medium", str(block.path), "No required provider constraints were found.", "required_providers is absent.", "Declare required providers with source and version constraints."))
        elif "required_providers" in block.body:
            provider_section = block.body.split("required_providers", 1)[1]
            versions = re.findall(r"\bversion\s*=\s*\"([^\"]+)\"", provider_section)
            if not versions and "TFWHY-PROVIDER-001" not in skipped:
                findings.append(StandardFinding("TFWHY-PROVIDER-001", "Medium", str(block.path), "A required_providers block has no provider version constraints.", "No version attribute was detected in required_providers.", "Pin each provider to a bounded compatible constraint."))
            elif any(_is_unbounded(version) for version in versions) and "TFWHY-PROVIDER-002" not in skipped:
                findings.append(StandardFinding("TFWHY-PROVIDER-002", "Low", str(block.path), "At least one provider constraint is not bounded.", "A provider constraint has no upper compatibility bound.", "Use a bounded provider constraint."))
    return findings


def _configuration_findings(blocks: tuple[_Block, ...], required_tags: tuple[str, ...], skipped: set[str]) -> list[StandardFinding]:
    findings: list[StandardFinding] = []
    for block in blocks:
        if block.kind in {"variable", "output"} and not _has_attribute(block.body, "description") and "TFWHY-DOC-001" not in skipped:
            findings.append(StandardFinding("TFWHY-DOC-001", "Low", str(block.path), f"The {block.kind} block has no description.", "description is absent.", f"Add a description to the {block.kind} block."))
        if block.kind == "resource":
            findings.extend(_resource_findings(block, required_tags, skipped))
            if block.second_label and not _SNAKE_CASE.fullmatch(block.second_label) and "TFWHY-NAME-001" not in skipped:
                findings.append(StandardFinding("TFWHY-NAME-001", "Low", str(block.path), "The resource name does not follow lowercase snake_case.", "The resource label violates the configured basic naming convention.", "Rename the resource using lowercase letters, digits, and underscores."))
    return findings


def _resource_findings(block: _Block, required_tags: tuple[str, ...], skipped: set[str]) -> list[StandardFinding]:
    findings: list[StandardFinding] = []
    body = block.body
    resource_type = block.first_label or ""
    if resource_type.startswith("aws_") and resource_type not in {"aws_security_group_rule", "aws_iam_policy", "aws_iam_role_policy"} and required_tags and "TFWHY-TAG-001" not in skipped:
        tags_match = re.search(r"\btags\s*=\s*\{(.*?)\}", body, re.DOTALL)
        if tags_match:
            present = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*=", tags_match.group(1), re.MULTILINE))
            missing = [tag for tag in required_tags if tag not in present]
        elif re.search(r"\btags\s*=", body):
            missing = []
        else:
            missing = list(required_tags)
        for tag in missing:
            findings.append(StandardFinding("TFWHY-TAG-001", "Medium", str(block.path), "A taggable AWS resource is missing a required tag.", f"Required tag {tag!r} was not found in a literal tags map.", "Add the required tag or configure the applicable tag policy."))

    if resource_type == "aws_security_group" and "TFWHY-SEC-001" not in skipped:
        ingress_blocks = re.findall(r"\bingress\s*\{(.*?)\}", body, re.DOTALL)
        if any(_PUBLIC_IPV4.search(ingress) or _PUBLIC_IPV6.search(ingress) for ingress in ingress_blocks):
            findings.append(StandardFinding("TFWHY-SEC-001", "High", str(block.path), "A security-group ingress rule permits public network access.", "An ingress block contains an unrestricted IPv4 or IPv6 source.", "Restrict ingress sources to the smallest required CIDR ranges and ports."))

    if resource_type in {"aws_ebs_volume", "aws_db_instance", "aws_rds_cluster", "aws_s3_bucket"} and "TFWHY-SEC-002" not in skipped:
        encrypted = re.search(r"\b(?:encrypted|storage_encrypted)\s*=\s*true\b", body)
        s3_encryption = "server_side_encryption_configuration" in body
        if not encrypted and not (resource_type == "aws_s3_bucket" and s3_encryption):
            findings.append(StandardFinding("TFWHY-SEC-002", "Medium", str(block.path), "A supported storage resource has no explicit encryption configuration.", "No explicit encryption setting was detected for this resource type.", "Enable the provider-supported encryption setting and verify the resulting plan."))
    return findings


def _terraform_tool_findings(config_dir: Path, skipped: set[str]) -> list[StandardFinding]:
    findings: list[StandardFinding] = []
    commands = (("TFWHY-FMT-001", ("terraform", "fmt", "-check", "-recursive"), "Terraform formatting check failed.", "Run terraform fmt and review the resulting formatting."), ("TFWHY-VALIDATE-001", ("terraform", "validate", "-no-color"), "Terraform validation failed.", "Fix the reported Terraform configuration errors and rerun validation."))
    for rule_id, command, explanation, remediation in commands:
        if rule_id in skipped:
            continue
        try:
            result = subprocess.run(command, cwd=config_dir, capture_output=True, text=True, check=False, timeout=60)
        except FileNotFoundError:
            if "TFWHY-TOOL-001" not in skipped:
                findings.append(StandardFinding("TFWHY-TOOL-001", "Info", None, "Terraform is not installed; Terraform-dependent checks were unavailable.", "The terraform executable was not found.", "Install Terraform to enable formatting and validation checks."))
            return findings
        except (OSError, subprocess.TimeoutExpired):
            findings.append(StandardFinding(rule_id, "Medium", None, explanation, "Terraform could not complete the requested check.", remediation))
            continue
        if result.returncode != 0:
            findings.append(StandardFinding(rule_id, "Medium", None, explanation, "Terraform returned a failing status for the requested check.", remediation))
    return findings


def _attribute_value(body: str, attribute: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(attribute)}\s*=\s*\"([^\"]+)\"", body, re.MULTILINE)
    return match.group(1) if match else None


def _has_attribute(body: str, attribute: str) -> bool:
    return any(match.group(1) == attribute for match in (_ATTRIBUTE.match(line) for line in body.splitlines()) if match)


def _is_unbounded(constraint: str) -> bool:
    return constraint.strip() in {"*", ">=", "~"} or (">=" in constraint and "<" not in constraint and "~>" not in constraint)