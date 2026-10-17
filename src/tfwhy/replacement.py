"""Conservative replacement analysis from safe plan and configuration metadata.

This is intentionally a small HCL-aware scanner, not a Terraform evaluator. It
only follows local modules with a literal source and single-line direct
expressions. Anything more complex remains inconclusive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from .analyzer import PlanError, PlanSummary, ReplacementFinding, ResourceSummary

_RESOURCE_HEADER = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{')
_VARIABLE_HEADER = re.compile(r'^\s*variable\s+"([^"]+)"\s*\{')
_MODULE_HEADER = re.compile(r'^\s*module\s+"([^"]+)"\s*\{')
_LOCALS_HEADER = re.compile(r"^\s*locals\s*\{")
_ATTRIBUTE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")
_DIRECT_REFERENCE = re.compile(
    r"^(?P<reference>(?:var|local)\.[A-Za-z_][A-Za-z0-9_]*|"
    r"data\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*|"
    r"[A-Za-z0-9_]+\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)$"
)
_LITERAL_STRING = re.compile(r'^"(?P<value>(?:[^"\\]|\\.)*)"$')
_DYNAMIC_EXPRESSION = re.compile(r"\b(timestamp|plantimestamp|timeadd)\s*\(|\brandom_[A-Za-z0-9_]*\.")
_INDEXED_ADDRESS = re.compile(r"\[[^]]+\]")
_HEREDOC = re.compile(r"<<-?\s*(?:\"(?P<quoted>[A-Za-z_][A-Za-z0-9_]*)\"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))")


@dataclass(frozen=True)
class _Attribute:
    name: str
    line: int
    expression: str


@dataclass(frozen=True)
class _Block:
    kind: str
    labels: tuple[str, ...]
    path: Path
    line: int
    body: tuple[str, ...]
    module_address: str
    attributes: tuple[_Attribute, ...]


@dataclass(frozen=True)
class _Configuration:
    # These are scanner-internal records. Expressions are retained only while
    # evaluating a local report and never escape into findings or renderers.
    resources: tuple[_Block, ...]
    variables: tuple[_Block, ...]
    locals: tuple[_Block, ...]


def analyze_replacements(summary: PlanSummary, config_dir: Path | None = None) -> PlanSummary:
    """Add replacement findings without retaining Terraform expressions or values."""
    # Plan metadata is useful on its own. Configuration inspection is optional
    # so `tfwhy explain plan.json` remains local, deterministic, and credential-free.
    configuration = _load_configuration(config_dir) if config_dir is not None else _Configuration((), (), ())
    findings = tuple(_analyze_resource(resource, configuration) for resource in summary.resources if resource.category == "replace")
    return replace(summary, replacement_findings=findings)


def _analyze_resource(resource: ResourceSummary, configuration: _Configuration) -> ReplacementFinding:
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
            evidence.append("Terraform reported indexed addressing; count or for_each alone does not establish a replacement cause")

    # Instance keys identify copies of the same declaration. Match the declared
    # module/type/name identity, but retain the original indexed plan address in
    # the user-facing finding.
    matching_blocks = tuple(block for block in configuration.resources if _resource_address(block) == _unindexed_address(resource.address))
    # A duplicate exact address is malformed or ambiguous configuration. Do not
    # guess which declaration Terraform used.
    if len(matching_blocks) == 1:
        block = matching_blocks[0]
        for path in resource.replacement_paths:
            attribute = path.split(".", 1)[0].split("[", 1)[0]
            match = _attribute(block, attribute)
            if match is not None:
                _trace_expression(
                    match.expression,
                    attribute,
                    block.module_address,
                    _location(block.path, match.line),
                    configuration,
                    evidence,
                    likely_patterns,
                    set(),
                )
        for addressing_attribute in ("count", "for_each"):
            match = _attribute(block, addressing_attribute)
            if match is not None:
                evidence.append(
                    f"configuration evidence at {_location(block.path, match.line)} declares {addressing_attribute}; "
                    "its presence does not establish a replacement cause"
                )

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


def _trace_expression(
    expression: str,
    attribute: str,
    module_address: str,
    location: str,
    configuration: _Configuration,
    evidence: list[str],
    likely_patterns: list[str],
    seen: set[tuple[str, str]],
) -> None:
    """Trace only a direct expression and never expose its value in findings."""
    if _DYNAMIC_EXPRESSION.search(expression):
        likely_patterns.append(f"{attribute} uses a timestamp or random expression")
        evidence.append(f"configuration evidence at {location} matches a dynamic {attribute} expression")
        return

    direct = _DIRECT_REFERENCE.fullmatch(expression.strip())
    if direct is None:
        return
    reference = direct.group("reference")
    if reference.startswith("data."):
        likely_patterns.append(f"{attribute} references a data source")
        evidence.append(f"configuration evidence at {location} references a data source for {attribute}")
        return
    if reference.startswith("var."):
        name = reference.split(".", 1)[1]
        target = _named_block(configuration.variables, module_address, name)
        if target is None:
            # An input may be supplied outside the scanned files. Without a
            # visible default there is no safe next edge to follow.
            return
        default = _attribute(target, "default")
        evidence.append(f"configuration evidence at {location} directly references variable {name}")
        if default is not None and ("var", name) not in seen:
            evidence.append(f"configuration evidence at {_location(target.path, default.line)} defines the referenced variable default")
            _trace_expression(default.expression, attribute, module_address, _location(target.path, default.line), configuration, evidence, likely_patterns, seen | {("var", name)})
        return
    if reference.startswith("local."):
        name = reference.split(".", 1)[1]
        target = _local_block(configuration, module_address, name)
        if target is None:
            # Locals can be assembled dynamically; only one visible direct
            # assignment is considered traceable.
            return
        local_value = _attribute(target, name)
        evidence.append(f"configuration evidence at {location} directly references local {name}")
        if local_value is not None and ("local", name) not in seen:
            evidence.append(f"configuration evidence at {_location(target.path, local_value.line)} defines the referenced local")
            _trace_expression(local_value.expression, attribute, module_address, _location(target.path, local_value.line), configuration, evidence, likely_patterns, seen | {("local", name)})
        return

    # A direct managed-resource reference links the replacement-triggering
    # attribute to a source declaration, but does not prove either value changed.
    target = _resource_reference(configuration.resources, module_address, reference)
    if target is not None:
        evidence.append(
            f"configuration evidence at {location} directly references resource declared at {_location(target.path, target.line)}"
        )


def _load_configuration(config_dir: Path | None) -> _Configuration:
    if config_dir is None:
        return _Configuration((), (), ())
    if not config_dir.is_dir():
        raise PlanError("configuration directory not found or is not a directory")
    root = config_dir.resolve()
    resources: list[_Block] = []
    variables: list[_Block] = []
    locals_blocks: list[_Block] = []
    # Terraform module addresses are built from calls, not directory names.
    # Start at the root and follow only literal local `source` attributes.
    pending: list[tuple[Path, str]] = [(root, "")]
    visited: set[tuple[Path, str]] = set()

    while pending:
        directory, module_address = pending.pop()
        key = (directory.resolve(), module_address)
        if key in visited:
            continue
        visited.add(key)
        try:
            files = sorted(directory.glob("*.tf"))
        except OSError:
            continue
        module_blocks: list[_Block] = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for block in _scan_blocks(lines, path.relative_to(root), module_address):
                if block.kind == "resource":
                    resources.append(block)
                elif block.kind == "variable":
                    variables.append(block)
                elif block.kind == "locals":
                    locals_blocks.append(block)
                elif block.kind == "module":
                    module_blocks.append(block)
        for block in module_blocks:
            source = _attribute(block, "source")
            if source is None:
                continue
            source_path = _literal_source(source.expression)
            if source_path is None:
                continue
            candidate = (directory / source_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                # Do not expand the read scope beyond the directory chosen by
                # the user, even when a local source points elsewhere.
                continue
            if candidate.is_dir():
                pending.append((candidate, _module_address(module_address, block.labels[0])))
    return _Configuration(tuple(resources), tuple(variables), tuple(locals_blocks))


def _scan_blocks(lines: list[str], path: Path, module_address: str) -> tuple[_Block, ...]:
    blocks: list[_Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kind: str | None = None
        labels: tuple[str, ...] = ()
        if match := _RESOURCE_HEADER.match(line):
            kind, labels = "resource", (match.group(1), match.group(2))
        elif match := _VARIABLE_HEADER.match(line):
            kind, labels = "variable", (match.group(1),)
        elif match := _MODULE_HEADER.match(line):
            kind, labels = "module", (match.group(1),)
        elif _LOCALS_HEADER.match(line):
            kind = "locals"
        if kind is None:
            index += 1
            continue
        # A block is used only when its structural closing brace is known. An
        # unclosed or unsupported construct becomes unavailable evidence.
        body, end = _capture_block(lines, index)
        if body is not None:
            blocks.append(_Block(kind, labels, path, index + 1, body, module_address, _top_level_attributes(body, index + 1)))
            index = end
        else:
            index += 1
    return tuple(blocks)


def _capture_block(lines: list[str], start: int) -> tuple[tuple[str, ...] | None, int]:
    depth = 0
    block_comment = False
    heredoc: str | None = None
    for index in range(start, len(lines)):
        delta, block_comment, heredoc = _brace_delta(lines[index], block_comment, heredoc)
        depth += delta
        if depth == 0:
            return tuple(lines[start : index + 1]), index + 1
    return None, start + 1


def _top_level_attributes(body: tuple[str, ...], start_line: int) -> tuple[_Attribute, ...]:
    attributes: list[_Attribute] = []
    depth = 0
    block_comment = False
    heredoc: str | None = None
    for index, line in enumerate(body):
        before_depth = depth
        delta, block_comment, heredoc = _brace_delta(line, block_comment, heredoc)
        # Attribute paths in plan metadata start at the resource body. Nested
        # maps/blocks need HCL evaluation, so they intentionally are not traced.
        if index and before_depth == 1 and (match := _ATTRIBUTE.match(_without_comment(line))):
            attributes.append(_Attribute(match.group(1), start_line + index, match.group(2)))
        depth += delta
    return tuple(attributes)


def _brace_delta(line: str, in_block_comment: bool, heredoc: str | None) -> tuple[int, bool, str | None]:
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
    match = _HEREDOC.search(_without_comment(line))
    return depth, in_block_comment, (match.group("quoted") or match.group("plain")) if match else None


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


def _attribute(block: _Block, name: str) -> _Attribute | None:
    return next((attribute for attribute in block.attributes if attribute.name == name), None)


def _named_block(blocks: tuple[_Block, ...], module_address: str, name: str) -> _Block | None:
    matches = tuple(block for block in blocks if block.module_address == module_address and block.labels == (name,))
    return matches[0] if len(matches) == 1 else None


def _local_block(configuration: _Configuration, module_address: str, name: str) -> _Block | None:
    matches = tuple(block for block in configuration.locals if block.module_address == module_address and _attribute(block, name) is not None)
    return matches[0] if len(matches) == 1 else None


def _resource_reference(resources: tuple[_Block, ...], module_address: str, reference: str) -> _Block | None:
    parts = reference.split(".")
    if len(parts) < 2:
        return None
    address = f"{module_address + '.' if module_address else ''}{parts[0]}.{parts[1]}"
    matches = tuple(block for block in resources if _resource_address(block) == address)
    return matches[0] if len(matches) == 1 else None


def _resource_address(block: _Block) -> str:
    prefix = f"{block.module_address}." if block.module_address else ""
    return prefix + ".".join(block.labels)


def _module_address(parent: str, label: str) -> str:
    return f"{parent}.module.{label}" if parent else f"module.{label}"


def _literal_source(expression: str) -> str | None:
    match = _LITERAL_STRING.fullmatch(expression.strip())
    return match.group("value") if match else None


def _location(path: Path, line: int) -> str:
    return f"{path.as_posix()}:{line}"


def _unindexed_address(address: str) -> str:
    # Both count and for_each instances share a single source declaration.
    return _INDEXED_ADDRESS.sub("", address)


def _has_index(address: str) -> bool:
    return _INDEXED_ADDRESS.search(address) is not None
