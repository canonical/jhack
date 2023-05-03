"""Jhack logging module."""

import logging
import os

LOGLEVEL = os.environ.get("LOGLEVEL", "WARNING").upper()
logging.basicConfig(level=LOGLEVEL)
logger = logging.getLogger("jhack")
