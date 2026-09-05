"""Cache of extracted fields, keyed by normalised narration text.

This sits above :mod:`recon.llm.cache`, not in place of it. The LLM cache is keyed on
the exact prompt sent (a whole batch of up to twenty narrations at once), so
re-batching the same narrations differently between runs would miss it. This cache is
keyed on one narration at a time, so a format that has already been read once - by any
batch, in any run - is never sent to a model again. Real statements repeat formats
constantly; this is the cache that actually pays for itself.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PATH = Path("fixtures/llm/narration_cache.json")


class NarrationCache:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self._path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put_many(self, items: dict[str, dict]) -> None:
        if not items:
            return
        self._data.update(items)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="",
        )
