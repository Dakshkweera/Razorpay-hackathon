"""Perplexity backend.

``sonar`` with search disabled and temperature 0: the model is used purely as a text
extractor and classifier over content already in the prompt, never as a search
engine, and never with any randomness that would make two runs disagree.

Perplexity's chat-completions endpoint is OpenAI-compatible, so swapping to Anthropic
or OpenAI later is realistically a different base URL and a different response
envelope to unwrap — not a different calling convention. That is the whole point of
keeping :class:`~recon.llm.base.LlmProvider` this narrow.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from recon.llm.base import LlmError

DEFAULT_BASE_URL = "https://api.perplexity.ai"
DEFAULT_MODEL = "sonar"


class PerplexityProvider:
    name = "perplexity"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        if not key:
            raise LlmError(
                "PERPLEXITY_API_KEY is not set - export it, or use LlmMode.CACHE / "
                "LlmMode.STUB to run without calling the network"
            )
        self._api_key = key
        self._model = model or os.environ.get("PERPLEXITY_MODEL", DEFAULT_MODEL)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def complete_json(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        system: str,
        user: str,
    ) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "temperature": 0,
            "disable_search": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema},
            },
        }
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
        except httpx.HTTPError as error:
            raise LlmError(f"perplexity request failed: {error}") from error
        except (KeyError, IndexError, json.JSONDecodeError) as error:
            raise LlmError(f"perplexity returned an unparseable response: {error}") from error
