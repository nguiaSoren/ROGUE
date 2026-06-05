"""Tests for local credential/config storage (sandboxed to a tmp ROGUE_CONFIG_DIR)."""

from __future__ import annotations

from rogue.utils import config

# --- config_dir / paths ---------------------------------------------------------------------------


def test_config_dir_honors_env(tmp_path):
    # the autouse _sandbox fixture sets ROGUE_CONFIG_DIR to a tmp dir
    assert config.config_dir() == config.credentials_path().parent


def test_credentials_path_filename():
    assert config.credentials_path().name == "credentials.json"


# --- load on missing / corrupt --------------------------------------------------------------------


def test_load_credentials_missing_returns_empty():
    assert config.load_credentials() == {}


def test_load_api_key_missing_returns_none():
    assert config.load_api_key() is None


def test_load_base_url_missing_returns_none():
    assert config.load_base_url() is None


def test_load_credentials_corrupt_returns_empty():
    path = config.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    assert config.load_credentials() == {}


# --- round trip -----------------------------------------------------------------------------------


def test_save_and_load_api_key():
    config.save_api_key("sk-secret")
    assert config.load_api_key() == "sk-secret"


def test_save_api_key_returns_path():
    path = config.save_api_key("sk-secret")
    assert path == config.credentials_path()
    assert path.exists()


def test_save_with_base_url_round_trips():
    config.save_api_key("sk-secret", base_url="https://api.example.com")
    assert config.load_api_key() == "sk-secret"
    assert config.load_base_url() == "https://api.example.com"


def test_save_preserves_existing_base_url_when_omitted():
    config.save_api_key("k1", base_url="https://api.example.com")
    config.save_api_key("k2")  # no base_url -> keep prior
    assert config.load_api_key() == "k2"
    assert config.load_base_url() == "https://api.example.com"


def test_save_overwrites_api_key():
    config.save_api_key("k1")
    config.save_api_key("k2")
    assert config.load_api_key() == "k2"


# --- clear ----------------------------------------------------------------------------------------


def test_clear_credentials_returns_true_when_present():
    config.save_api_key("sk-secret")
    assert config.clear_credentials() is True
    assert config.load_api_key() is None


def test_clear_credentials_returns_false_when_absent():
    assert config.clear_credentials() is False


def test_clear_then_load_is_empty():
    config.save_api_key("sk-secret")
    config.clear_credentials()
    assert config.load_credentials() == {}


# --- file permissions (best effort) ---------------------------------------------------------------


def test_saved_file_is_readable_back():
    config.save_api_key("sk-secret", base_url="https://x")
    import json

    data = json.loads(config.credentials_path().read_text(encoding="utf-8"))
    assert data["api_key"] == "sk-secret"
    assert data["base_url"] == "https://x"
