"""
discord.py
Split a message to fit Discord and post one part, waiting once on a short rate limit
"""

#Standard Library
from dataclasses import dataclass
import math

#Third Party Libraries
import requests

#Local Imports
from errors import UNREADABLE_ERRORS

@dataclass(frozen=True)
class PostFailure:
    """Why a post failed: Discord's status (None for a network error or timeout) and a detail for the log"""
    status: int | None
    detail: str

    @property
    def outage(self) -> bool:
        """True when Discord is down or unusable (network error, 401 bad token, 429, 5xx), which should stop a batch;
        False when only this message was refused (another 4xx)"""
        return self.status is None or self.status in (401, 429) or self.status >= 500

    def __str__(self) -> str:
        return self.detail if self.status is None else f"status {self.status}{self.detail}"

def split_message(text: str, limit: int) -> list:
    """Return the message in parts of at most limit characters, split between lines where possible

    A single line longer than limit is cut. Joining the parts with newlines gives back the message.

    Parameters:
        text (str): The whole message
        limit (int): The most characters one part may hold (Discord: 2000)

    Returns:
        The parts in order; an empty list for an empty message
    """
    if not text:
        return []
    parts, current = [], None
    for line in text.split("\n"):
        while len(line) > limit:
            if current is not None:
                parts.append(current)
                current = None
            parts.append(line[:limit])
            line = line[limit:]
        if current is None:
            current = line
        elif len(current) + 1 + len(line) <= limit:
            current = f"{current}\n{line}"
        else:
            parts.append(current)
            current = line
    if current is not None:
        parts.append(current)
    return parts

def _retry_after(response) -> float | None:
    """Return the seconds a 429 asks to wait, or None when it can't be read"""
    try:
        seconds = float(response.json()["retry_after"])
    except UNREADABLE_ERRORS:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None

def post_message(http_post, url: str, content: str, *, headers: dict | None, timeout: float,
                 max_retry_seconds: float, sleep) -> PostFailure | None:
    """Post one part to a Discord channel or webhook

    On a 429 it waits Discord's retry_after and tries once more, but only when the wait is at most
    max_retry_seconds, so a long rate limit never stalls the caller. Only user mentions ping (never @everyone).

    Parameters:
        http_post: requests.post or a fake with the same arguments
        url (str): The channel's messages URL or a webhook URL
        content (str): One part, already redacted and within Discord's limit
        headers (dict | None): The bot's Authorization header; None for a webhook
        timeout (float): Seconds to wait for Discord's answer
        max_retry_seconds (float): The longest retry_after worth waiting for
        sleep: time.sleep or a fake

    Returns:
        None when posted, otherwise a PostFailure
    """
    payload = {"content": content, "allowed_mentions": {"parse": ["users"]}}
    for attempt in range(2):
        try:
            response = http_post(url, json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as error:
            return PostFailure(None, f"{type(error).__name__}: {error}")
        if response.ok:
            return None
        if response.status_code != 429:
            return PostFailure(response.status_code, "")
        wait = _retry_after(response)
        if attempt == 1 or wait is None or wait > max_retry_seconds:
            return PostFailure(429, f", retry_after {wait}")
        sleep(wait)
    return PostFailure(429, "")
