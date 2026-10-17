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
_VARIABLE_REFERENCE = re.compile(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)\b")
_HEREDOC = re.compile(r"<<-?\s*(?:\"(?P<quoted>[A-Za-z_][A-Za-z0-9_]*)\"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")
_IAM_POLICY_RESOURCES = frozenset({"aws_iam_policy", "aws_iam_role_policy"})
_SENSITIVE_NETWORK_PORTS = frozenset({22, 3389})
_LITERAL_PROVIDER_SOURCE = re.compile(r'^\s*source\s*=\s*"(?P<source>[^"]+)"\s*(?://.*|#.*)?$', re.MULTILINE)


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
    # A blank policy key previously became a misleading "missing tag ''"
    # finding. Reject invalid operator input instead of inventing a policy.
    if any(not isinstance(tag, str) or not tag.strip() for tag in required):
        raise PlanError("required tag names must be non-empty strings")
    variable_defaults = _variable_defaults(blocks)
    findings: list[StandardFinding] = []
    findings.extend(_malformed_findings(malformed_files, skipped))
    findings.extend(_version_findings(blocks, skipped))
    findings.extend(_configuration_findings(blocks, required, skipped, variable_defaults))
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
            # Braces inside strings such as "${var.name}" are not structural
            # HCL braces. Count only lexical braces so a resource cannot absorb
            # a later block and create false policy findings.
            depth = 0
            block_comment = False
            heredoc: str | None = None
            body_lines = [line]
            cursor = index + 1
            delta, block_comment, heredoc = _brace_delta(line, block_comment, heredoc)
            depth += delta
            while depth > 0 and cursor < len(lines):
                body_lines.append(lines[cursor])
                delta, block_comment, heredoc = _brace_delta(lines[cursor], block_comment, heredoc)
                depth += delta
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
            # HashiCorp documents this source as an old provider that is
            # incompatible with Terraform 0.11+. Restrict the check to a
            # literal line so comments and computed provider selections stay
            # inconclusive instead of receiving invented migration advice.
            if (
                "TFWHY-UPGRADE-001" not in skipped
                and "hashicorp/terraform" in _literal_provider_sources(provider_section)
            ):
                findings.append(StandardFinding(
                    "TFWHY-UPGRADE-001",
                    "Medium",
                    str(block.path),
                    "The legacy hashicorp/terraform provider source is incompatible with Terraform 0.11 and later.",
                    "A literal required_providers source is hashicorp/terraform.",
                    "Remove the legacy provider requirement and use Terraform's built-in provider features where applicable; review the resulting configuration and plan.",
                ))
    return findings


def _configuration_findings(blocks: tuple[_Block, ...], required_tags: tuple[str, ...], skipped: set[str], variable_defaults: dict[str, str]) -> list[StandardFinding]:
    findings: list[StandardFinding] = []
    for block in blocks:
        if block.kind in {"variable", "output"} and not _has_attribute(block.body, "description") and "TFWHY-DOC-001" not in skipped:
            findings.append(StandardFinding("TFWHY-DOC-001", "Low", str(block.path), f"The {block.kind} block has no description.", "description is absent.", f"Add a description to the {block.kind} block."))
        if block.kind == "resource":
            findings.extend(_resource_findings(block, required_tags, skipped, variable_defaults))
            if block.second_label and not _SNAKE_CASE.fullmatch(block.second_label) and "TFWHY-NAME-001" not in skipped:
                findings.append(StandardFinding("TFWHY-NAME-001", "Low", str(block.path), "The resource name does not follow lowercase snake_case.", "The resource label violates the configured basic naming convention.", "Rename the resource using lowercase letters, digits, and underscores."))
    return findings


def _resource_findings(block: _Block, required_tags: tuple[str, ...], skipped: set[str], variable_defaults: dict[str, str]) -> list[StandardFinding]:
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
        if any(_public_ingress(ingress, variable_defaults) for ingress in ingress_blocks):
            findings.append(StandardFinding("TFWHY-SEC-001", "High", str(block.path), "A security-group ingress rule permits public network access.", "An ingress block contains an unrestricted IPv4 or IPv6 source.", "Restrict ingress sources to the smallest required CIDR ranges and ports."))

    # Keep IAM and network analysis narrow: it only emits a finding for static,
    # directly visible configuration. Expressions it cannot inspect are not
    # treated as either safe or unsafe.
    findings.extend(_permission_findings(block, skipped))

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


def _literal_provider_sources(content: str) -> frozenset[str]:
    """Return only directly declared provider sources from simple HCL lines."""
    return frozenset(match.group("source") for match in _LITERAL_PROVIDER_SOURCE.finditer(content))


def _variable_defaults(blocks: tuple[_Block, ...]) -> dict[str, str]:
    return {
        block.first_label: default
        for block in blocks
        if block.kind == "variable"
        and block.first_label
        and (default := _attribute_value(block.body, "default")) is not None
    }


