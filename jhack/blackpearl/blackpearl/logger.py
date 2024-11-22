import logging
import os

bp_logger = logging.getLogger("blackpearl")
logging.basicConfig(level=os.getenv("LOGLEVEL", logging.DEBUG))
bp_logger.info(f"blackpearl_logger initialized with {bp_logger.level}")
