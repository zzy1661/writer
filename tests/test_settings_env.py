from __future__ import annotations

import os
from pathlib import Path

from writer.config import get_settings, load_env_file, refresh_settings


def test_load_env_file_from_project_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("WRITER_API_KEY", raising=False)
    get_settings.cache_clear()

    (tmp_path / ".env").write_text("WRITER_API_KEY=from-project-env\n", encoding="utf-8")

    assert load_env_file(tmp_path) is True
    refresh_settings()

    assert get_settings().has_api_key is True
    assert get_settings().api_key is not None
    assert get_settings().api_key.get_secret_value() == "from-project-env"

    get_settings.cache_clear()


def test_load_env_file_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WRITER_API_KEY", "from-shell")
    get_settings.cache_clear()

    (tmp_path / ".env").write_text("WRITER_API_KEY=from-file\n", encoding="utf-8")

    load_env_file(tmp_path)
    refresh_settings()

    assert os.environ["WRITER_API_KEY"] == "from-shell"
    assert get_settings().api_key is not None
    assert get_settings().api_key.get_secret_value() == "from-shell"

    get_settings.cache_clear()


def test_load_writer_config_overrides_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WRITER_API_KEY", "from-shell")
    get_settings.cache_clear()

    writer_dir = tmp_path / ".writer"
    writer_dir.mkdir()
    (writer_dir / "config").write_text("WRITER_API_KEY=from-writer-config\n", encoding="utf-8")

    from writer.config.settings import load_writer_config

    load_writer_config(tmp_path)
    refresh_settings()

    assert get_settings().api_key is not None
    assert get_settings().api_key.get_secret_value() == "from-writer-config"

    get_settings.cache_clear()
