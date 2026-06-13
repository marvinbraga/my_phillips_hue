"""
Marvin Hue Chat Module

Este módulo implementa um sistema de chat com agente ReAct para controle
de lâmpadas Philips Hue usando LangChain e LangGraph.

Arquitetura:
- providers/: Abstrações e implementações de provedores LLM (OpenAI, Anthropic, xAI)
- tools/: Ferramentas para controle das lâmpadas
- agents/: Implementação do agente ReAct com LangGraph
"""

from marvin_hue.chat.agents import HueLightAgent, create_hue_agent
from marvin_hue.chat.agents.react_agent import HueLightAgentBuilder, AgentConfig
from marvin_hue.chat.providers import (
    LLMProviderRegistry,
    LLMProviderFactory,
    LLMProviderBuilder,
)
from marvin_hue.chat.tools import build_light_tools

__all__ = [
    # Agents
    "HueLightAgent",
    "HueLightAgentBuilder",
    "AgentConfig",
    "create_hue_agent",
    # Providers
    "LLMProviderRegistry",
    "LLMProviderFactory",
    "LLMProviderBuilder",
    # Tools
    "build_light_tools",
]
