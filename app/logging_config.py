"""Logging configuration with automatic secret redaction.

Ensures session cookies, CSRF tokens, authorization headers, and passwords
are never written to console output or persistent log files.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional


class SecretRedactorFilter(logging.Filter):
    """
    Log filter that masks sensitive authentication data including
    JSESSIONID, CSRF tokens, basic auth credentials, and passwords.
    """

    DEFAULT_PATTERNS = [
        # Session cookies
        re.compile(r"(JSESSIONID=)[^;\s&]+", re.IGNORECASE),
        re.compile(r"('Cookie':\s*'[^']*(?:JSESSIONID=)[^;'\s]+[^']*')", re.IGNORECASE),
        # CSRF tokens in headers and bodies
        re.compile(r"(X-CSRF-TOKEN[:=]\s*)[0-9a-fA-F-]+", re.IGNORECASE),
        re.compile(r"(_csrf[:=]\s*)[0-9a-fA-F-]+", re.IGNORECASE),
        re.compile(r"(<meta\s+name=[\"']_csrf[\"']\s+content=[\"'])[^\"']+", re.IGNORECASE),
        # Passwords and credentials
        re.compile(r"(password=)[^&\s]+", re.IGNORECASE),
        re.compile(r"(authorization:\s*Bearer\s+)[^\s]+", re.IGNORECASE),
    ]

    def __init__(self, known_secrets: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self._exact_secrets: set[str] = set()
        if known_secrets:
            for s in known_secrets:
                if s and len(s.strip()) > 4:  # Avoid redacting tiny strings
                    self._exact_secrets.add(s.strip())

    def add_secret(self, secret: Optional[str]) -> None:
        """Register a known secret string to redact."""
        if secret and len(secret.strip()) > 4:
            self._exact_secrets.add(secret.strip())

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(str(arg)) for arg in record.args)
        return True

    def _redact(self, text: str) -> str:
        # Mask regex patterns
        for pattern in self.DEFAULT_PATTERNS:
            text = pattern.sub(r"\1***REDACTED***", text)
        # Mask exact secret values
        for sec in self._exact_secrets:
            if sec in text:
                text = text.replace(sec, "***REDACTED***")
        return text


_global_redactor = SecretRedactorFilter()


def register_secret(secret: Optional[str]) -> None:
    """Register a runtime secret string with the global redaction filter."""
    _global_redactor.add_secret(secret)


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[Path | str] = None,
    known_secrets: Optional[Iterable[str]] = None,
) -> logging.Logger:
    """
    Configure root/application logger with secret redaction filter.
    """
    logger = logging.getLogger("flash_automator")
    logger.setLevel(level)

    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if known_secrets:
        for s in known_secrets:
            _global_redactor.add_secret(s)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_global_redactor)
    logger.addHandler(console_handler)

    # File handler if requested
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(_global_redactor)
        logger.addHandler(file_handler)

    return logger
