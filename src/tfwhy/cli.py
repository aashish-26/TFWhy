"""Command-line interface for tfwhy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import PlanError, load_plan
from .fixes import FixError, apply_proposal, propose_fix, verify_plan
from .history import HistoryError, clear_history, default_history_path, list_history, save_history, show_history
from .replacement import analyze_replacements
from .renderers import render_json, render_markdown, render_terminal
from .renderers import render_review_json, render_review_markdown, render_review_terminal
from .renderers import render_fix_json, render_fix_markdown, render_fix_terminal, render_verification_json, render_verification_markdown, render_verification_terminal
from .renderers import render_history_json, render_history_markdown, render_history_terminal
from .standards import review_configuration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tfwhy", description="Explain a Terraform plan without exposing values.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    explain = subparsers.add_parser("explain", help="explain a Terraform plan JSON file")
    explain.add_argument("plan", type=Path)
    explain.add_argument("--dir", dest="config_dir", type=Path, help="Terraform configuration directory to inspect")
    explain.add_argument("--format", choices=("terminal", "markdown", "json"), default="terminal")
    explain.add_argument("--save-history", action="store_true", help="save sanitized plan metadata locally")
    explain.add_argument("--history-file", type=Path, help="override the local history JSON path")
    review = subparsers.add_parser("review", help="review Terraform configuration standards and security")
    review.add_argument("--dir", dest="config_dir", type=Path, default=Path.cwd(), help="Terraform directory to inspect (default: current directory)")
    review.add_argument("--format", choices=("terminal", "markdown", "json"), default="terminal")
    review.add_argument("--required-tag", dest="required_tags", action="append", help="required tag key; repeat for multiple tags")
    review.add_argument("--skip-rule", dest="skip_rules", action="append", default=[], help="skip a rule ID; repeat for multiple rules")
    fix = subparsers.add_parser("fix", help="propose a safe Terraform refactoring")
    fix.add_argument("--finding", required=True)
    fix.add_argument("--plan", type=Path, required=True, help="user-generated Terraform plan JSON")
    fix.add_argument("--dir", dest="config_dir", type=Path, required=True)
    fix.add_argument("--format", choices=("terminal", "markdown", "json"), default="terminal")
    fix.add_argument("--dry-run", action="store_true", help="show the proposal without writing files (default)")
    fix.add_argument("--apply", action="store_true", help="write the proposed moved.tf after explicit approval")
    fix.add_argument("--approve", action="store_true", help="explicitly approve --apply")
    verify = subparsers.add_parser("verify", help="verify an intended Terraform refactoring from a plan")
    verify.add_argument("--plan", type=Path, required=True)
    verify.add_argument("--from", dest="from_address", required=True)
    verify.add_argument("--to", dest="to_address", required=True)
    verify.add_argument("--kind", choices=("resource_rename", "count_to_for_each"), default="resource_rename")
    verify.add_argument("--format", choices=("terminal", "markdown", "json"), default="terminal")
    history = subparsers.add_parser("history", help="list saved sanitized plan metadata")
    history.add_argument("--format", choices=("terminal", "markdown", "json"), default="terminal")
    history.add_argument("--history-file", type=Path, default=None)
    history_subparsers = history.add_subparsers(dest="history_command")
    show = history_subparsers.add_parser("show", help="show one saved history entry")
    show.add_argument("id")
    show.add_argument("--format", choices=("terminal", "markdown", "json"), default="terminal")
    show.add_argument("--history-file", type=Path, default=None)
    clear = history_subparsers.add_parser("clear", help="delete saved history")
    clear.add_argument("--confirm", action="store_true", help="confirm deletion of local history")
    clear.add_argument("--history-file", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "explain":
        try:
            summary = load_plan(args.plan)
            summary = analyze_replacements(summary, args.config_dir)
            if args.save_history:
                save_history(summary, args.history_file)
        except (PlanError, HistoryError) as exc:
            print(f"tfwhy: error: {exc}", file=sys.stderr)
            return 2
        renderer = {"terminal": render_terminal, "markdown": render_markdown, "json": render_json}[args.format]
        print(renderer(summary), end="")
        return 0
    if args.command == "review":
        try:
            report = review_configuration(args.config_dir, args.required_tags, args.skip_rules)
        except PlanError as exc:
            print(f"tfwhy: error: {exc}", file=sys.stderr)
            return 2
        renderer = {"terminal": render_review_terminal, "markdown": render_review_markdown, "json": render_review_json}[args.format]
        print(renderer(report), end="")
        return 0
    if args.command == "fix":
        try:
            if args.apply and args.dry_run:
                raise FixError("--apply and --dry-run cannot be used together")
            if args.apply and not args.approve:
                raise FixError("--apply requires explicit --approve")
            summary = analyze_replacements(load_plan(args.plan), args.config_dir)
            proposal = propose_fix(summary, args.finding, args.config_dir)
            if args.apply:
                apply_proposal(proposal, args.config_dir)
        except (PlanError, FixError) as exc:
            print(f"tfwhy: error: {exc}", file=sys.stderr)
            return 2
        renderer = {"terminal": render_fix_terminal, "markdown": render_fix_markdown, "json": render_fix_json}[args.format]
        print(renderer(proposal), end="")
        return 0
    if args.command == "verify":
        try:
            result = verify_plan(load_plan(args.plan), args.from_address, args.to_address, args.kind)
        except (PlanError, FixError) as exc:
            print(f"tfwhy: error: {exc}", file=sys.stderr)
            return 2
        renderer = {"terminal": render_verification_terminal, "markdown": render_verification_markdown, "json": render_verification_json}[args.format]
        print(renderer(result), end="")
        return 0
    if args.command == "history":
        history_path = args.history_file or default_history_path()
        try:
            if args.history_command == "show":
                document = {"schema_version": 1, "entries": [show_history(args.id, args.history_file)]}
            elif args.history_command == "clear":
                clear_history(args.history_file, args.confirm)
                print("History cleared.")
                return 0
            else:
                document = list_history(args.history_file)
        except HistoryError as exc:
            print(f"tfwhy: error: {exc}", file=sys.stderr)
            return 2
        renderer = {"terminal": render_history_terminal, "markdown": render_history_markdown, "json": render_history_json}[args.format]
        print(renderer(document), end="")
        return 0
    return 2
