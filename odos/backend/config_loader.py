"""Backwards-compatible access to configuration. New code should use odos.config."""
from odos.config import get_config, reload_config  # noqa: F401

CONFIG = get_config()


def load_config():
    return reload_config()
