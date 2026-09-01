from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from hashlib import sha256
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from wait_local_agent import fs_permissions
from wait_local_agent.config import Settings
from wait_local_agent.diagnostics import scrub_text, valid_correlation_id

LOG_FILE_NAME = "wait-local-agent.jsonl"


class PrivateRotatingFileHandler(RotatingFileHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._restricting = False

    def doRollover(self) -> None:
        if self._restricting:
            return
        self._restricting = True
        try:
            super().doRollover()
            self._restrict(Path(self.baseFilename))
            for index in range(1, self.backupCount + 1):
                backup = Path(f"{self.baseFilename}.{index}")
                if backup.exists():
                    self._restrict(backup)
        finally:
            self._restricting = False

    @staticmethod
    def _restrict(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


class ScrubbedJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": scrub_text(record.name),
            "message": scrub_text(record.getMessage()),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if valid_correlation_id(correlation_id):
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exception"] = scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def configured_log_directory(settings: Settings) -> Path:
    if settings.log_dir is None:
        if settings.data_path.is_absolute():
            return settings.data_path.parent / "logs"
        configured_root = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_STATE_HOME")
        state_root = Path(configured_root) if configured_root else _platform_state_root()
        data_identity = sha256(str(settings.data_path).encode("utf-8")).hexdigest()[:12]
        return state_root / "wait-local-agent" / data_identity / "logs"
    if settings.log_dir.is_absolute():
        return settings.log_dir
    return (settings.data_path.parent / settings.log_dir).absolute()


def _platform_state_root() -> Path:
    if os.name == "nt":
        return Path.home() / "AppData" / "Local"
    return Path.home() / ".local" / "state"


def configure_structured_logging(settings: Settings) -> Path:
    log_dir = configured_log_directory(settings)
    fs_permissions.create_private_directory(log_dir)
    fs_permissions.restrict_existing_directory(log_dir)
    log_path = log_dir / LOG_FILE_NAME

    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path:
            return log_path

    handler = PrivateRotatingFileHandler(
        log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
        delay=False,
    )
    handler.setFormatter(ScrubbedJsonFormatter())
    root.addHandler(handler)
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    fs_permissions.restrict_existing_file(log_path)
    return log_path
