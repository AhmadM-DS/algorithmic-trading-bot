"""
settings.py
Load env variables once and check every required value at startup
"""

#Standard Library
from pathlib import Path
import os

#Third Party Libraries
from dotenv import load_dotenv

#Custom Exception when not all environment variables are loaded
class SettingsError(Exception):
    """Raised when there is missing or empty environment variable(s)"""

#File-only constants
REQUIRED_ENV_VARS = ["DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD",
            "DISCORD_CRITICAL_HOOK", "DISCORD_TRADES_HOOK", "DISCORD_ROUTINE_HOOK",
            "FMP_API_KEY"]

ALLOWED_EMPTY_ENV_VARS = ["DB_PASSWORD"]

ALLOWED_TRADING_MODES = ["paper", "live"]

def check_env_var(key_dict: dict, names: list=REQUIRED_ENV_VARS) -> dict:
    """Validate whether an environment variable is missing or empty
    
    Parameters:
        key_dict (dict): A dictionary of environment variables from os.environ
        names (list): A list of environment variable names
    
    Returns:
        A dictionary holding the missing or empty keys
    """
    result = {}
    empty = []
    missing = []
    for key in names:
        if key not in key_dict:
            missing.append(key)
        elif not key_dict[key].strip() and key not in ALLOWED_EMPTY_ENV_VARS:
            empty.append(key)
    result["Missing"] = missing
    result["Empty"] = empty
    return result

def load_env_vars(env_path=Path(__file__).parent.parent.parent / ".env") -> str:
    """Load environment variables once at startup

    Parameters:
        env_path(Path): The path of the .env file
    
    Returns:
        The trading_mode.upper() value as a string
    """
    load_dotenv(dotenv_path=env_path)
    trading_mode = os.environ.get("TRADING_MODE", "").strip().lower()
    if trading_mode not in ALLOWED_TRADING_MODES:
        raise SettingsError(f"Received {trading_mode!r} instead of one of two: {ALLOWED_TRADING_MODES}")
    suffix = trading_mode.upper()
    alpaca_keys_wmode = [f"ALPACA_API_KEY_{suffix}", f"ALPACA_SECRET_KEY_{suffix}"]
    result = check_env_var(os.environ, REQUIRED_ENV_VARS + alpaca_keys_wmode)
    if result["Missing"] or result["Empty"]:
        raise SettingsError(f"""Not all environment variables loaded. 
                         Missing: {result["Missing"]}. Empty: {result["Empty"]}""")
    return suffix
