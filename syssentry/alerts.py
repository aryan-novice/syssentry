"""Alert channels (console, file, webhook) with per-source cooldown."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime

from .rules import Event

ICONS = {"ok": "RESOLVED", "warning": "WARNING", "critical": "CRITICAL"}


def format_event(event: Event, hostname: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[{stamp}] [{ICONS[event.level]}] {hostname}: {event.message}"


class ConsoleChannel:
    def send(self, text: str, event: Event) -> None:
        print(text, file=sys.stderr if event.level == "critical" else sys.stdout, flush=True)


class FileChannel:
    def __init__(self, path: str):
        self.path = path

    def send(self, text: str, event: Event) -> None:
        with open(self.path, "a") as fh:
            fh.write(text + "\n")


class WebhookChannel:
    """Posts JSON to Slack, Discord, Teams (via workflow) or any HTTP receiver."""

    def __init__(self, url: str, timeout: float = 5):
        self.url, self.timeout = url, timeout

    def send(self, text: str, event: Event) -> None:
        payload = json.dumps({"text": text, "content": text, "level": event.level, "source": event.source}).encode()
        req = urllib.request.Request(self.url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=self.timeout).close()


def build_channels(specs: list[dict]) -> list:
    channels = []
    for spec in specs:
        kind = spec.get("type")
        if kind == "console":
            channels.append(ConsoleChannel())
        elif kind == "file":
            channels.append(FileChannel(spec["path"]))
        elif kind == "webhook":
            channels.append(WebhookChannel(spec["url"]))
        else:
            raise ValueError(f"unknown alert channel {kind!r}")
    return channels


class AlertManager:
    """Sends events to every channel, suppressing repeats of the same source+level inside the cooldown.

    Resolved events always go out, so on-call engineers know when to stand down.
    """

    def __init__(self, channels: list, hostname: str, cooldown_seconds: int = 300, clock=time.time):
        self.channels, self.hostname = channels, hostname
        self.cooldown, self.clock = cooldown_seconds, clock
        self.last_sent: dict[tuple[str, str], float] = {}
        self.suppressed = 0
        self.failures = 0

    def dispatch(self, event: Event) -> bool:
        key = (event.source, event.level)
        now = self.clock()
        if not event.resolved and now - self.last_sent.get(key, float("-inf")) < self.cooldown:
            self.suppressed += 1
            return False
        self.last_sent[key] = now
        text = format_event(event, self.hostname)
        for channel in self.channels:
            try:
                channel.send(text, event)
            except Exception as exc:  # one broken channel must not silence the others
                self.failures += 1
                print(f"[syssentry] alert channel {type(channel).__name__} failed: {exc}", file=sys.stderr)
        return True
