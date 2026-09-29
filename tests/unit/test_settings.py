import pytest
import os
from config.settings import check_env_var, load_env_vars, REQUIRED_ENV_VARS, SettingsError

@pytest.fixture(autouse=True)
def clean_env():
    """Restores our environment variables for testing"""
    saved = os.environ.copy()
    for name in REQUIRED_ENV_VARS:
        os.environ.pop(name, None)
    yield
    os.environ.clear()
    os.environ.update(saved)

def test_all_keys_present():
    """Tests for all environment variables present with values"""
    env_dict = {"ALPACA_API_KEY": "api_key", "ALPACA_SECRET_KEY": "secret_key", "ALPACA_BASE_URL": "url", 
            "DB_SERVER": "server", "DB_NAME": "name", "DB_USER": "user", "DB_PASSWORD": "pw",
            "DISCORD_CRITICAL_HOOK": "dch", "DISCORD_TRADES_HOOK": "dth", "DISCORD_ROUTINE_HOOK": "drh",
            "FMP_API_KEY": "fak"}
    result = check_env_var(env_dict)
    assert not any(result.values())

def test_some_keys_empty_rest_missing():
    """Tests for some empty environment variables with rest missing their values"""
    env_dict = {"ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": "", "ALPACA_BASE_URL": ""}
    result = check_env_var(env_dict)
    assert result["Empty"] == ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL"]
    assert result["Missing"] == ["DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD",
                                "DISCORD_CRITICAL_HOOK", "DISCORD_TRADES_HOOK",
                                "DISCORD_ROUTINE_HOOK", "FMP_API_KEY"]


def test_some_empty_some_missing_some_valid():
    """Tests for some empty environment variables with some missing their values and the rest loaded"""
    env_dict = {"ALPACA_API_KEY": "api", "ALPACA_SECRET_KEY": "", "ALPACA_BASE_URL": ""}
    result = check_env_var(env_dict)
    assert result["Empty"] == ["ALPACA_SECRET_KEY", "ALPACA_BASE_URL"]
    assert result["Missing"] == ["DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD",
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

def test_all_env_vars_presnt(tmp_path):
    """Tests if all environment variables load"""
    fake_env = tmp_path / ".env"
    fake_env.write_text("\n".join(item + "=a" for item in REQUIRED_ENV_VARS))
    load_env_vars(fake_env)