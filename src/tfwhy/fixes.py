"""Deterministic Terraform refactoring proposals and plan verification."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .analyzer import PlanError, PlanSummary, ResourceSummary

_FINDING_ID = re.compile(r"^TFWHY-(\d+)$")
_INDEX = re.compile(r"^(?P<base>.+)\[(?P<key>\"[^\"]+\"|\d+)\]$")


class FixError(ValueError):
    """A requested fix cannot be proposed or safely applied."""


@dataclass(frozen=True)
class FixProposal:
    finding_id: str
    kind: str | None
    status: str
    summary: str
    rationale: str
    diff: str | None
    from_address: str | None = None
    to_address: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    status: str
    kind: str
    from_address: str
    to_address: str
    explanation: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def propose_fix(summary: PlanSummary, finding_id: str, config_dir: Path) -> FixProposal:
    if not config_dir.is_dir():
        raise FixError("configuration directory not found or is not a directory")
    resource = _resource_for_finding(summary, finding_id)
    if resource is None or not resource.previous_address:
        return FixProposal(finding_id, None, "inconclusive", "No safe fix was generated.", "The selected replacement has no unambiguous previous address.", None)
    old_address = resource.previous_address
    new_address = resource.address
    old_index = _INDEX.fullmatch(old_address)
    new_index = _INDEX.fullmatch(new_address)
    if old_index and new_index and old_index.group("base") == new_index.group("base"):
        if old_index.group("key").isdigit() and new_index.group("key").startswith('"'):
            return _proposal(finding_id, "count_to_for_each", old_address, new_address, "The plan provides one numeric-to-string instance mapping.", "Use the explicit instance mapping in a moved block, then review the for_each configuration separately.")
        return FixProposal(finding_id, "count_to_for_each", "rejected", "No safe fix was generated.", "The count-to-for_each mapping is not an unambiguous numeric-to-string transition.", None, old_address, new_address)
    if old_address != new_address and _same_resource_identity(old_address, new_address):
        return _proposal(finding_id, "resource_rename", old_address, new_address, "The plan provides one previous and one current address for the same resource identity.", "Preserve Terraform state identity with a moved block before reviewing the resulting plan.")
    return FixProposal(finding_id, None, "rejected", "No safe fix was generated.", "The address change is ambiguous or unsupported by the initial refactoring scope.", None, old_address, new_address)


def apply_proposal(proposal: FixProposal, config_dir: Path) -> Path:
    if proposal.status != "proposed" or not proposal.diff:
        raise FixError("only a proposed fix can be applied")
    target = config_dir / "moved.tf"
    if target.exists():
        raise FixError("moved.tf already exists; refusing to overwrite it")
    content = _moved_block(proposal.from_address or "", proposal.to_address or "")
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise FixError("could not write the approved proposal") from exc
    return target


def verify_plan(summary: PlanSummary, from_address: str, to_address: str, kind: str) -> VerificationResult:
    if kind not in {"resource_rename", "count_to_for_each"}:
        raise FixError("unsupported verification kind")
    current = next((resource for resource in summary.resources if resource.address == to_address), None)
    old_present = any(resource.address == from_address for resource in summary.resources)
    if current is None:
        return VerificationResult("inconclusive", kind, from_address, to_address, "The expected target address is not present in the supplied plan.", ("Target address was not found.",))
    if old_present or current.category != "no-op":
        return VerificationResult("not_verified", kind, from_address, to_address, "The supplied plan still contains an unexpected old address or a non-no-op target action.", (f"Target action category: {current.category}.", f"Old address present: {old_present}."))
    return VerificationResult("verified", kind, from_address, to_address, "The supplied plan shows the target address as no-op and contains no old address.", ("Target action category: no-op.", "Old address is absent."))


def _resource_for_finding(summary: PlanSummary, finding_id: str) -> ResourceSummary | None:
    match = _FINDING_ID.fullmatch(finding_id)
    if not match:
        raise FixError("finding ID must have the form TFWHY-NNN")
    index = int(match.group(1)) - 1
    replacements = [resource for resource in summary.resources if resource.category == "replace"]
    if index < 0 or index >= len(replacements):
        raise FixError("finding ID does not identify a replacement in this plan")
    return replacements[index]


def _proposal(finding_id: str, kind: str, old_address: str, new_address: str, summary: str, rationale: str) -> FixProposal:
    return FixProposal(finding_id, kind, "proposed", summary, rationale, _unified_diff(old_address, new_address), old_address, new_address)


def _unified_diff(old_address: str, new_address: str) -> str:
    content = _moved_block(old_address, new_address)
    line_count = len(content.splitlines())
    return f"diff --git a/moved.tf b/moved.tf\nnew file mode 100644\n--- /dev/null\n+++ b/moved.tf\n@@ -0,0 +1,{line_count} @@\n+" + "+".join(content.splitlines(True))


def _moved_block(old_address: str, new_address: str) -> str:
    return f"moved {{\n  from = {old_address}\n  to   = {new_address}\n}}\n"


def _same_resource_identity(old_address: str, new_address: str) -> bool:
    old_parts = old_address.split(".")
    new_parts = new_address.split(".")
    return (
        len(old_parts) == 2
        and len(new_parts) == 2
        and old_parts[0] == new_parts[0]
        and not _INDEX.search(old_address)
        and not _INDEX.search(new_address)
        and not old_address.startswith("module.")
        and not new_address.startswith("module.")
    )