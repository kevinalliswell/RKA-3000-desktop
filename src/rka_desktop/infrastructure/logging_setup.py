"""Rotating backend log in the user data directory; stdout stays free for the handshake."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "rka_desktop"


_BEARER = re.compile(r"Bearer\s+\S+")


class _RedactTokens(logging.Filter):
    """Never let bearer tokens reach the log, whatever a caller interpolates."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "Bearer" in message:
            record.msg = _BEARER.sub("Bearer [redacted]", message)
            record.args = ()
        return True


def setup_logging(log_file: Path, *, max_bytes: int = 5_000_000, backup_count: int = 3,
                  console: bool = True, level: int = logging.INFO) -> Path:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RedactTokens())
    root.addHandler(file_handler)
    if console:
        # Diagnostics go to stderr; stdout is reserved for the machine-readable handshake.
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(_RedactTokens())
        root.addHandler(stream)
    logging.getLogger(LOGGER_NAME).info("logging initialised: %s", log_file)
    return log_file


def tail_text(path: Path, max_bytes: int = 256 * 1024) -> str:
    if not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as stream:
        if size > max_bytes:
            stream.seek(size - max_bytes)
        data = stream.read()
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]
    return text
