"""Factory: turn an :class:`~recon.report.LlmMode` into a usable provider.

This is the one place in the codebase that knows Perplexity exists. Every caller -
narration extraction, header mapping, residue classification - takes an
``LlmProvider | None`` and asks nothing about which one it is. Adding Anthropic or
OpenAI later means writing ``recon/llm/anthropic.py`` and adding one branch here.

Mode resolution order, cheapest and most offline first:

* ``off``   - no provider at all; callers fall back to their deterministic floor.
* ``stub``  - the deterministic offline stand-in, always available, never network.
* ``cache`` - replay committed fixtures; a miss falls back to the stub rather than
              failing a demo that happens to hit an uncached input.
* ``live``  - call Perplexity for real, writing every response as a new fixture.

:func:`resolve_mode` is what ``off``-by-default-unless-configured means in practice:
without an API key and without an explicit override, a run uses ``cache`` if any
fixtures are committed, else ``stub`` - never an error, never a network call nobody
asked for.
"""

from __future__ import annotations

import os
from pathlib import Path

from recon.llm.base import LlmProvider
from recon.llm.cache import DEFAULT_CACHE_DIR, CachingProvider
from recon.llm.stub import StubProvider
from recon.report import LlmMode

__all__ = ["build_provider", "resolve_mode", "DEFAULT_CACHE_DIR"]


def resolve_mode(env: dict[str, str] | None = None) -> LlmMode:
    environ = env if env is not None else os.environ
    override = environ.get("RECON_LLM_MODE", "").strip().lower()
    if override:
        try:
            return LlmMode(override)
        except ValueError as error:
            raise ValueError(
                f"RECON_LLM_MODE={override!r} is not one of {[m.value for m in LlmMode]}"
            ) from error
    if environ.get("PERPLEXITY_API_KEY"):
        return LlmMode.LIVE
    if any(DEFAULT_CACHE_DIR.glob("*.json")):
        return LlmMode.CACHE
    return LlmMode.STUB


def build_provider(
    mode: LlmMode, *, cache_dir: Path = DEFAULT_CACHE_DIR
) -> LlmProvider | None:
    if mode is LlmMode.OFF:
        return None
    if mode is LlmMode.STUB:
        return StubProvider()
    if mode is LlmMode.CACHE:
        # A miss here degrades to the stub's honest guess rather than raising: a demo
        # should never crash because one narration format wasn't in the fixture set.
        return CachingProvider(StubProvider(), cache_dir, read_only=True)
    if mode is LlmMode.LIVE:
        from recon.llm.perplexity import PerplexityProvider

        return CachingProvider(PerplexityProvider(), cache_dir)
    raise ValueError(f"unhandled LlmMode: {mode!r}")
