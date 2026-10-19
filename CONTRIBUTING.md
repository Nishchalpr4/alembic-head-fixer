# Contributing

Thanks for helping! Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). For questions, use [Discussions](https://github.com/Nishchalpr4/alembic-head-fixer/discussions). Bug reports with a reproducible history are the most useful thing you can send.

## Reporting a bug

Please include:

- the output of `alembic-head-fixer --version`, and the full command and output;
- the shape of your history: `git log --first-parent --oneline -- <versions dir>` around the problem, and the `revision` / `down_revision` of the files involved;
- what you expected to happen.

## Development

```bash
git clone https://github.com/Nishchalpr4/alembic-head-fixer
cd alembic-head-fixer
python -m pip install -e ".[dev]"
python -m pytest
ruff check . && ruff format --check .
```

The tests build real throwaway git repos and play out merge races in them (`tests/conftest.py`, `Repo.pr` / `Repo.merge`). A new behaviour of `fix` should come with a test written that way.

## Ground rules

- **Never move what already ran.** Any change to `fix` must keep every file at the applied ref byte-for-byte unchanged. When in doubt, refuse and exit `1`.
- **No runtime dependencies.** Standard library only, Python 3.10+.
- **Never import migration files.** Read them with `ast`.
