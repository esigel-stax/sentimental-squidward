"""Load .env once, from the project root, before anything reads os.getenv.

Without this, `.env.example` is a lie: every adapter calls os.getenv and would
only ever see variables exported in the shell. Imported for its side effect by
both entrypoints.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, ".env")


def load() -> bool:
    """Returns True if a .env was found and loaded. Real env vars always win."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    if not os.path.exists(ENV_PATH):
        return False
    load_dotenv(ENV_PATH, override=False)
    return True


loaded = load()
