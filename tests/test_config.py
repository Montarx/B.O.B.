"""Configuration loading and layering."""

from __future__ import annotations

from pathlib import Path

import pytest

from bob.config.loader import deep_merge, env_overrides, load_persona, load_settings
from bob.config.schema import Settings
from bob.core.errors import ConfigError


def test_defaults_load_and_validate(settings: Settings) -> None:
    assert settings.app.language == "el"
    assert settings.llm.provider == "mock"
    assert settings.security.policy["high"] == "confirm"


def test_deep_merge_replaces_leaves_and_keeps_siblings() -> None:
    base = {"llm": {"model": "a", "temperature": 0.7}, "ui": {"theme": "dark"}}
    result = deep_merge(base, {"llm": {"model": "b"}})
    assert result == {
        "llm": {"model": "b", "temperature": 0.7},
        "ui": {"theme": "dark"},
    }
    assert base["llm"]["model"] == "a"  # original untouched


def test_env_overrides_build_nested_dicts() -> None:
    out = env_overrides({"BOB__LLM__MODEL": "llama3", "BOB__UI__ANIMATION_FPS": "30"})
    assert out == {"llm": {"model": "llama3"}, "ui": {"animation_fps": 30}}


def test_env_overrides_ignore_unrelated_variables() -> None:
    assert env_overrides({"PATH": "/usr/bin", "BOBBY": "x"}) == {}


def test_env_override_reaches_settings(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOB__LOGGING__LEVEL", "DEBUG")
    monkeypatch.setenv("BOB__UI__REDUCED_MOTION", "true")
    settings = load_settings()
    assert settings.logging.level == "DEBUG"
    assert settings.ui.reduced_motion is True


def test_user_toml_overrides_default_toml(clean_env: None, tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text('[llm]\nmodel = "base"\ntemperature = 0.5\n')
    (tmp_path / "user.toml").write_text('[llm]\nmodel = "personal"\n')
    settings = load_settings(config_dir=tmp_path)
    assert settings.llm.model == "personal"
    assert settings.llm.temperature == 0.5  # untouched by the user file


def test_explicit_overrides_win(clean_env: None) -> None:
    settings = load_settings(overrides={"llm": {"model": "override"}})
    assert settings.llm.model == "override"


def test_unknown_section_is_rejected(clean_env: None, tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text("[nonsense]\nfoo = 1\n")
    with pytest.raises(ConfigError):
        load_settings(config_dir=tmp_path)


def test_secrets_in_toml_are_refused(clean_env: None, tmp_path: Path) -> None:
    """Keys must never be committable, so TOML is not allowed to carry them."""
    (tmp_path / "default.toml").write_text('[secrets]\nopenai_api_key = "sk-oops"\n')
    with pytest.raises(ConfigError, match="secrets"):
        load_settings(config_dir=tmp_path)


def test_high_risk_cannot_be_auto_allowed(clean_env: None, tmp_path: Path) -> None:
    """The safety floor is enforced by the schema, not only by the broker."""
    (tmp_path / "default.toml").write_text(
        '[security.policy]\nlow = "allow"\nmedium = "allow"\nhigh = "allow"\n'
    )
    with pytest.raises(ConfigError, match="high"):
        load_settings(config_dir=tmp_path)


def test_persona_is_loaded_from_file_not_code() -> None:
    text = load_persona("bob")
    assert "B.O.B." in text
    assert "Greek" in text or "Ελλην" in text


def test_missing_persona_raises() -> None:
    with pytest.raises(ConfigError):
        load_persona("does-not-exist")
