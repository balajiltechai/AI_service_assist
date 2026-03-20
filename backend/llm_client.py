"""
Shared LLM client — calls Claude via the Anthropic SDK.
"""
import anthropic
from typing import AsyncGenerator
from backend.config import get_settings

_client: anthropic.Anthropic | None = None
_async_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    return _client


def _get_async_client() -> anthropic.AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = anthropic.AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _async_client


def call_llm(system: str, user: str) -> str:
    """Send a system+user prompt to Claude and return the response text."""
    settings = get_settings()
    msg = _get_client().messages.create(
        model=settings.claude_model,
        max_tokens=settings.max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


async def stream_llm_fast(system: str, user: str, max_tokens: int = 600) -> AsyncGenerator[str, None]:
    """Async streaming LLM call using Haiku. Yields text chunks as they arrive."""
    async with _get_async_client().messages.stream(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
