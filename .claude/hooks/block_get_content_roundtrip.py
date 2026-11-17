"""
block_get_content_roundtrip.py
Claude Code PreToolUse hook: deny PowerShell commands that read a file with Get-Content and write a file in the
same command, since Windows PowerShell 5.1 reads UTF-8 without a BOM as ANSI and the write double-encodes it
"""

#Standard Library
import json
import re
import sys

READER = re.compile(r"(?<![\w$-])(Get-Content|gc|cat|type)(?![\w-])", re.IGNORECASE)
WRITER = re.compile(r"(?<![\w$-])(Set-Content|sc|Add-Content|ac|Out-File|Tee-Object|tee|WriteAllText|WriteAllLines)"
                    r"(?![\w-])", re.IGNORECASE)
REDIRECT = re.compile(r"(?:^|[^\d>])\*?>{1,2}(?!&)\s*(?!\$null\b)", re.IGNORECASE)

DENY_REASON = ("Blocked: a Get-Content read plus a file write in one PowerShell command double-encodes UTF-8 here "
               "(Windows PowerShell 5.1). Use the Edit/Write tools, Python with encoding='utf-8', or "
               "[IO.File]::ReadAllText / WriteAllText.")

def is_round_trip(command: str) -> bool:
    """Check whether a PowerShell command reads with Get-Content and writes a file

    Parameters:
        command (str): The PowerShell command Claude is about to run

    Returns:
        True when the command has a Get-Content read and a file write (cmdlet, .NET write or > / >> redirect);
        a 2>, 2>&1 or > $null redirect isn't a file write
    """
    return bool(READER.search(command)) and bool(WRITER.search(command) or REDIRECT.search(command))

def main():
    """Read the hook input from stdin and print a deny decision when the command is a round trip"""
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and is_round_trip(command):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": DENY_REASON}}))

if __name__ == "__main__":
    main()
