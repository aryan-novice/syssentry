"""Incremental log scanning: SSH brute-force detection and error-rate spikes.

Each file is read from the last byte offset seen, and rotation is detected
when the inode changes or the file shrinks, so a scan never re-reads old lines.
"""

from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .rules import Event

PATTERNS = {
    "ssh_failed": re.compile(r"Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})"),
    "ssh_invalid_user": re.compile(r"Invalid user (?P<user>\S+) from (?P<ip>\d{1,3}(?:\.\d{1,3}){3})"),
    "errors": re.compile(r"\b(error|critical|fatal|panic|segfault|out of memory)\b", re.IGNORECASE),
}


@dataclass
class LogWatch:
    path: str
    pattern: str = "ssh_failed"
    threshold: int = 5
    window_seconds: int = 300
    offset: int = 0
    inode: int | None = None
    hits: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    alerted: set[str] = field(default_factory=set)

    def read_new_lines(self) -> list[str]:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return []
        if self.inode is not None and (st.st_ino != self.inode or st.st_size < self.offset):
            self.offset = 0  # log was rotated or truncated
        self.inode = st.st_ino
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            data = fh.read()
        # Only consume complete lines; keep a partial last line for the next scan.
        end = data.rfind(b"\n") + 1
        self.offset += end
        return data[:end].decode("utf-8", "replace").splitlines()

    def scan(self, now: float | None = None) -> list[Event]:
        now = time.time() if now is None else now
        regex = PATTERNS[self.pattern]
        for line in self.read_new_lines():
            m = regex.search(line)
            if not m:
                continue
            key = m.groupdict().get("ip") or self.pattern
            self.hits[key].append(now)

        events = []
        for key, stamps in list(self.hits.items()):
            while stamps and now - stamps[0] > self.window_seconds:
                stamps.popleft()
            if not stamps:
                del self.hits[key]
                self.alerted.discard(key)
                continue
            if len(stamps) >= self.threshold and key not in self.alerted:
                self.alerted.add(key)
                source = f"log:{os.path.basename(self.path)}"
                events.append(Event("warning", source, self._message(key, len(stamps)), len(stamps)))
        return events

    def _message(self, key: str, count: int) -> str:
        mins = self.window_seconds // 60
        if self.pattern.startswith("ssh"):
            return f"possible SSH brute force from {key}: {count} failed logins in {mins} min"
        return f"{count} '{self.pattern}' lines in {self.path} within {mins} min"

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.hits.items()}
