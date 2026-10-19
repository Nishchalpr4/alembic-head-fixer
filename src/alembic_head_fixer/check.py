"""`check`: is this migration history deployable, and does this branch start at the right place?"""

from __future__ import annotations

from pathlib import Path

from . import git
from .graph import Migration, describe, find_problems, heads, load_dir


def stale_branch_problems(migrations: list[Migration], repo: Path, rel_dir: str, base_ref: str) -> list[str]:
    """New migrations on this branch must grow out of `base_ref`'s current head.

    Two PRs can each pass their own checks and still collide after both merge.
    Catching a branch point that went stale (someone else's migration merged
    first) while the PR is still open keeps the fix in the author's hands.
    A stack of several new migrations is fine, as long as it attaches at the head.
    """
    if not git.ref_exists(repo, base_ref):
        return [f"base ref {base_ref!r} not found; fetch it first (git fetch origin <branch>)"]
    base = git.migrations_at(repo, base_ref, rel_dir)
    if not base:
        return []
    base_heads = heads(base)
    if len(base_heads) != 1:
        return [f"{base_ref} itself has {len(base_heads)} heads ({', '.join(base_heads)}); fix that branch first"]
    (base_head,) = base_heads

    existing = {(m.name, m.revision) for m in base}
    base_files = {m.revision: m.name for m in base}
    new = {m.revision: m for m in migrations if (m.name, m.revision) not in existing}

    def reaches_base_head(revision: str, seen: set[str]) -> bool:
        if revision == base_head:
            return True
        if revision not in new or revision in seen:
            return False
        seen.add(revision)
        return any(reaches_base_head(p, seen) for p in new[revision].parents)

    problems = []
    for m in sorted(new.values(), key=lambda m: m.name):
        if m.revision in base_files:
            problems.append(
                f"{m.name}: revision id {m.revision!r} is already taken on {base_ref} by "
                f"{base_files[m.revision]}. Give it a new id and point it at {base_head!r}."
            )
        elif not any(reaches_base_head(p, set()) for p in m.parents):
            problems.append(
                f"{m.name}: down_revision is {describe(m.parents)}, but {base_ref}'s head is now "
                f"{base_head!r} (another migration merged first). Point the first new migration "
                f"on this branch at {base_head!r}."
            )
    return problems


def run_check(versions_dir: Path, *, base_ref: str | None, max_id_length: int) -> tuple[list[Migration], list[str]]:
    migrations, problems = load_dir(versions_dir)
    problems += find_problems(migrations, max_id_length)
    if base_ref and not problems:
        repo = git.repo_root(versions_dir)
        rel_dir = versions_dir.relative_to(repo).as_posix()
        problems += stale_branch_problems(migrations, repo, rel_dir, base_ref)
    return migrations, problems
