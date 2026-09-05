"""The provider-agnostic contract every LLM backend implements.

Everything upstream — narration extraction, header mapping, residue classification —
talks to this interface and nothing else. Swapping Perplexity for Anthropic or OpenAI
later is a matter of writing one more class here and pointing the factory in
``recon.llm`` at it; no caller changes.

The interface is deliberately narrow: one method, JSON in, JSON out, against a schema
the caller supplies. There is no streaming, no tool use, no chat history — none of
that is needed for classification and extraction calls, and not supporting it is what
keeps a second provider a small class rather than a rewrite.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class LlmError(RuntimeError):
    """Raised when a provider cannot produce a schema-conforming answer."""


@runtime_checkable
class LlmProvider(Protocol):
    """A chat model that returns one JSON object conforming to a caller-supplied schema."""

    #: Short, stable identifier written into ``RunMeta.llm_provider`` — "perplexity",
    #: "stub", and so on. Never the model name; a provider may serve several models.
    name: str

    def complete_json(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        system: str,
        user: str,
    ) -> dict[str, Any]:
        """Return one object satisfying ``schema``.

        ``schema_name`` is not sent to every backend's API, but it is always mixed into
        the cache key: two callers asking different questions about byte-identical text
        must never share a cache entry.
        """
        ...
