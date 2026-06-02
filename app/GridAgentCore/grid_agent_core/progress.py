from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass


_OUTPUT_LOCK = threading.Lock()
_ACTIVE_LINE_LENGTH = 0


def log_event(message: str, *, enabled: bool = True, label: str | None = None) -> None:
    if not enabled:
        return
    prefix = time.strftime("%H:%M:%S")
    if label:
        line = f"[{prefix}] [{label}] {message}"
    else:
        line = f"[{prefix}] {message}"
    with _OUTPUT_LOCK:
        _clear_active_line()
        print(line, file=sys.stderr)


def _clear_active_line() -> None:
    global _ACTIVE_LINE_LENGTH
    if _ACTIVE_LINE_LENGTH and sys.stderr.isatty():
        sys.stderr.write("\r" + (" " * _ACTIVE_LINE_LENGTH) + "\r")
        _ACTIVE_LINE_LENGTH = 0


@dataclass
class ProgressBar:
    label: str
    total: int
    enabled: bool = True
    width: int = 28

    def __post_init__(self) -> None:
        self.current = 0
        self._last_line = ""
        self._interactive = self.enabled and sys.stderr.isatty()
        if self.enabled:
            self._render("starting")

    def advance(self, step: int = 1, *, detail: str = "") -> None:
        if not self.enabled:
            return
        self.current = min(self.total, self.current + step)
        self._render(detail)

    def close(self, *, detail: str = "done") -> None:
        if not self.enabled:
            return
        self.current = self.total
        self._render(detail)
        if self._interactive:
            with _OUTPUT_LOCK:
                sys.stderr.write("\n")
                sys.stderr.flush()
                _reset_active_line()

    def fail(self, *, detail: str = "failed") -> None:
        if not self.enabled:
            return
        self._render(detail)
        if self._interactive:
            with _OUTPUT_LOCK:
                sys.stderr.write("\n")
                sys.stderr.flush()
                _reset_active_line()

    def _render(self, detail: str) -> None:
        total = max(self.total, 1)
        ratio = min(1.0, self.current / total)
        filled = int(self.width * ratio)
        bar = "#" * filled + "-" * (self.width - filled)
        percent = int(ratio * 100)
        line = f"{self.label}: [{bar}] {self.current}/{self.total} {percent:3d}%"
        if detail:
            line = f"{line} {detail}"
        with _OUTPUT_LOCK:
            if self._interactive:
                global _ACTIVE_LINE_LENGTH
                padding = " " * max(0, len(self._last_line) - len(line))
                sys.stderr.write(f"\r{line}{padding}")
                sys.stderr.flush()
                self._last_line = line
                _ACTIVE_LINE_LENGTH = len(line)
            else:
                print(line, file=sys.stderr)


def _reset_active_line() -> None:
    global _ACTIVE_LINE_LENGTH
    _ACTIVE_LINE_LENGTH = 0
