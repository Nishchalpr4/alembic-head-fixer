"""Command line: `alembic-head-fixer check` and `alembic-head-fixer fix`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__, git
from .check import run_check
from .config import ConfigError, find_versions_dir
from .fix import CannotFix, apply_moves, plan_fix
from .graph import ALEMBIC_VERSION_NUM_LENGTH, describe, find_problems, heads, load_dir

EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE = 0, 1, 2


def _error(message: str) -> None:
    # GitHub Actions turns `::error::` lines into annotations on the run.
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") == "true" else "error: "
    sys.stdout.flush()  # keep errors after the output they follow when both go to one log
    print(prefix + message, file=sys.stderr)


def _cmd_check(args: argparse.Namespace, versions_dir: Path) -> int:
    migrations, problems = run_check(versions_dir, base_ref=args.base_ref, max_id_length=args.max_id_length)
    print(f"Checked {len(migrations)} migrations in {versions_dir}")
    if problems:
        for problem in problems:
            _error(problem)
        return EXIT_PROBLEMS
    found = heads(migrations)
    print(f"OK: single head {found[0]!r}." if found else "OK: no migrations yet.")
    return EXIT_OK


def _cmd_fix(args: argparse.Namespace, versions_dir: Path) -> int:
    migrations, unreadable = load_dir(versions_dir)
    if unreadable:
        for message in unreadable:
            _error(message)
        return EXIT_PROBLEMS
    problems = find_problems(migrations)
    if not problems:
        print(
            f"Single head {heads(migrations)[0]!r}; nothing to fix." if migrations else "No migrations; nothing to fix."
        )
        return EXIT_OK
    print("Migration history is not deployable:")
    for problem in problems:
        print(f"  - {problem}")

    repo = git.repo_root(versions_dir)
    rel_dir = versions_dir.relative_to(repo).as_posix()
    if not git.ref_exists(repo, args.applied_ref):
        _error(
            f"{args.applied_ref!r} does not exist, so there is no record of which migrations your "
            "database already ran, and nothing can be moved safely. Create it at the last commit "
            "you migrated (git tag <name> <sha> && git push origin <name>), or let a successful "
            "deploy create it."
        )
        return EXIT_PROBLEMS
    if git.is_shallow(repo):
        _error("this is a shallow clone; merge order needs full history (actions/checkout: fetch-depth: 0)")
        return EXIT_PROBLEMS

    try:
        moves = plan_fix(
            migrations, git.migrations_at(repo, args.applied_ref, rel_dir), git.landing_order(repo, rel_dir)
        )
    except CannotFix as exc:
        _error(f"cannot fix without touching a migration that already ran: {exc}")
        return EXIT_PROBLEMS

    print(
        f"{'Would re-chain' if args.dry_run else 'Re-chained'} onto the applied history ({args.applied_ref} untouched):"
    )
    for mv in moves:
        changes = []
        if mv.revision != mv.migration.revision:
            changes.append(f"revision {mv.migration.revision!r} -> {mv.revision!r}")
        if mv.parents != mv.migration.parents:
            changes.append(f"down_revision {describe(mv.migration.parents)} -> {describe(mv.parents)}")
        if mv.path != mv.migration.path:
            changes.append(f"renamed to {mv.path.name}")
        print(f"  {mv.migration.name}: {', '.join(changes)}")

    if args.dry_run:
        return EXIT_OK
    apply_moves(moves)
    if args.report:
        args.report.write_text(
            json.dumps(
                [
                    {
                        "commit": mv.commit,
                        "file": mv.migration.path.relative_to(repo).as_posix(),
                        "new_file": mv.path.relative_to(repo).as_posix(),
                        "revision": mv.migration.revision,
                        "new_revision": mv.revision,
                        "down_revision": list(mv.migration.parents),
                        "new_down_revision": list(mv.parents),
                    }
                    for mv in moves
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"Single head is now {moves[-1].revision!r}." if moves else "Nothing needed moving.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alembic-head-fixer",
        description=(
            "Catch parallel Alembic migrations before they break `alembic upgrade head`, and safely re-chain them."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c", "--config", type=Path, help="alembic.ini to read script_location from (default: ./alembic.ini)"
    )
    common.add_argument("--versions-dir", type=Path, help="revision files directory; overrides --config")

    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", parents=[common], help="fail if the history is not a single deployable head")
    check.add_argument(
        "--base-ref",
        help="branch this will merge into (e.g. origin/main): new migrations must grow from its current head",
    )
    check.add_argument(
        "--max-id-length",
        type=int,
        default=ALEMBIC_VERSION_NUM_LENGTH,
        help=f"longest allowed revision id (default {ALEMBIC_VERSION_NUM_LENGTH}, the alembic_version column size)",
    )

    fix = sub.add_parser("fix", parents=[common], help="re-chain migrations that have not run yet onto a single head")
    fix.add_argument(
        "--applied-ref",
        required=True,
        help="git ref of the last commit whose migrations ran on the database; nothing in it is ever moved",
    )
    fix.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    fix.add_argument("--report", type=Path, help="write a JSON list of what moved here (only when something moved)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        versions_dir = find_versions_dir(args.versions_dir, args.config)
    except ConfigError as exc:
        _error(str(exc))
        return EXIT_USAGE
    try:
        return _cmd_check(args, versions_dir) if args.command == "check" else _cmd_fix(args, versions_dir)
    except git.GitError as exc:
        _error(str(exc))
        return EXIT_USAGE
