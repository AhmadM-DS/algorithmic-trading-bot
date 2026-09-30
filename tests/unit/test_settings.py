import pytest
import os
from config.settings import check_env_var, load_env_vars, REQUIRED_ENV_VARS, SettingsError

@pytest.fixture(autouse=True)
def clean_env():
    """Restores our environment variables for testing"""
    saved = os.environ.copy()
    for name in REQUIRED_ENV_VARS:
        os.environ.pop(name, None)
    os.environ.pop("TRADING_MODE", None)
    for mode in ["PAPER", "LIVE"]:
        for key in ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL"]:
            os.environ.pop(f"{key}_{mode}", None)
    yield
    os.environ.clear()
    os.environ.update(saved)

def write_env(path, extra):
    fake_env = path / ".env"
    values = {key: "a" for key in REQUIRED_ENV_VARS}
    values.update(extra)
    fake_env.write_text("\n".join(key + "=" + value for key, value in values.items()))
    return fake_env

def test_all_keys_present():
    """Tests for all environment variables present with values"""
    env_dict = {"DB_SERVER": "server", "DB_NAME": "name", "DB_USER": "user", "DB_PASSWORD": "pw",
            "DISCORD_CRITICAL_HOOK": "dch", "DISCORD_TRADES_HOOK": "dth", "DISCORD_ROUTINE_HOOK": "drh",
            "FMP_API_KEY": "fak"}
    result = check_env_var(env_dict)
    assert not any(result.values())

def test_some_keys_empty_rest_missing():
    """Tests for some empty environment variables with rest missing their values"""
    env_dict = {"DB_SERVER": ""}
    result = check_env_var(env_dict)
    assert result["Empty"] == ["DB_SERVER"]
    assert result["Missing"] == ["DB_NAME", "DB_USER", "DB_PASSWORD",
                                "DISCORD_CRITICAL_HOOK", "DISCORD_TRADES_HOOK",
                                "DISCORD_ROUTINE_HOOK", "FMP_API_KEY"]


def test_some_empty_some_missing_some_valid():
    """Tests for some empty environment variables with some missing their values and the rest loaded"""
    env_dict = {"DB_SERVER": "server", "DB_NAME": "", "DB_USER": ""}
    result = check_env_var(env_dict)
    assert result["Empty"] == ["DB_NAME", "DB_USER"]
    assert result["Missing"] == ["DB_PASSWORD",
            "DISCORD_CRITICAL_HOOK", "DISCORD_TRADES_HOOK", "DISCORD_ROUTINE_HOOK",
            "FMP_API_KEY"]

def test_all_keys_missing():
    """Tests if all environment variables are not present"""
    env_dict = {}
    result = check_env_var(env_dict)
    assert result["Empty"] == []
    assert result["Missing"] == REQUIRED_ENV_VARS

def test_allowed_empty_env_vars():
    """Tests for environment variables that are allowed to be blank"""
    env_dict = {"DB_PASSWORD": "", "DB_USER": " "}
    result = check_env_var(env_dict)
    assert "DB_USER" in result["Empty"]
    assert "DB_PASSWORD" not in result["Empty"] and "DB_PASSWORD" not in result["Missing"]

#-----------------------

def test_delete_env_var(tmp_path):
    """Tests if SettingsError is raised when an environment variable is deleted"""
    fake_env = tmp_path / ".env"
    fake_env.write_text("DB_USER=\n")
    with pytest.raises(SettingsError):
        load_env_vars(fake_env)

def test_all_env_vars_present(tmp_path):
    """Tests if all environment variables load"""
    fake_env = write_env(tmp_path, {"TRADING_MODE": "Paper", "ALPACA_API_KEY_PAPER": "a", "ALPACA_SECRET_KEY_PAPER": "a", "ALPACA_BASE_URL_PAPER": "a"})
    load_env_vars(fake_env)

#-----------------------

def test_missing_trading_mode(tmp_path):
    """Tests if trading mode env var is missing"""
    fake_env = write_env(tmp_path, {})
    with pytest.raises(SettingsError):
        load_env_vars(fake_env)

def test_trading_mode_misspelled(tmp_path):
    """Tests if trading mode env var is misspelled"""
    fake_env = write_env(tmp_path, {"TRADING_MODE": "Lvie "})
    with pytest.raises(SettingsError):
        load_env_vars(fake_env)

def test_spaces_between_mode(tmp_path):
    """Tests when trading mode is in between spaces"""
    fake_env = write_env(tmp_path, {"TRADING_MODE": " Live ", "ALPACA_API_KEY_LIVE": "a", "ALPACA_SECRET_KEY_LIVE": "a", "ALPACA_BASE_URL_LIVE": "a"})
    load_env_vars(fake_env)

def test_paper_mode_live_keys(tmp_path):
    """Tests when trading mode is paper but using live keys"""
    fake_env = write_env(tmp_path, {"TRADING_MODE": "Paper", "ALPACA_API_KEY_LIVE": "a", "ALPACA_SECRET_KEY_LIVE": "a", "ALPACA_BASE_URL_LIVE": "a"})
    with pytest.raises(SettingsError):
        load_env_vars(fake_env)

def test_live_mode_paper_keys(tmp_path):
    """Tests when trading mode is live but using paper keys"""
    fake_env = write_env(tmp_path, {"TRADING_MODE": "Live", "ALPACA_API_KEY_PAPER": "a", "ALPACA_SECRET_KEY_PAPER": "a", "ALPACA_BASE_URL_PAPER": "a"})
    with pytest.raises(SettingsError):
        load_env_vars(fake_env)