# Changelog

## 0.1.0

First release.

- `check`: single head, duplicate ids, unknown parents, revision ids longer than `alembic_version` holds, and (`--base-ref`) migrations that start from a stale head or reuse an id taken on the base branch.
- `fix`: replays migrations that haven't run onto the applied head in merge order, renumbering numeric ids; never touches anything in the applied ref. `--dry-run` and a JSON `--report`.
- pre-commit hook (`id: alembic-head-fixer`) running `check`.
- GitHub Action with `check`, `fix` and `mark-applied`, including PR comments for moved migrations.
