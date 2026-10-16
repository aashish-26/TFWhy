"""Opt-in local history for sanitized Terraform plan metadata."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analyzer import PlanError, PlanSummary

HISTORY_SCHEMA_VERSION = 1


class HistoryError(ValueError):
    """History cannot be read or safely updated."""


def default_history_path() -> Path:
    configured = os.environ.get("TFWHY_HISTORY_FILE")
    return Path(configured) if configured else Path.home() / ".tfwhy" / "history.json"


def save_history(summary: PlanSummary, path: Path | None = None) -> dict[str, Any]:
    history_path = path or default_history_path()
    document = _read_document(history_path)
    entries = document["entries"]
    entry = _entry_from_summary(summary, _next_id(entries))
    entries.append(entry)
    _write_document(history_path, document)
    return _history_view(document)["entries"][-1]


def list_history(path: Path | None = None) -> dict[str, Any]:
    return _history_view(_read_document(path or default_history_path()))


def show_history(entry_id: str, path: Path | None = None) -> dict[str, Any]:
    document = _read_document(path or default_history_path())
    for entry in _history_view(document)["entries"]:
        if entry["id"] == entry_id:
            return entry
    raise HistoryError("history entry not found")


def clear_history(path: Path | None = None, confirmed: bool = False) -> None:
    if not confirmed:
        raise HistoryError("history clear requires explicit confirmation")
    history_path = path or default_history_path()
    try:
        history_path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise HistoryError("could not clear history") from exc


def _read_document(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema_version": HISTORY_SCHEMA_VERSION, "entries": []}
    except (OSError, UnicodeError) as exc:
        raise HistoryError("could not read history") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HistoryError("history file is corrupt") from exc
    if not isinstance(document, dict) or document.get("schema_version") != HISTORY_SCHEMA_VERSION or not isinstance(document.get("entries"), list):
        raise HistoryError("history file has an unsupported structure")
    if not all(_valid_entry(entry) for entry in document["entries"]):
        raise HistoryError("history file has invalid entries")
    return document


def _write_document(path: Path, document: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise HistoryError("could not write history") from exc


def _entry_from_summary(summary: PlanSummary, entry_id: str) -> dict[str, Any]:
    resources = []
    for resource in summary.resources:
        resources.append(
            {
                "address": resource.address,
                "resource_type": resource.resource_type,
                "action": resource.category,
                "replacement_paths": list(resource.replacement_paths),
                "action_reason": resource.action_reason,
            }
        )
    return {
        "id": entry_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "format_version": summary.format_version,
        "terraform_version": summary.terraform_version,
        "counts": summary.counts(),
        "resources": resources,
    }


def _history_view(document: dict[str, Any]) -> dict[str, Any]:
    entries = document["entries"]
    replacement_counts: dict[tuple[str, str, tuple[str, ...]], int] = {}
    for entry in entries:
        for resource in entry["resources"]:
            if resource["action"] == "replace":
                key = (resource["resource_type"], resource["address"], tuple(resource["replacement_paths"]))
                replacement_counts[key] = replacement_counts.get(key, 0) + 1
    viewed = []
    for entry in entries:
        copied = dict(entry)
        copied_resources = []
        for resource in entry["resources"]:
            copied_resource = dict(resource)
            if resource["action"] == "replace":
                key = (resource["resource_type"], resource["address"], tuple(resource["replacement_paths"]))
                copied_resource["recurrence_count"] = replacement_counts[key]
                copied_resource["recurrence_note"] = (
                    f"Observed in {replacement_counts[key]} saved runs; recurrence does not prove a root cause."
                    if replacement_counts[key] > 1
                    else "Observed once; recurrence does not prove a root cause."
                )
            copied_resources.append(copied_resource)
        copied["resources"] = copied_resources
        viewed.append(copied)
    return {"schema_version": document["schema_version"], "entries": viewed}


def _next_id(entries: list[dict[str, Any]]) -> str:
    numbers = [int(entry["id"]) for entry in entries if isinstance(entry.get("id"), str) and entry["id"].isdigit()]
    return str(max(numbers, default=0) + 1)


def _valid_entry(entry: Any) -> bool:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("resources"), list):
        return False
    return all(
        isinstance(resource, dict)
        and isinstance(resource.get("address"), str)
        and isinstance(resource.get("resource_type"), str)
        and isinstance(resource.get("action"), str)
        and isinstance(resource.get("replacement_paths"), list)
        and all(isinstance(path, str) for path in resource["replacement_paths"])
        for resource in entry["resources"]
    )