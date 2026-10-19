from pathlib import Path

import pytest

from alembic_head_fixer.config import ConfigError, find_versions_dir


def test_reads_script_location_with_here(tmp_path, monkeypatch):
    (tmp_path / "db" / "versions").mkdir(parents=True)
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = %(here)s/db\n")
    monkeypatch.chdir(tmp_path)
    assert find_versions_dir(None, None) == (tmp_path / "db" / "versions").resolve()


def test_relative_script_location_is_relative_to_the_ini(tmp_path, monkeypatch):
    (tmp_path / "svc" / "migrations" / "versions").mkdir(parents=True)
    (tmp_path / "svc" / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")
    monkeypatch.chdir(tmp_path)
    assert find_versions_dir(None, Path("svc/alembic.ini")) == (tmp_path / "svc" / "migrations" / "versions").resolve()


def test_flask_migrate_layout_without_ini(tmp_path, monkeypatch):
    (tmp_path / "migrations" / "versions").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert find_versions_dir(None, None) == (tmp_path / "migrations" / "versions").resolve()


def test_several_version_locations_need_an_explicit_choice(tmp_path, monkeypatch):
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = a\nversion_locations = a/v b/v\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="--versions-dir"):
        find_versions_dir(None, None)


def test_nothing_to_find(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError):
        find_versions_dir(None, None)
