"""Dead-simple persistent cache so re-runs don't re-pay for scoring.

Keyed by (mention id, model, prompt version) — bump PROMPT_VERSION in analyze.py
and every entry invalidates itself, which is what you want when you tune a prompt.
"""

import json
import os
from typing import Optional


class Cache:
    def __init__(self, path: str, enabled: bool = True):
        self.path = path
        self.enabled = enabled
        self._data = {}
        self.hits = 0
        if enabled and os.path.exists(path):
            try:
                with open(path) as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, key: str) -> Optional[dict]:
        if not self.enabled:
            return None
        v = self._data.get(key)
        if v is not None:
            self.hits += 1
        return v

    def put(self, key: str, value: dict) -> None:
        if self.enabled:
            self._data[key] = value

    def flush(self) -> None:
        if not self.enabled:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f)
