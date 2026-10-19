"""Work out where the revision files live."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

# Conventional layouts, tried when there is no alembic.ini to read:
# plain Alembic, and Flask-Migrate.
FALLBACK_DIRS = ("alembic/versions", "migrations/versions")


class ConfigError(Exception):
    pass


def _read_ini(ini: Path) -> Path:
    here = ini.parent.resolve()
    parser = configparser.ConfigParser(defaults={"here": str(here)})
    try:
        parser.read(ini, encoding="utf-8")
        locations = parser.get("alembic", "version_locations", fallback="")
        script_location = parser.get("alembic", "script_location", fallback="")
    except configparser.Error as exc:
        raise ConfigError(f"could not read {ini}: {exc}") from exc

    split = [p for p in re.split(r"[\s,]+", locations) if p]
    if len(split) > 1:
        raise ConfigError(f"{ini} lists {len(split)} version_locations; pass the one to check with --versions-dir")
    if split:
        return (here / split[0]).resolve()
    if not script_location:
        raise ConfigError(f"{ini} has no script_location under [alembic]")
    script_dir = (here / script_location).resolve()
    if not script_dir.is_dir() and ":" in script_location:
        raise ConfigError(f"script_location {script_location!r} looks like a package resource; pass --versions-dir")
    return script_dir / "versions"


def find_versions_dir(versions_dir: Path | None, config: Path | None) -> Path:
    if versions_dir is not None:
        found = versions_dir.resolve()
    elif config is not None:
        if not config.is_file():
            raise ConfigError(f"{config} does not exist")
        found = _read_ini(config)
    elif Path("alembic.ini").is_file():
        found = _read_ini(Path("alembic.ini"))
    else:
        candidates = [Path(d) for d in FALLBACK_DIRS if Path(d).is_dir()]
        if not candidates:
            raise ConfigError(
                "no alembic.ini here and no alembic/versions or migrations/versions; pass --config or --versions-dir"
            )
        found = candidates[0].resolve()
    if not found.is_dir():
        raise ConfigError(f"versions directory {found} does not exist")
    return found