def _public_ingress(ingress: str, variable_defaults: dict[str, str]) -> bool:
    if _PUBLIC_IPV4.search(ingress) or _PUBLIC_IPV6.search(ingress):
        return True
    return any(
        variable_defaults.get(variable_name) in {"0.0.0.0/0", "::/0"}
        for variable_name in _VARIABLE_REFERENCE.findall(ingress)
    )


def _permission_findings(block: _Block, skipped: set[str]) -> list[StandardFinding]:
    """Return evidence-backed IAM and network findings for supported literals."""
    resource_type = block.first_label or ""
    findings: list[StandardFinding] = []
    if resource_type in _IAM_POLICY_RESOURCES:
        for statement in _allow_policy_statements(block.body):
            # A Deny wildcard has different semantics and is not evidence of an
            # overly broad grant. Only literal Allow statements enter this rule.
            if _literal_attribute(statement, "Effect") != "Allow":
                continue
            actions = _literal_attribute_strings(statement, "Action")
            resources = _literal_attribute_strings(statement, "Resource")
            if actions is not None and "TFWHY-IAM-001" not in skipped:
                if "*" in actions:
                    findings.append(StandardFinding("TFWHY-IAM-001", "High", str(block.path), "An IAM Allow statement grants all actions.", "A statically parsed Allow statement has Action set to a global wildcard.", "Replace the wildcard with the smallest set of required service actions and review the resulting policy."))
                elif any(action.endswith(":*") for action in actions):
                    findings.append(StandardFinding("TFWHY-IAM-001", "Medium", str(block.path), "An IAM Allow statement grants every action in a service.", "A statically parsed Allow statement has a service action wildcard.", "Replace the service wildcard with the smallest set of required actions and review the resulting policy."))
            if resources is not None and "*" in resources and "TFWHY-IAM-002" not in skipped:
                findings.append(StandardFinding("TFWHY-IAM-002", "Medium", str(block.path), "An IAM Allow statement applies to every resource.", "A statically parsed Allow statement has Resource set to a global wildcard.", "Restrict the policy to required resource ARNs where the service supports them."))

    if resource_type == "aws_security_group":
        for egress in re.findall(r"\begress\s*\{(.*?)\}", block.body, re.DOTALL):
            if _allows_all_public_egress(egress) and "TFWHY-NET-002" not in skipped:
                findings.append(StandardFinding("TFWHY-NET-002", "Medium", str(block.path), "A security-group egress rule permits all outbound traffic.", "A statically parsed egress block allows all protocols to an unrestricted IPv4 or IPv6 destination.", "Restrict egress destinations, protocols, and ports to the services the workload needs."))

    if resource_type == "aws_security_group_rule":
        rule_type = _literal_attribute(block.body, "type")
        if rule_type == "ingress" and _contains_public_cidr(block.body) and "TFWHY-SEC-001" not in skipped:
            findings.append(StandardFinding("TFWHY-SEC-001", "High", str(block.path), "A standalone security-group rule permits public network ingress.", "A statically parsed ingress rule contains an unrestricted IPv4 or IPv6 source.", "Restrict ingress sources to the smallest required CIDR ranges and ports."))
        if rule_type == "egress" and _allows_all_public_egress(block.body) and "TFWHY-NET-002" not in skipped:
            findings.append(StandardFinding("TFWHY-NET-002", "Medium", str(block.path), "A standalone security-group rule permits all outbound traffic.", "A statically parsed egress rule allows all protocols to an unrestricted IPv4 or IPv6 destination.", "Restrict egress destinations, protocols, and ports to the services the workload needs."))

    if resource_type == "aws_network_acl_rule" and _risky_public_network_acl_ingress(block.body) and "TFWHY-NET-003" not in skipped:
        findings.append(StandardFinding("TFWHY-NET-003", "Medium", str(block.path), "A network ACL allows public ingress to a sensitive port or all protocols.", "A statically parsed inbound Allow rule uses an unrestricted source and exposes SSH, RDP, or all protocols. This does not establish reachability or exploitability.", "Restrict the source CIDR and limit the ports to the required network path."))
    return findings


def _allow_policy_statements(body: str) -> tuple[str, ...]:
    """Extract only literal jsonencode Allow statements; unknown syntax is skipped."""
    policy_start = re.search(r"\bpolicy\s*=\s*jsonencode\s*\(", body)
    if policy_start is None:
        return ()
    map_start = body.find("{", policy_start.end())
    if map_start < 0:
        return ()
    policy_end = _matching_delimiter(body, map_start, "{", "}")
    if policy_end is None:
        return ()
    policy = body[map_start : policy_end + 1]
    statement_start = re.search(r"\bStatement\s*=\s*\[", policy)
    if statement_start is None:
        return ()
    list_start = policy.find("[", statement_start.start())
    list_end = _matching_delimiter(policy, list_start, "[", "]")
    if list_end is None:
        return ()
    return _top_level_objects(policy[list_start + 1 : list_end])


