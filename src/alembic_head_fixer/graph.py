"""Read Alembic revision files without importing them, and reason about the graph.

Revision files are parsed with `ast`, never executed: checking a migration
history should not need your app's settings, a database, or its imports.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Alembic creates alembic_version.version_num as VARCHAR(32). A longer revision
# id makes the version bump fail *after* the migration's DDL ran, and the
# rollback that follows makes it look like the migration itself was broken.
ALEMBIC_VERSION_NUM_LENGTH = 32


class MigrationParseError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    path: Path
    revision: str
    parents: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.path.name


def is_migration_file(name: str) -> bool:
    return name.endswith(".py") and name != "__init__.py"


def module_assignments(source: str, filename: str) -> dict[str, ast.expr]:
    """Top-level `name = value` and `name: T = value` assignments of a module."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise MigrationParseError(f"{filename}: {exc.msg} (line {exc.lineno})") from exc
    found: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            found[node.target.id] = node.value
    return found


def _literal(node: ast.expr | None, filename: str):
    if node is None:
        return None
    if isinstance(node, ast.Constant) and (node.value is None or isinstance(node.value, str)):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(_literal(element, filename) for element in node.elts)
    raise MigrationParseError(f"{filename}: revision ids must be plain string literals")


def parse_migration(source: str, path: Path) -> Migration:
    values = module_assignments(source, path.name)
    revision = _literal(values.get("revision"), path.name)
    if not isinstance(revision, str) or not revision:
        raise MigrationParseError(f'{path.name}: no `revision = "..."` found')
    down = _literal(values.get("down_revision"), path.name)
    if down is None:
        parents: tuple[str, ...] = ()
    elif isinstance(down, tuple):
        parents = tuple(p for p in down if p)
    else:
        parents = (down,)
    return Migration(path, revision, parents)


def load_dir(versions_dir: Path) -> tuple[list[Migration], list[str]]:
    """Every revision file in `versions_dir`, plus a message per file that could not be read."""
    migrations: list[Migration] = []
    errors: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        if not is_migration_file(path.name):
            continue
        try:
            migrations.append(parse_migration(path.read_text(encoding="utf-8"), path))
        except MigrationParseError as exc:
            errors.append(str(exc))
    return migrations, errors


def heads(migrations: Iterable[Migration]) -> list[str]:
    migrations = list(migrations)
    referenced = {p for m in migrations for p in m.parents}
    return sorted({m.revision for m in migrations} - referenced)


def describe(parents: tuple[str, ...]) -> str:
    if not parents:
        return "None"
    if len(parents) == 1:
        return repr(parents[0])
    return "(" + ", ".join(repr(p) for p in parents) + ")"


def find_problems(migrations: list[Migration], max_id_length: int | None = None) -> list[str]:
    """Everything that would make `alembic upgrade head` refuse this graph. Empty means deployable."""
    problems: list[str] = []
    by_id: dict[str, Migration] = {}
    for m in migrations:
        if max_id_length is not None and len(m.revision) > max_id_length:
            problems.append(
                f"{m.name}: revision id {m.revision!r} is {len(m.revision)} characters; "
                f"alembic_version.version_num only holds {max_id_length}"
            )
        if m.revision in by_id:
            problems.append(f"duplicate revision id {m.revision!r} in {by_id[m.revision].name} and {m.name}")
        else:
            by_id[m.revision] = m

    unknown = sorted({p for m in migrations for p in m.parents} - by_id.keys())
    if unknown:
        problems.append(f"down_revision points at revision(s) that do not exist: {', '.join(unknown)}")

    found = heads(migrations)
    if migrations and not found:
        problems.append("no head at all: the down_revision chain loops back on itself")
    elif len(found) > 1:
        children: dict[str, list[str]] = {}
        for m in migrations:
            for p in m.parents:
                children.setdefault(p, []).append(m.name)
        forks = [f"{parent} -> {', '.join(sorted(kids))}" for parent, kids in sorted(children.items()) if len(kids) > 1]
        detail = f" (forks: {'; '.join(forks)})" if forks else ""
        problems.append(f"{len(found)} heads: {', '.join(found)}{detail}")
    return problems
