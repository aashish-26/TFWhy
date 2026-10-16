"""Safe output formats for normalized Terraform plan metadata."""

from __future__ import annotations

import json

from .analyzer import PlanSummary
from .fixes import FixProposal, VerificationResult
from .history import HistoryError
from .standards import StandardsReport


def render_json(summary: PlanSummary) -> str:
    return json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n"


def render_markdown(summary: PlanSummary) -> str:
    counts = summary.counts()
    lines = ["# Terraform Plan Summary", "", f"- Format version: `{summary.format_version}`"]
    if summary.terraform_version:
        lines.append(f"- Terraform version: `{summary.terraform_version}`")
    lines.extend(["", "## Actions", "", "| Action | Count |", "| --- | ---: |"])
    lines.extend(f"| {category} | {counts[category]} |" for category in counts)
    lines.extend(["", "## Resources", ""])
    if not summary.resources:
        lines.append("No resource changes.")
    for resource in summary.resources:
        lines.append(f"- `{resource.address}` (`{resource.resource_type}`): **{resource.category}**")
        if resource.replacement_paths:
            lines.append(f"  - Replacement paths: {', '.join(f'`{path}`' for path in resource.replacement_paths)}")
        if resource.action_reason:
            lines.append(f"  - Action reason: `{resource.action_reason}`")
    if summary.replacement_findings:
        lines.extend(["", "## Replacement Findings", ""])
        for finding in summary.replacement_findings:
            lines.append(f"- `{finding.address}` (`{finding.resource_type}`): **{finding.confidence}**")
            lines.append(f"  - Triggering paths: {', '.join(f'`{path}`' for path in finding.triggering_paths) or 'not provided'}")
            lines.append(f"  - Explanation: {finding.explanation}")
            for evidence in finding.evidence:
                lines.append(f"  - Evidence: {evidence}")
    return "\n".join(lines) + "\n"


def render_terminal(summary: PlanSummary) -> str:
    counts = summary.counts()
    lines = [f"Terraform plan (format {summary.format_version})"]
    if summary.terraform_version:
        lines.append(f"Terraform version: {summary.terraform_version}")
    lines.append("Actions: " + ", ".join(f"{category}={counts[category]}" for category in counts))
    if not summary.resources:
        lines.append("Resources: none")
    else:
        lines.append("Resources:")
        for resource in summary.resources:
            lines.append(f"- {resource.address} ({resource.resource_type}): {resource.category}")
            if resource.replacement_paths:
                lines.append(f"  replacement paths: {', '.join(resource.replacement_paths)}")
            if resource.action_reason:
                lines.append(f"  action reason: {resource.action_reason}")
    _append_terminal_findings(lines, summary)
    return "\n".join(lines) + "\n"


def _append_terminal_findings(lines: list[str], summary: PlanSummary) -> None:
    if not summary.replacement_findings:
        return
    lines.extend(["Replacement findings:"])
    for finding in summary.replacement_findings:
        lines.append(f"- {finding.address} ({finding.resource_type}): {finding.confidence}")
        lines.append(f"  paths: {', '.join(finding.triggering_paths) or 'not provided'}")
        lines.append(f"  explanation: {finding.explanation}")
        for evidence in finding.evidence:
            lines.append(f"  evidence: {evidence}")


def render_review_json(report: StandardsReport) -> str:
    return json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"


def render_review_markdown(report: StandardsReport) -> str:
    lines = ["# Terraform Standards Review", ""]
    if not report.findings:
        lines.append("No findings.")
    for finding in report.findings:
        location = f" ({finding.location})" if finding.location else ""
        lines.extend([
            f"## {finding.rule_id}: {finding.severity}{location}",
            "",
            finding.explanation,
            "",
            f"- Evidence: {finding.evidence}",
            f"- Remediation: {finding.remediation}",
            "",
        ])
    return "\n".join(lines)


def render_review_terminal(report: StandardsReport) -> str:
    if not report.findings:
        return "Terraform standards review\nNo findings.\n"
    lines = ["Terraform standards review"]
    for finding in report.findings:
        location = f" ({finding.location})" if finding.location else ""
        lines.extend([
            f"- {finding.rule_id} [{finding.severity}]{location}: {finding.explanation}",
            f"  evidence: {finding.evidence}",
            f"  remediation: {finding.remediation}",
        ])
    return "\n".join(lines) + "\n"


def render_fix_json(proposal: FixProposal) -> str:
    return json.dumps(proposal.as_dict(), indent=2, sort_keys=True) + "\n"


def render_fix_markdown(proposal: FixProposal) -> str:
    lines = [f"# Terraform Fix Proposal: {proposal.finding_id}", "", f"- Status: **{proposal.status}**", f"- Kind: `{proposal.kind or 'unsupported'}`", "", proposal.summary, proposal.rationale]
    if proposal.diff:
        lines.extend(["", "```diff", proposal.diff.rstrip("\n"), "```"])
    return "\n".join(lines) + "\n"


def render_fix_terminal(proposal: FixProposal) -> str:
    lines = [f"Terraform fix proposal {proposal.finding_id} [{proposal.status}]", proposal.summary, f"Rationale: {proposal.rationale}"]
    if proposal.diff:
        lines.extend(["Proposed diff:", proposal.diff.rstrip("\n")])
    return "\n".join(lines) + "\n"


def render_verification_json(result: VerificationResult) -> str:
    return json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n"


def render_verification_markdown(result: VerificationResult) -> str:
    return f"# Terraform Verification\n\n- Status: **{result.status}**\n- Kind: `{result.kind}`\n- Explanation: {result.explanation}\n\n" + "\n".join(f"- Evidence: {item}" for item in result.evidence) + "\n"


def render_verification_terminal(result: VerificationResult) -> str:
    return "\n".join([f"Terraform verification: {result.status}", f"Kind: {result.kind}", result.explanation, *[f"Evidence: {item}" for item in result.evidence]]) + "\n"


def render_history_json(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def render_history_markdown(document: dict[str, object]) -> str:
    entries = document["entries"]
    lines = ["# Terraform Plan History", ""]
    if not entries:
        lines.append("No saved history entries.")
    for entry in entries:
        lines.extend([f"## Entry {entry['id']}", "", f"- Timestamp: `{entry['timestamp']}`", f"- Format version: `{entry['format_version']}`", f"- Resources: {len(entry['resources'])}", ""])
        for resource in entry["resources"]:
            recurrence = f"; observed in {resource['recurrence_count']} saved runs" if "recurrence_count" in resource else ""
            lines.append(f"- `{resource['address']}` (`{resource['resource_type']}`): **{resource['action']}**{recurrence}")
    return "\n".join(lines) + "\n"


def render_history_terminal(document: dict[str, object]) -> str:
    entries = document["entries"]
    if not entries:
        return "Terraform plan history\nNo saved history entries.\n"
    lines = ["Terraform plan history"]
    for entry in entries:
        lines.append(f"- Entry {entry['id']} ({entry['timestamp']}): {len(entry['resources'])} resources")
        for resource in entry["resources"]:
            recurrence = f"; observed in {resource['recurrence_count']} saved runs" if "recurrence_count" in resource else ""
            lines.append(f"  {resource['address']} ({resource['resource_type']}): {resource['action']}{recurrence}")
    return "\n".join(lines) + "\n"
