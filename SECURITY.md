# Security policy

## Supported versions

Security fixes go into the latest release. If you use the GitHub Action, pin to `@v1` to receive them automatically.

## Reporting a vulnerability

Please **don't open a public issue.** Report it privately through [GitHub's private vulnerability reporting](https://github.com/Nishchalpr4/alembic-head-fixer/security/advisories/new) instead.

You'll get a reply within a few days. Once a fix is released, the advisory is published and you're credited, unless you'd rather not be.

Things that are in scope here, as examples: the Action running untrusted input as shell, a way to make `fix` rewrite a migration that's in the applied ref, or path traversal when renaming files.
