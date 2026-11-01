"""Per-user data directory resolution. Nothing is written next to the executable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "RKA3000"
DATA_DIR_ENV = "RKA3000_DATA_DIR"


def default_data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_DIR_NAME.lower()


class AppPaths:
    """Well-known locations inside the user data directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_data_dir()).resolve()

    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    @property
    def database_file(self) -> Path:
        return self.root / "data" / "rka3000.db"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    @property
    def backend_log_file(self) -> Path:
        return self.log_dir / "backend.log"

    @property
    def export_dir(self) -> Path:
        return self.root / "exports"

    @property
    def backup_dir(self) -> Path:
        return self.root / "backups"

    def ensure(self) -> "AppPaths":
        for directory in (self.root, self.database_file.parent, self.log_dir, self.export_dir, self.backup_dir):
            directory.mkdir(parents=True, exist_ok=True)
        return self
