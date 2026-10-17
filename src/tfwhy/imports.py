"""Generate deliberately narrow Terraform import proposals.

Import identifiers are supplied by the caller rather than discovered from a
cloud account.  The proposal stays in memory until an explicit, non-existing
output path is approved for writing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


# A Terraform address is code, so validate it before putting it in generated
# HCL.  The supported grammar covers managed resources, module prefixes, and
# simple count/for_each instance keys; data-source targets are intentionally
# excluded because they cannot be imported.
_RESOURCE_ADDRESS = re.compile(
    r"^(?:module\.[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:\d+|\"[A-Za-z0-9_-]+\")\])?\.)*"
    r"(?P<resource_type>[A-Za-z_][A-Za-z0-9_-]*)\.(?P<resource_name>[A-Za-z_][A-Za-z0-9_-]*)"
    r"(?:\[(?:\d+|\"[A-Za-z0-9_-]+\")\])?$"
)


class ImportError(ValueError):
    """An import proposal cannot be made or safely written."""


@dataclass(frozen=True)
class ImportProposal:
    """A reviewable file proposal; the content is never saved automatically."""

    address: str
    output_path: Path
    can_write: bool
    status: str
    summary: str
    rationale: str
    starter_status: str
    diff: str
    content: str

    def as_dict(self) -> dict[str, object]:
        # `content` is represented once as a unified diff.  Keeping a second
        # copy out of JSON output reduces accidental exposure of an identifier.
        return {
            "address": self.address,
            "output_path": str(self.output_path),
            "status": self.status,
            "summary": self.summary,
            "rationale": self.rationale,
            "starter_status": self.starter_status,
            "diff": self.diff,
        }


def propose_import(
    address: str,
    import_id: str,
    output_path: Path | None = None,
    include_starter: bool = False,
) -> ImportProposal:
    """Create a diff from explicit input without reading state or cloud APIs."""
    match = _RESOURCE_ADDRESS.fullmatch(address)
    if match is None:
        # Do not echo caller input in errors: an import identifier or malformed
        # address may be sensitive and errors are often copied into CI logs.
        raise ImportError("import address must be a supported managed-resource address")
    if not isinstance(import_id, str) or not import_id:
        raise ImportError("import identifier must be a non-empty string")

    # A preview gets a predictable proposed filename.  Only `--out` makes a
    # path eligible for writing, which prevents an implicit project mutation.
    target = output_path or Path("tfwhy-import.tf")
    content, starter_status, rationale = _content_for_import(
        address,
        import_id,
        match.group("resource_type"),
        match.group("resource_name"),
        include_starter,
    )
    return ImportProposal(
        address=address,
        output_path=target,
        can_write=output_path is not None,
        status="proposed",
        summary="A Terraform import block was generated from the supplied address and identifier.",
        rationale=rationale,
        starter_status=starter_status,
        diff=_unified_diff(target, content),
        content=content,
    )


def apply_import_proposal(proposal: ImportProposal) -> Path:
    """Write only an approved proposal to an explicit, new file path."""
    if proposal.status != "proposed":
        raise ImportError("only a proposed import can be written")
    if not proposal.can_write:
        raise ImportError("writing an import requires an explicit --out path")
    if proposal.output_path.exists():
        raise ImportError("output path already exists; refusing to overwrite it")
    try:
        # Do not create parent directories: an explicit path must already point
        # to an existing project location, avoiding surprising filesystem work.
        proposal.output_path.write_text(proposal.content, encoding="utf-8")
    except OSError as exc:
        raise ImportError("could not write the approved import proposal") from exc
    return proposal.output_path


def _content_for_import(
    address: str,
    import_id: str,
    resource_type: str,
    resource_name: str,
    include_starter: bool,
) -> tuple[str, str, str]:
    # json.dumps produces a quoted, escaped string accepted by Terraform HCL.
    # It lets user-supplied identifiers contain quotes without becoming HCL code.
    content = f"import {{\n  to = {address}\n  id = {json.dumps(import_id)}\n}}\n"
    if not include_starter:
        return content, "not_requested", "No starter resource block was requested. Review the import block and provider documentation before writing configuration."

    # The S3 import ID is the bucket name, which is enough to produce a tiny,
    # truthful starter block. Other providers need schema-specific arguments;
    # guessing them would violate TFWhy's conservative generation policy.
    if resource_type == "aws_s3_bucket" and _is_root_unindexed(address):
        content += f"\nresource \"aws_s3_bucket\" \"{resource_name}\" {{\n  bucket = {json.dumps(import_id)}\n}}\n"
        return content, "generated", "The supplied import identifier is the bucket name for this supported aws_s3_bucket starter configuration."
    return content, "unavailable", "No starter resource block was generated because this resource type or address needs provider-specific required arguments not supplied to TFWhy."


def _is_root_unindexed(address: str) -> bool:
    # A starter block cannot represent a module instance or a count/for_each
    # instance without the surrounding module or repetition configuration.
    return address.count(".") == 1 and "[" not in address


def _unified_diff(target: Path, content: str) -> str:
    line_count = len(content.splitlines())
    return (
        f"diff --git a/{target.as_posix()} b/{target.as_posix()}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{target.as_posix()}\n"
        f"@@ -0,0 +1,{line_count} @@\n"
        + "+".join(content.splitlines(True))
    )
