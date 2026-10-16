"""Deterministic replacement-cause analysis using safe plan and config metadata."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .analyzer import PlanError, PlanSummary, ReplacementFinding, ResourceSummary

_RESOURCE_HEADER = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{')
_ATTRIBUTE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
_DYNAMIC_EXPRESSION = re.compile(r"\b(timestamp|plantimestamp|timeadd)\s*\(|\brandom_[A-Za-z0-9_]*\b")
_DATA_SOURCE = re.compile(r"\bdata\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+\b")
_INDEXED_ADDRESS = re.compile(r"\[[^]]+\]")


def analyze_replacements(summary: PlanSummary, config_dir: Path | None = None) -> PlanSummary:
    """Add replacement findings without retaining Terraform expressions or values."""
    blocks = _load_resource_blocks(config_dir) if config_dir is not None else ()
    findings = tuple(_analyze_resource(resource, blocks) for resource in summary.resources if resource.category == "replace")
    return replace(summary, replacement_findings=findings)


def _analyze_resource(resource: ResourceSummary, blocks: tuple[tuple[Path, int, str, str, str], ...]) -> ReplacementFinding:
    evidence: list[str] = []
    likely_patterns: list[str] = []
    confidence = "Unknown"

    if resource.replacement_paths:
        evidence.append("Terraform reported replacement path(s): " + ", ".join(resource.replacement_paths))
    if resource.action_reason:
        evidence.append(f"Terraform reported action reason: {resource.action_reason}")
        if resource.action_reason in {"replace_because_tainted", "replace_by_request"}:
            confidence = "Confirmed"

    if resource.previous_address and resource.previous_address != resource.address:
        evidence.append("Terraform reported a previous resource address different from the planned address")
        if _has_index(resource.previous_address) or _has_index(resource.address):
            likely_patterns.append("resource addressing changed through an indexed instance")

    candidates = tuple(block for block in blocks if block[3] == resource.resource_type and _address_name(resource.address) == block[4])
    matching_blocks = candidates if not resource.address.startswith("module.") and len(candidates) == 1 else ()
    for path in resource.replacement_paths:
        attribute = path.split(".", 1)[0].split("[", 1)[0]
        for file_path, line_number, body, _, _ in matching_blocks:
            attribute_lines = _attribute_lines(body, attribute)
            for relative_line in attribute_lines:
                line = body.splitlines()[relative_line - 1]
                if _DYNAMIC_EXPRESSION.search(line):
                    likely_patterns.append(f"{attribute} uses a timestamp or random expression")
                    evidence.append(f"configuration evidence at {file_path}:{line_number + relative_line - 1} matches a dynamic {attribute} expression")
                elif _DATA_SOURCE.search(line):
                    likely_patterns.append(f"{attribute} references a data source")
                    evidence.append(f"configuration evidence at {file_path}:{line_number + relative_line - 1} references a data source for {attribute}")
                elif attribute == "user_data":
                    evidence.append(f"configuration evidence at {file_path}:{line_number + relative_line - 1} associates user_data with this resource")
    for file_path, line_number, body, _, _ in matching_blocks:
        if re.search(r"^\s*(count|for_each)\s*=", body, re.MULTILINE):
            evidence.append(f"configuration evidence at {file_path}:{line_number} uses count or for_each")

    if likely_patterns and confidence != "Confirmed":
        confidence = "Likely"
    if likely_patterns:
        explanation = "Possible replacement cause: " + "; ".join(dict.fromkeys(likely_patterns)) + "."
    elif confidence == "Confirmed":
        explanation = "Terraform directly reported replacement metadata, but that metadata does not establish an upstream configuration root cause."
    else:
        explanation = "Terraform reported a replacement, but the available evidence is insufficient to determine the upstream root cause."

    return ReplacementFinding(
        address=resource.address,
        resource_type=resource.resource_type,
        triggering_paths=resource.replacement_paths,
        evidence=tuple(dict.fromkeys(evidence)),
        explanation=explanation,
        confidence=confidence,
    )


def _load_resource_blocks(config_dir: Path | None) -> tuple[tuple[Path, int, str, str, str], ...]:
    if config_dir is None:
        return ()
    if not config_dir.is_dir():
        raise PlanError("configuration directory not found or is not a directory")
    blocks: list[tuple[Path, int, str, str, str]] = []
    try:
        files = sorted(path for path in config_dir.glob("*.tf") if ".terraform" not in path.parts)
    except OSError as exc:
        raise PlanError("could not inspect configuration directory") from exc
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for index, line in enumerate(lines):
            match = _RESOURCE_HEADER.match(line)
            if not match:
                continue
            depth = line.count("{") - line.count("}")
            body_lines = [line]
            cursor = index + 1
            while depth > 0 and cursor < len(lines):
                body_lines.append(lines[cursor])
                depth += lines[cursor].count("{") - lines[cursor].count("}")
                cursor += 1
            blocks.append((path.relative_to(config_dir), index + 1, "\n".join(body_lines), match.group(1), match.group(2)))
    return tuple(blocks)


def _attribute_lines(body: str, attribute: str) -> tuple[int, ...]:
    return tuple(index for index, line in enumerate(body.splitlines(), start=1) if _ATTRIBUTE.match(line) and _ATTRIBUTE.match(line).group(1) == attribute)


def _address_name(address: str) -> str:
    base = address.split(".")[-1]
    return re.sub(r"\[[^]]+\]$", "", base)


def _has_index(address: str) -> bool:
    return _INDEXED_ADDRESS.search(address) is not None
