"""SHA-256-keyed fixture cache, wrapping any :class:`~recon.llm.base.LlmProvider`.

Every call this system makes to a real model is keyed on the exact schema name and
prompt text and written to ``fixtures/llm/<hash>.json``. Committing that directory is
what lets ``recon verify`` and the demo run offline and byte-identical: replaying a
committed fixture is indistinguishable, from the caller's side, from making the call
again and getting the same answer - because ``temperature: 0`` promises that it would.

This class does not decide *whether* to fall back to a stub on a cache miss; that
policy lives in :mod:`recon.llm` (the factory), so this file stays what it is - a
cache, not a strategy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from recon.llm.base import LlmProvider

DEFAULT_CACHE_DIR = Path("fixtures/llm")


def cache_key(*, schema_name: str, system: str, user: str) -> str:
    canonical = json.dumps(
        {"schema_name": schema_name, "system": system, "user": user},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CachingProvider:
    """Replays a committed fixture when one matches; otherwise defers to ``inner``.

    ``inner`` is usually a real backend (writes the fixture it just earned) or a
    :class:`~recon.llm.stub.StubProvider` (never writes - see ``read_only``). Two
    counters are kept because ``RunMeta.llm_calls`` and ``RunMeta.llm_cache_hits`` are
    exactly this class's ``calls`` and ``cache_hits`` at the end of a run.
    """

    def __init__(
        self,
        inner: LlmProvider,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        *,
        read_only: bool = False,
    ) -> None:
        self._inner = inner
        self._dir = cache_dir
        self._read_only = read_only
        self.name = inner.name
        self.calls = 0
        self.cache_hits = 0

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def complete_json(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        system: str,
        user: str,
    ) -> dict[str, Any]:
        self.calls += 1
        key = cache_key(schema_name=schema_name, system=system, user=user)
        path = self._path(key)
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))

        result = self._inner.complete_json(
            schema_name=schema_name, schema=schema, system=system, user=user
        )
        if not self._read_only:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="",
            )
        return result
