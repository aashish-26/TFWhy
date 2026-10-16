"""Load Terraform plan JSON and reduce it to safe, reportable metadata."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SUPPORTED_FORMAT_MAJOR = 1
FORMAT_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SUPPORTED_ACTION_REASONS = frozenset(
    {
        "replace_because_cannot_update",
        "replace_because_tainted",
        "replace_by_request",
        "delete_because_no_move",
        "read_because_config_unknown",
        "read_because_dependency_pending",
        "read_because_deferred",
    }
)
KNOWN_ACTIONS = frozenset({"create", "delete", "update", "read", "no-op"})


class PlanError(ValueError):
    """An input plan cannot be safely analyzed."""


@dataclass(frozen=True)
class ResourceSummary:
    address: str
    resource_type: str
    actions: tuple[str, ...]
    category: str
    replacement_paths: tuple[str, ...] = ()
    action_reason: str | None = None
    previous_address: str | None = None


@dataclass(frozen=True)
class ReplacementFinding:
    address: str
    resource_type: str
    triggering_paths: tuple[str, ...]
    evidence: tuple[str, ...]
    explanation: str
    confidence: str


@dataclass(frozen=True)
class StandardFinding:
    rule_id: str
    severity: str
    location: str | None
    explanation: str
    evidence: str
    remediation: str


@dataclass(frozen=True)
class PlanSummary:
    format_version: str
    terraform_version: str | None
    resources: tuple[ResourceSummary, ...]
    replacement_findings: tuple[ReplacementFinding, ...] = ()

    def counts(self) -> dict[str, int]:
        categories = ("create", "update", "delete", "replace", "read", "no-op")
        return {category: sum(item.category == category for item in self.resources) for category in categories}

    def as_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "terraform_version": self.terraform_version,
            "counts": self.counts(),
            "resources": [asdict(resource) for resource in self.resources],
            "replacement_findings": [asdict(finding) for finding in self.replacement_findings],
        }


def load_plan(path: Path) -> PlanSummary:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanError("plan file not found") from exc
    except (OSError, UnicodeError) as exc:
        raise PlanError(f"could not read plan file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"malformed JSON at line {exc.lineno}, column {exc.colno}") from exc

    if not isinstance(document, dict):
        raise PlanError("plan root must be a JSON object")
    format_version = document.get("format_version")
    if not isinstance(format_version, str):
        raise PlanError("missing or invalid format_version; expected a string")
    _validate_format_version(format_version)

    raw_changes = document.get("resource_changes", [])
    if raw_changes is None:
        raw_changes = []
    if not isinstance(raw_changes, list):
        raise PlanError("resource_changes must be an array")

    resources = tuple(_parse_resource_change(change, index) for index, change in enumerate(raw_changes))
    terraform_version = document.get("terraform_version")
    if terraform_version is not None and not isinstance(terraform_version, str):
        raise PlanError("terraform_version must be a string when present")
    return PlanSummary(format_version, terraform_version, resources)


def _validate_format_version(format_version: str) -> None:
    match = FORMAT_VERSION_PATTERN.fullmatch(format_version)
    if match is None:
        raise PlanError("malformed plan format_version; expected MAJOR.MINOR")
    major = int(match.group(1))
    if major != SUPPORTED_FORMAT_MAJOR:
        raise PlanError(f"unsupported plan format major version {major}; supported major version: {SUPPORTED_FORMAT_MAJOR}")


def _parse_resource_change(change: Any, index: int) -> ResourceSummary:
    if not isinstance(change, dict):
        raise PlanError(f"resource_changes[{index}] must be an object")
    address = change.get("address")
    resource_type = change.get("type")
    if not isinstance(address, str) or not address:
        raise PlanError(f"resource_changes[{index}] is missing a valid address")
    if not isinstance(resource_type, str) or not resource_type:
        raise PlanError(f"resource_changes[{index}] is missing a valid type")

    change_data = change.get("change")
    if not isinstance(change_data, dict):
        raise PlanError(f"resource_changes[{index}] is missing a change object")
    actions = change_data.get("actions")
    if not isinstance(actions, list) or not actions or not all(isinstance(action, str) for action in actions):
        raise PlanError(f"resource_changes[{index}] is missing valid actions")
    if any(action not in KNOWN_ACTIONS for action in actions):
        raise PlanError(f"resource_changes[{index}] contains an unsupported action")

    replace_paths = change_data.get("replace_paths", [])
    if replace_paths is None:
        replace_paths = []
    if not isinstance(replace_paths, list) or not all(_valid_path(path) for path in replace_paths):
        raise PlanError(f"resource_changes[{index}] contains malformed replacement paths")
    action_reason = change.get("action_reason")
    if not isinstance(action_reason, str) or action_reason not in SUPPORTED_ACTION_REASONS:
        action_reason = None
    action_tuple = tuple(actions)
    category = _category(action_tuple)
    previous_address = change.get("previous_address")
    if previous_address is not None and (not isinstance(previous_address, str) or not previous_address):
        raise PlanError(f"resource_changes[{index}] contains an invalid previous address")
    return ResourceSummary(
        address=address,
        resource_type=resource_type,
        actions=action_tuple,
        category=category,
        replacement_paths=tuple(_path_text(path) for path in replace_paths),
        action_reason=action_reason,
        previous_address=previous_address,
    )


def _valid_path(path: Any) -> bool:
    return isinstance(path, list) and bool(path) and all(isinstance(part, (str, int)) and not isinstance(part, bool) for part in path)


def _path_text(path: list[str | int]) -> str:
    result = ""
    for part in path:
        result += f"[{part}]" if isinstance(part, int) else (f".{part}" if result else part)
    return result or "<root>"


def _category(actions: tuple[str, ...]) -> str:
    if set(actions) == {"create", "delete"} and len(actions) == 2:
        return "replace"
    if len(actions) == 1:
        return actions[0]
    raise PlanError("resource actions must be one action or a create/delete replacement")
