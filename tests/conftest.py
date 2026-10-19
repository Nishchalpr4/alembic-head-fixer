from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

TEMPLATE = '''"""{slug}

Revision ID: {revision}
Revises: {revises}
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = {revision_literal}
down_revision: Union[str, None] = {down_literal}
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("things", sa.Column("{slug}", sa.Text()))


def downgrade() -> None:
    op.drop_column("things", "{slug}")
'''


class Repo:
    """A throwaway git repo with an Alembic layout, for playing out merge races."""

    def __init__(self, root: Path):
        self.root = root
        self.versions = root / "alembic" / "versions"
        self.versions.mkdir(parents=True)
        (root / "alembic.ini").write_text("[alembic]\nscript_location = %(here)s/alembic\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout.strip()

    def migration(self, revision: str, down: str | None, slug: str, quote: str = "'", newline: str = "\n") -> Path:
        path = self.versions / f"{revision}_{slug}.py"
        source = TEMPLATE.format(
            slug=slug,
            revision=revision,
            revises=down or "",
            revision_literal=f"{quote}{revision}{quote}",
            down_literal=f"{quote}{down}{quote}" if down else "None",
        )
        path.write_bytes(source.replace("\n", newline).encode())
        return path

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def pr(self, branch: str, *migrations: tuple, base: str = "main") -> None:
        """Open a PR branch off `base` adding migrations (revision, down, slug)."""
        self.git("checkout", "-q", "-b", branch, base)
        for spec in migrations:
            self.migration(*spec)
        self.commit(f"{branch}: add migrations")
        self.git("checkout", "-q", base)

    def merge(self, branch: str) -> str:
        self.git("merge", "-q", "--no-ff", branch, "-m", f"Merge {branch}")
        return self.git("rev-parse", "HEAD")

    def mark_applied(self, ref: str = "HEAD") -> None:
        self.git("tag", "-f", "applied", ref)

    def files(self) -> list[str]:
        return sorted(p.name for p in self.versions.glob("*.py"))


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return Repo(tmp_path)
