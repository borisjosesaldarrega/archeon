"""Structured local logging with conservative secret redaction."""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_REDACTIONS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"), r"\1<redacted>"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|private[_-]?key)\s*[:=]\s*)[^\s,;]+"), r"\1<redacted>"),
    (re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL), "<redacted-private-key>"),
)


def redact(value: object) -> str:
    text = str(value)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original_message, original_args = record.msg, record.args
        try:
            record.msg = redact(record.msg)
            record.args = tuple(redact(arg) for arg in record.args) if record.args else ()
            return super().format(record)
        finally:
            record.msg, record.args = original_message, original_args


def configure_logging(log_dir: Path, *, console: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("archeon")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in tuple(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(
        log_dir / "archeon.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    safe_fields = {key: redact(value) for key, value in fields.items()}
    logger.info("%s %s", event, json.dumps(safe_fields, ensure_ascii=False, sort_keys=True))


def close_logger(logger: logging.Logger) -> None:
    """Flush and close owned handlers so Windows releases the log immediately."""
    for handler in tuple(logger.handlers):
        try:
            handler.flush()
        finally:
            handler.close()
            logger.removeHandler(handler)
