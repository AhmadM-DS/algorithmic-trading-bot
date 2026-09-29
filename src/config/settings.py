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
REQUIRED_ENV_VARS = ["ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL", 
            "DB_SERVER", "DB_NAME", "DB_USER", "DB_PASSWORD",
            "DISCORD_CRITICAL_HOOK", "DISCORD_TRADES_HOOK", "DISCORD_ROUTINE_HOOK",
            "FMP_API_KEY"]

ALLOWED_EMPTY_ENV_VARS = ["DB_PASSWORD"]

def check_env_var(key_dict: dict) -> dict:
    """Validate whether an environment variable is missing or empty
    
    Parameters:
        key_dict (dict): A dictionary of environment variables from os.environ
    """
    result = {}
    empty = []
    missing = []
    for key in REQUIRED_ENV_VARS:
        if key not in key_dict:
            missing.append(key)
        elif not key_dict[key].strip() and key not in ALLOWED_EMPTY_ENV_VARS:
            empty.append(key)
    result["Missing"] = missing
    result["Empty"] = empty
    return result

def load_env_vars(env_path=Path(__file__).parent.parent.parent / ".env"):
    """Load environment variables once at startup

    Parameters:
        env_path(Path): The path of the .env file
    """
    load_dotenv(dotenv_path=env_path)
    result = check_env_var(os.environ)
    if result["Missing"] or result["Empty"]:
        raise SettingsError(f"""ERROR! Not all environment variables loaded. 
                         Missing: {result["Missing"]}. Empty: {result["Empty"]}""")
