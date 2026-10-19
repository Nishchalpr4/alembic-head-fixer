## What and why

<!-- What does this change, and what problem does it solve? Link the issue if there is one. -->

## Checklist

- [ ] Tests added or updated (`fix` changes: a test that plays out the merge race in a throwaway repo, see `tests/conftest.py`)
- [ ] `python -m pytest` and `ruff check . && ruff format --check .` pass
- [ ] Nothing in the applied ref can be modified by this change
- [ ] `CHANGELOG.md` updated under "Unreleased", if users will notice
