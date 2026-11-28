"""
failed.py
Keep Discord messages that couldn't be posted in an append-only JSON-lines file until they're resent
"""

#Standard Library
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import threading
import uuid

#Local Imports
from errors import UNREADABLE_ERRORS
from logger import ChangeLog, health_log

@dataclass(frozen=True)
class FailedMessage:
    """One part that couldn't be posted: failed_at is UTC; message is the part as it was sent (already redacted)"""
    id: str
    failed_at: datetime
    kind: str
    asset: str | None
    message: str

class FailedLog:
    """One process's failed-message file

    Each failed part is one line {"id", "failed_at", "kind", "asset", "message"}. A resend appends {"sent": id};
    a part Discord refuses on its own gets {"dropped": id, "reason"}; nothing is ever rewritten. Pending = failed ids
    with no sent or dropped line, read from the file each time, so a restart
    loses nothing.
    """
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.bad_lines = ChangeLog(health_log)

    def _append(self, records: list):
        """Add records to the end of the file, one JSON line each"""
        with self.lock, self.path.open("a", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record) + "\n")

    def save(self, kind: str, asset: str | None, parts: list, failed_at: datetime):
        """Save parts that couldn't be posted, in order

        Parameters:
            kind (str): The kind they were routed as
            asset (str | None): Their asset, if any
            parts (list): The parts' text as they were sent
            failed_at (datetime): When posting failed (UTC)
        """
        self._append([{"id": uuid.uuid4().hex, "failed_at": failed_at.isoformat(), "kind": kind, "asset": asset,
                       "message": part} for part in parts])

    def mark_sent(self, message_id: str):
        """Record that one saved part has now been posted

        Parameters:
            message_id (str): The id from FailedMessage.id
        """
        self._append([{"sent": message_id}])

    def mark_dropped(self, message_id: str, reason: str):
        """Record that Discord refused one saved part on its own, so it isn't tried again

        Parameters:
            message_id (str): The id from FailedMessage.id
            reason (str): Discord's answer, e.g. "status 400"
        """
        self._append([{"dropped": message_id, "reason": reason}])

    def _read_line(self, number: int, line: str):
        """Return a FailedMessage, ("sent" or "dropped", id), or None for a line that can't be read (logged once)"""
        try:
            record = json.loads(line)
            for mark in ("sent", "dropped"):
                if mark in record:
                    return mark, str(record[mark])
            failed_at = datetime.fromisoformat(record["failed_at"])
            if failed_at.tzinfo is None:
                raise ValueError(f"failed_at {record['failed_at']!r} has no time zone")
            asset = record["asset"]
            if asset is not None and not isinstance(asset, str):
                raise TypeError(f"asset {asset!r} isn't text")
            return FailedMessage(id=str(record["id"]), failed_at=failed_at, kind=str(record["kind"]),
                                 asset=asset, message=str(record["message"]))
        except UNREADABLE_ERRORS as error:
            self.bad_lines.failed(number, f"Unreadable line {number} in {self.path.name} skipped: "
                                          f"{type(error).__name__}: {error}")
            return None

    def _read(self) -> tuple:
        """Return (every saved part in order, {"sent": ids, "dropped": ids})"""
        failed, marks = [], {"sent": set(), "dropped": set()}
        if not self.path.exists():
            return failed, marks
        with self.lock:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            item = self._read_line(number, line)
            if isinstance(item, FailedMessage):
                failed.append(item)
            elif item is not None:
                marks[item[0]].add(item[1])
        return failed, marks

    def pending(self) -> list:
        """Return every saved part not yet resent or dropped, in the order it was saved

        Returns:
            A list of FailedMessage; empty when there's no file
        """
        failed, marks = self._read()
        return [message for message in failed if message.id not in marks["sent"] | marks["dropped"]]

    def unsent(self) -> list:
        """Return every saved part that never went out, waiting or dropped, from one read of the file

        Returns:
            A list of FailedMessage
        """
        failed, marks = self._read()
        return [message for message in failed if message.id not in marks["sent"]]

    def dropped(self) -> list:
        """Return every saved part Discord refused on its own

        Returns:
            A list of FailedMessage
        """
        failed, marks = self._read()
        return [message for message in failed if message.id in marks["dropped"]]

    def rotate(self, day: date) -> Path | None:
        """Move the file aside as <name>.<day> (then -2, -3 ... if that exists) so the next day starts empty

        Parameters:
            day (date): The New York trading day the file covers

        Returns:
            The rotated file's path, or None when there was no file
        """
        with self.lock:
            if not self.path.exists():
                return None
            target = self.path.with_name(f"{self.path.name}.{day.isoformat()}")
            copy = 2
            while target.exists():
                target = self.path.with_name(f"{self.path.name}.{day.isoformat()}-{copy}")
                copy += 1
            self.path.rename(target)
            self.bad_lines.clear()
            return target
