"""Logging configuration for ObservIA Emploi."""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Set up structured console logging for the project."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
