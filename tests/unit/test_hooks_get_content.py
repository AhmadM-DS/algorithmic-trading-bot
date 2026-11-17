"""
test_hooks_get_content.py
Unit tests for the Claude Code hook that blocks PowerShell Get-Content round trips (they double-encode UTF-8)
"""

#Standard Library
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

#Third Party Libraries
import pytest

HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "block_get_content_roundtrip.py"

ROUND_TRIPS = ["(Get-Content f -Raw) -replace 'a','b' | Set-Content f",
               "$t = Get-Content f -Raw; [IO.File]::WriteAllText('f', $t)",
               "gc f | % { $_ -replace 'x','y' } | Out-File f",
               "Get-Content a.txt > b.txt",
               "cat notes.md >> all.md",
               "type f | Add-Content g",
               "gc f | sc f",
               "gc f | ac g",
               "Get-Content f | Tee-Object -FilePath f",
               "gc f | tee g"]

SAFE_COMMANDS = ["Get-Content src/main.py -TotalCount 20",
                 "Get-Content f | Select-String foo 2>$null",
                 "Get-Content f 2>&1 | Select-Object -First 5",
                 "$t = [IO.File]::ReadAllText('f'); [IO.File]::WriteAllText('f', $t)",
                 "Set-Content x.txt -Value 'abc'",
                 "git status",
                 "Get-ChildItem docs | Select-Object Name"]

def load_hook():
    """Import the hook script from .claude/hooks, which isn't on the import path"""
    spec = importlib.util.spec_from_file_location("block_get_content_roundtrip", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run_hook(payload: str) -> subprocess.CompletedProcess:
    """Run the hook the way Claude Code does: hook JSON on stdin, decision JSON on stdout"""
    return subprocess.run([sys.executable, str(HOOK_PATH)], input=payload, capture_output=True, text=True,
                          check=False)

@pytest.mark.parametrize("command", ROUND_TRIPS)
def test_round_trip_is_caught(command):
    """Flag a command that reads a file with Get-Content and writes a file in the same command"""
    assert load_hook().is_round_trip(command) is True

@pytest.mark.parametrize("command", SAFE_COMMANDS)
def test_safe_command_is_allowed(command):
    """Let reads alone, writes alone, stderr redirects and UTF-8-safe .NET calls through"""
    assert load_hook().is_round_trip(command) is False

def test_hook_denies_round_trip():
    """Print a deny decision with the safe alternatives for a round trip"""
    payload = json.dumps({"tool_name": "PowerShell", "tool_input": {"command": ROUND_TRIPS[0]}})

    result = run_hook(payload)

    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert result.returncode == 0
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "encoding='utf-8'" in output["permissionDecisionReason"]

def test_hook_stays_silent_on_safe_command():
    """Print nothing for a safe command, so the tool call goes ahead"""
    payload = json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "git status"}})

    result = run_hook(payload)

    assert result.returncode == 0
    assert result.stdout == ""

def test_hook_stays_silent_on_bad_input():
    """Print nothing for input that isn't hook JSON, so a broken payload never blocks PowerShell"""
    result = run_hook("not json")

    assert result.returncode == 0
    assert result.stdout == ""