def _top_level_objects(content: str) -> tuple[str, ...]:
    """Keep only a simple list of object statements, not computed expressions."""
    statements: list[str] = []
    cursor = 0
    while cursor < len(content):
        while cursor < len(content) and (content[cursor].isspace() or content[cursor] == ","):
            cursor += 1
        if cursor == len(content):
            break
        if content[cursor] != "{":
            return ()
        end = _matching_delimiter(content, cursor, "{", "}")
        if end is None:
            return ()
        statements.append(content[cursor : end + 1])
        cursor = end + 1
    return tuple(statements)


def _literal_attribute_strings(content: str, attribute: str) -> tuple[str, ...] | None:
    """Read a quoted string or list of quoted strings, rejecting expressions."""
    match = re.search(rf"\b{re.escape(attribute)}\s*=\s*", content)
    if match is None:
        return None
    value = content[match.end() :].lstrip()
    if value.startswith('"'):
        end = _quoted_end(value)
        return (value[1:end],) if end is not None else None
    if not value.startswith("["):
        return None
    end = _matching_delimiter(value, 0, "[", "]")
    if end is None:
        return None
    items = value[1:end]
    # Remove quoted strings before checking the remaining syntax. This prevents
    # a computed list item from being mistaken for a literal IAM permission.
    strings = re.findall(r'"((?:[^"\\]|\\.)*)"', items)
    remainder = re.sub(r'"(?:[^"\\]|\\.)*"', "", items).replace(",", "").strip()
    return tuple(strings) if strings and not remainder else None


def _literal_attribute(content: str, attribute: str) -> str | None:
    values = _literal_attribute_strings(content, attribute)
    if values is not None and len(values) == 1:
        return values[0]
    # Network booleans and ports are often unquoted HCL scalars. Only accept
    # simple literals; references and arithmetic stay outside this scanner.
    match = re.search(rf"\b{re.escape(attribute)}\s*=\s*(true|false|-?\d+)\b", content)
    return match.group(1) if match else None


def _contains_public_cidr(content: str) -> bool:
    return _PUBLIC_IPV4.search(content) is not None or _PUBLIC_IPV6.search(content) is not None


def _allows_all_public_egress(content: str) -> bool:
    # Protocol -1 means all protocols in AWS security-group semantics. A public
    # CIDR without that protocol may be necessary for a narrowly scoped service.
    return _contains_public_cidr(content) and _literal_attribute(content, "protocol") == "-1"


def _risky_public_network_acl_ingress(content: str) -> bool:
    if _literal_attribute(content, "egress") != "false" or _literal_attribute(content, "rule_action") != "allow":
        return False
    if not _contains_public_cidr(content):
        return False
    if _literal_attribute(content, "protocol") == "-1":
        return True
    port = _literal_attribute(content, "from_port")
    return port is not None and port.isdigit() and int(port) in _SENSITIVE_NETWORK_PORTS


def _matching_delimiter(content: str, start: int, opening: str, closing: str) -> int | None:
    """Find a matching delimiter while ignoring quoted strings and escapes."""
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(content)):
        character = content[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _quoted_end(content: str) -> int | None:
    escaped = False
    for index, character in enumerate(content[1:], start=1):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return index
    return None


def _brace_delta(line: str, in_block_comment: bool, heredoc: str | None) -> tuple[int, bool, str | None]:
    """Return structural brace change for the scanner without parsing HCL values."""
    if heredoc is not None:
        return 0, in_block_comment, None if line.strip() == heredoc else heredoc
    depth = 0
    quoted = False
    escaped = False
    cursor = 0
    while cursor < len(line):
        character = line[cursor]
        following = line[cursor + 1] if cursor + 1 < len(line) else ""
        if in_block_comment:
            if character == "*" and following == "/":
                in_block_comment = False
                cursor += 2
                continue
            cursor += 1
            continue
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            cursor += 1
            continue
        if character == '"':
            quoted = True
        elif character == "#" or (character == "/" and following == "/"):
            break
        elif character == "/" and following == "*":
            in_block_comment = True
            cursor += 2
            continue
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        cursor += 1
    heredoc_match = _HEREDOC.search(_without_comment(line))
    return depth, in_block_comment, (heredoc_match.group("quoted") or heredoc_match.group("plain")) if heredoc_match else None


def _without_comment(line: str) -> str:
    quoted = False
    escaped = False
    for index, character in enumerate(line):
        following = line[index + 1] if index + 1 < len(line) else ""
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character == "#" or (character == "/" and following == "/"):
            return line[:index]
    return line


def _has_attribute(body: str, attribute: str) -> bool:
    return any(match.group(1) == attribute for match in (_ATTRIBUTE.match(line) for line in body.splitlines()) if match)


def _is_unbounded(constraint: str) -> bool:
    return constraint.strip() in {"*", ">=", "~"} or (">=" in constraint and "<" not in constraint and "~>" not in constraint)
