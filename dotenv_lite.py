"""
Minimal .env loader (no third-party dependency).

Parses simple KEY=VALUE lines from a .env file and injects them into
os.environ *without* overwriting variables already set in the real
environment (so pm2 / shell env always wins over the file).
"""

import os


def load_dotenv(path):
    """Load KEY=VALUE pairs from `path` into os.environ (set-default semantics)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
