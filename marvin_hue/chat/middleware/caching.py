"""Builder único do cache de prompt da Anthropic (orquestrador e subagents)."""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware

PROMPT_CACHE_TTL = "5m"


def prompt_caching_middleware() -> AgentMiddleware:
    """``AnthropicPromptCachingMiddleware`` com o TTL compartilhado.

    Só faz sentido com provider anthropic; o chamador decide quando usar.
    """
    from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

    return AnthropicPromptCachingMiddleware(ttl=PROMPT_CACHE_TTL)
