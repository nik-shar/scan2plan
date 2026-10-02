"""Logging helper - one configured logger for the whole package."""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def get_logger(name: str = "scan2plan") -> logging.Logger:
    """Return a package logger, configuring a basic handler once."""
    global _CONFIGURED
    if not _CONFIGURED:
        level = os.environ.get("SCAN2PLAN_LOG", "INFO").upper()
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        )
        _CONFIGURED = True
    return logging.getLogger(name)
