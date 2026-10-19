"""The few git questions the fixer needs answered."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from .graph import Migration, MigrationParseError, is_migration_file, parse_migration


class GitError(Exception):
    pass


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def repo_root(start: Path) -> Path:
    return Path(git(start, "rev-parse", "--show-toplevel").strip()).resolve()


def ref_exists(repo: Path, ref: str) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except GitError:
        return False
    return True


def is_shallow(repo: Path) -> bool:
    return git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def migrations_at(repo: Path, ref: str, rel_dir: str) -> list[Migration]:
    """The revision files in `rel_dir` as they are at `ref`. Paths come back repo-relative."""
    try:
        listing = git(repo, "ls-tree", "--name-only", f"{ref}:{rel_dir}")
    except GitError:
        return []  # the directory did not exist yet at that ref
    names = [n for n in listing.splitlines() if is_migration_file(n)]
    if not names:
        return []

    # One `cat-file --batch` instead of a `git show` per file: histories run to hundreds of revisions.
    request = "".join(f"{ref}:{rel_dir}/{name}\n" for name in names).encode()
    output = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=repo, input=request, capture_output=True, check=True
    ).stdout

    migrations = []
    offset = 0
    for name in names:
        header_end = output.index(b"\n", offset)
        size = int(output[offset:header_end].split()[2])
        body = output[header_end + 1 : header_end + 1 + size]
        offset = header_end + 1 + size + 1
        path = Path(PurePosixPath(rel_dir, name))
        try:
            migrations.append(parse_migration(body.decode("utf-8"), path))
        except MigrationParseError:
            continue  # an old unreadable file is the check's business, not history's
    return migrations


def landing_order(repo: Path, rel_dir: str) -> dict[str, tuple[int, str]]:
    """filename -> (position, commit) of the commit that last added it to this branch.

    Follows first parents only, so everything a merged PR added counts as
    landing when the PR *merged*, not when its commits were written. A higher
    position landed later.
    """
    log = git(
        repo,
        "log",
        "--first-parent",
        "--reverse",
        "--diff-merges=first-parent",
        "--no-renames",
        "--diff-filter=A",
        "--format=@%H",
        "--name-only",
        "--",
        rel_dir,
    )
    order: dict[str, tuple[int, str]] = {}
    position, commit = -1, ""
    for line in log.splitlines():
        if line.startswith("@"):
            position, commit = position + 1, line[1:]
        elif line.strip():
            order[PurePosixPath(line).name] = (position, commit)
    return order
