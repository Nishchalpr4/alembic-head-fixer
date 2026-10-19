"""`fix`: re-chain migrations that have not run yet onto a single head.

The one rule everything here serves: a migration your database has already
run is never touched. Alembic only walks forward from the revision stored in
`alembic_version`, so if an already-applied migration were re-pointed to sit
*after* a newcomer, the newcomer would land behind the database's position
and be skipped silently, forever. What has run is read from a git ref that
your deploy moves after every successful `alembic upgrade`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .graph import Migration, find_problems, heads, module_assignments

# All-digit ids up to this long are treated as sequence numbers (001, 042, 1203)
# and renumbered when moved. Longer all-digit strings are generated hashes.
SEQUENCE_ID_MAX_LENGTH = 6


class CannotFix(Exception):
    pass


@dataclass(frozen=True)
class Move:
    migration: Migration
    revision: str
    parents: tuple[str, ...]
    path: Path
    commit: str | None


def is_sequence_number(revision: str) -> bool:
    return revision.isdigit() and len(revision) <= SEQUENCE_ID_MAX_LENGTH


def split_by_applied(migrations: list[Migration], applied: list[Migration]) -> tuple[list[Migration], list[Migration]]:
    """(already run, not run yet), judged against the files present at the applied ref."""
    applied_pairs = {(m.name, m.revision) for m in applied}
    applied_ids = {m.revision for m in applied}
    still_named = {m.revision for m in migrations if (m.name, m.revision) in applied_pairs}

    def has_run(m: Migration) -> bool:
        if (m.name, m.revision) in applied_pairs:
            return True
        # Same id under a new filename: renamed after it ran -- unless another
        # file still carries that id under the applied name, which makes this
        # one a newcomer that happens to share the id.
        return m.revision in applied_ids and m.revision not in still_named

    done = [m for m in migrations if has_run(m)]
    pending = [m for m in migrations if not has_run(m)]
    return done, pending


def _renamed(path: Path, old: str, new: str) -> Path:
    if new == old:
        return path
    if path.name == f"{old}.py":
        return path.with_name(f"{new}.py")
    if path.name.startswith(f"{old}_"):
        return path.with_name(new + path.name[len(old) :])
    return path


def _next_free(revision: str, taken: set[str]) -> str:
    n = 2
    while f"{revision}_{n}" in taken:
        n += 1
    return f"{revision}_{n}"


def plan_fix(
    migrations: list[Migration],
    applied: list[Migration],
    landing: dict[str, tuple[int, str]],
) -> list[Move]:
    """The smallest set of rewrites that leaves one head without touching anything already run.

    Migrations that have not run are replayed onto the applied head in the
    order they landed on the branch. Each one that already attaches to the
    head with a unique id stays exactly as it is; the rest are re-pointed (and
    renumbered, for numeric ids) onto whatever is the head at that moment.
    """
    done, pending = split_by_applied(migrations, applied)
    if problems := find_problems(done):
        raise CannotFix(
            "the migrations that already ran do not form a single chain, so there is "
            "nothing safe to attach to: " + "; ".join(problems)
        )
    done_heads = heads(done)
    head = done_heads[0] if done_heads else None

    def commit_of(m: Migration) -> str | None:
        return landing[m.name][1] if m.name in landing else None

    def landed(m: Migration) -> tuple[float, str]:
        return (landing[m.name][0] if m.name in landing else math.inf, m.name)

    by_id: dict[str, list[Migration]] = {}
    for m in migrations:
        by_id.setdefault(m.revision, []).append(m)
    pending_set = set(pending)

    def resolve(child: Migration, parent_id: str) -> Migration:
        candidates = [c for c in by_id.get(parent_id, []) if c != child]
        if not candidates:
            raise CannotFix(f"{child.name}: down_revision {parent_id!r} does not exist")
        if len(candidates) == 1:
            return candidates[0]
        # A duplicated parent id: the one that landed with the child is the
        # one it was written against; otherwise the one that already ran.
        same_merge = [c for c in candidates if c in pending_set and commit_of(c) == commit_of(child)]
        ran = [c for c in candidates if c not in pending_set]
        return (same_merge or ran or sorted(candidates, key=landed))[0]

    parents_of = {m: tuple(resolve(m, p) for p in m.parents) for m in pending}

    # Landing order, but never a child before its own (pending) parent.
    remaining = sorted(pending, key=landed)
    ordered: list[Migration] = []
    placed: set[Migration] = set()
    while remaining:
        ready = next(
            (m for m in remaining if all(p in placed or p not in pending_set for p in parents_of[m])),
            None,
        )
        if ready is None:
            raise CannotFix(f"down_revision loop among {', '.join(m.name for m in remaining)}")
        ordered.append(ready)
        placed.add(ready)
        remaining.remove(ready)

    taken = {m.revision for m in done}
    last_number = max((int(r) for r in taken if is_sequence_number(r)), default=0)
    assigned: dict[Migration, str] = {}
    moves: list[Move] = []
    for m in ordered:
        current = tuple(assigned.get(p, p.revision) for p in parents_of[m])
        attach = (head,) if head else ()
        revision = m.revision
        if current == attach and revision not in taken:
            parents = current  # already in place; only rewritten if a parent was renumbered
        else:
            parents = attach
            if is_sequence_number(revision) and (revision in taken or int(revision) <= last_number):
                # Keep the zero-padding people use for `ls` order: 042 -> 043, not 43.
                revision = str(last_number + 1).zfill(len(revision))
            elif revision in taken:
                revision = _next_free(revision, taken)
        taken.add(revision)
        if is_sequence_number(revision):
            last_number = max(last_number, int(revision))
        assigned[m] = revision
        head = revision
        if revision != m.revision or parents != m.parents:
            moves.append(Move(m, revision, parents, _renamed(m.path, m.revision, revision), commit_of(m)))

    moved = {mv.migration for mv in moves}
    after = [m for m in migrations if m not in moved] + [Migration(mv.path, mv.revision, mv.parents) for mv in moves]
    if leftover := find_problems(after):
        raise CannotFix("re-chaining would still leave: " + "; ".join(leftover))
    paths = [m.path for m in after]
    if clashes := sorted({p.name for p in paths if paths.count(p) > 1}):
        raise CannotFix(f"renumbering would give two files the same name: {', '.join(clashes)}")
    return moves


def _literal(value: str, quote: str) -> str:
    return f"{quote}{value}{quote}"


def rewrite_source(source: bytes, filename: str, revision: str, parents: tuple[str, ...]) -> bytes:
    """`source` with its revision ids replaced, keeping its quoting, line endings and everything else."""
    values = module_assignments(source.decode("utf-8"), filename)
    lines = source.split(b"\n")
    edits = []
    quote = "'"
    for name in ("revision", "down_revision"):
        node = values.get(name)
        if node is None:
            raise CannotFix(f"{filename}: no top-level `{name} = ...` to rewrite")
        if node.lineno != node.end_lineno:
            raise CannotFix(f"{filename}: `{name}` spans several lines; put it on one line so it can be rewritten")
        if name == "revision" and lines[node.lineno - 1][node.col_offset : node.col_offset + 1] == b'"':
            quote = '"'
        edits.append((node.lineno - 1, node.col_offset, node.end_col_offset, name))

    new_values = {
        "revision": _literal(revision, quote),
        "down_revision": (
            "None"
            if not parents
            else _literal(parents[0], quote)
            if len(parents) == 1
            else "(" + ", ".join(_literal(p, quote) for p in parents) + ")"
        ),
    }
    # Right to left, so an edit never shifts the offsets of the next. ast
    # offsets are UTF-8 byte offsets, hence splicing bytes rather than str.
    for line_no, start, end, name in sorted(edits, reverse=True):
        line = lines[line_no]
        lines[line_no] = line[:start] + new_values[name].encode() + line[end:]
    updated = b"\n".join(lines)

    # The generated docstring repeats both ids; keep it truthful.
    updated = re.sub(rb"(?m)^(Revision ID:[ \t]*)[^\r\n]*", lambda m: m.group(1) + revision.encode(), updated, count=1)
    updated = re.sub(
        rb"(?m)^(Revises:[ \t]*)[^\r\n]*", lambda m: m.group(1) + ", ".join(parents).encode(), updated, count=1
    )
    return updated


def apply_moves(moves: list[Move]) -> None:
    """Write every move, or none: all rewrites are prepared before any file on disk changes."""
    staged: list[tuple[Path, Move]] = []
    try:
        for index, mv in enumerate(moves):
            updated = rewrite_source(mv.migration.path.read_bytes(), mv.migration.name, mv.revision, mv.parents)
            temp = mv.migration.path.with_name(f".alembic-head-fixer-{index}.tmp")
            temp.write_bytes(updated)
            staged.append((temp, mv))
    except BaseException:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)
        raise
    # Two phases: one move's new name can be the name another move is leaving.
    for _, mv in staged:
        mv.migration.path.unlink()
    for temp, mv in staged:
        temp.replace(mv.path)
