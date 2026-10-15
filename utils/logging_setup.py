"""Logging to logs/pos.log (rotating) and the console.

A filter removes anything that looks like a password before it is written.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd|secret|token)(['\"]?\s*[=:]\s*)(['\"]?)[^\s'\",;)]+"),
]


class RedactSecretsFilter(logging.Filter):
    """Masks password=..., pwd: ... etc. in every log record."""

    def __init__(self, extra_secrets: list[str] | None = None) -> None:
        super().__init__()
        self._literals = [s for s in (extra_secrets or []) if s and len(s) >= 3]

    def redact(self, text: str) -> str:
        for pat in _SECRET_PATTERNS:
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}***", text)
        for lit in self._literals:
            text = text.replace(lit, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = self.redact(message)
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


def setup_logging(log_dir: Path, level: str = "INFO", secrets: list[str] | None = None) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    redact = RedactSecretsFilter(secrets)

    file_handler = RotatingFileHandler(
        log_dir / "pos.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(redact)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redact)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(getattr(logging, level, logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(console)
    # mysql-connector can be chatty at DEBUG
    logging.getLogger("mysql.connector").setLevel(logging.WARNING)
