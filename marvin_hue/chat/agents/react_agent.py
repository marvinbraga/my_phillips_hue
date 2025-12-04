"""
ReAct Agent - Agente ReAct para controle de lâmpadas Philips Hue.

Utiliza LangGraph para implementar o padrão ReAct (Reason + Act)
para interação inteligente com as lâmpadas.
"""

from typing import Optional, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.prebuilt import create_react_agent
from langgraph.graph.state import CompiledStateGraph

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat.providers import LLMProviderFactory, LLMProviderBuilder
from marvin_hue.chat.tools import configure_tools, get_all_tools


# System prompt para o agente
SYSTEM_PROMPT = """Você é Marvin, um assistente inteligente especializado em controle de iluminação Philips Hue.

Suas capacidades incluem:
- Listar todas as lâmpadas disponíveis
- Verificar o status atual das lâmpadas (cor, brilho, estado)
- Alterar a cor de lâmpadas individuais usando valores RGB
- Aplicar configurações de iluminação predefinidas (temas)
- Ligar e desligar lâmpadas
- Ajustar o brilho

Diretrizes:
1. Sempre seja prestativo e amigável
2. Quando o usuário pedir para mudar cores, use os valores RGB apropriados
3. Se o usuário mencionar um tema ou ambiente (ex: "relaxante", "festa"), procure uma configuração adequada
4. Ao listar lâmpadas ou configurações, formate a saída de forma clara
5. Se houver erro, explique o problema de forma simples
6. Responda sempre em português brasileiro

Cores comuns em RGB:
- Vermelho: (255, 0, 0)
- Verde: (0, 255, 0)
- Azul: (0, 0, 255)
- Amarelo: (255, 255, 0)
- Roxo: (128, 0, 128)
- Rosa: (255, 105, 180)
- Laranja: (255, 165, 0)
- Branco quente: (255, 244, 229)
- Branco frio: (255, 255, 255)
"""


@dataclass
class AgentConfig:
    """Configuração para o agente de iluminação.

    Attributes:
        provider: Nome do provedor LLM (openai, anthropic, xai)
        model: Nome do modelo a ser usado
        temperature: Temperatura para geração de respostas
        max_tokens: Número máximo de tokens na resposta
        streaming: Se deve usar streaming de respostas
        system_prompt: Prompt de sistema customizado
    """
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    streaming: bool = True
    system_prompt: str = SYSTEM_PROMPT
    extra_params: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Classe base abstrata para agentes de chat.

    Define a interface que todos os agentes devem implementar.
    """

    @abstractmethod
    def invoke(self, message: str) -> str:
        """Processa uma mensagem e retorna a resposta.

        Args:
            message: Mensagem do usuário

        Returns:
            Resposta do agente
        """
        pass

    @abstractmethod
    async def ainvoke(self, message: str) -> str:
        """Processa uma mensagem de forma assíncrona.

        Args:
            message: Mensagem do usuário

        Returns:
            Resposta do agente
        """
        pass

    @abstractmethod
    def stream(self, message: str):
        """Processa uma mensagem com streaming.

        Args:
            message: Mensagem do usuário

        Yields:
            Chunks da resposta
        """
        pass


class HueLightAgent(BaseAgent):
    """Agente ReAct para controle de lâmpadas Philips Hue.

    Utiliza LangGraph create_react_agent para implementar o padrão ReAct.
    Suporta múltiplos provedores LLM através do sistema de providers.

    Attributes:
        controller: Controlador Hue para interagir com as lâmpadas
        manager: Gerenciador de configurações de iluminação
        config: Configuração do agente
    """

    def __init__(
        self,
        controller: HueController,
        manager: LightSetupsManager,
        config: Optional[AgentConfig] = None
    ):
        """Inicializa o agente.

        Args:
            controller: Instância do HueController
            manager: Instância do LightSetupsManager
            config: Configuração do agente (usa padrão se não fornecido)
        """
        self._controller = controller
        self._manager = manager
        self._config = config or AgentConfig()
        self._conversation_history: list[BaseMessage] = []

        # Configura as ferramentas com as referências necessárias
        configure_tools(controller, manager)

        # Cria o modelo LLM
        self._llm = self._create_llm()

        # Cria o agente ReAct
        self._agent = self._create_agent()

    def _create_llm(self) -> BaseChatModel:
        """Cria a instância do modelo LLM usando o factory.

        Returns:
            Modelo LLM configurado
        """
        # Só passa extra_params se houver valores
        kwargs = {}
        if self._config.extra_params:
            kwargs = self._config.extra_params

        provider = LLMProviderFactory.create(
            provider_name=self._config.provider,
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            streaming=self._config.streaming,
            **kwargs,
        )
        return provider.model

    def _create_agent(self) -> CompiledStateGraph:
        """Cria o agente ReAct com LangGraph.

        Returns:
            Grafo compilado do agente
        """
        tools = get_all_tools()

        agent = create_react_agent(
            model=self._llm,
            tools=tools,
            prompt=self._config.system_prompt,
        )

        return agent

    def _extract_response(self, result: dict) -> str:
        """Extrai a resposta final do resultado do agente.

        Args:
            result: Resultado retornado pelo agente

        Returns:
            Texto da resposta
        """
        messages = result.get("messages", [])
        if not messages:
            return "Desculpe, não consegui processar sua solicitação."

        # Pega a última mensagem AI
        for message in reversed(messages):
            if isinstance(message, AIMessage) and message.content:
                # Ignora mensagens que são apenas tool calls
                if not message.tool_calls:
                    return message.content

        return "Operação concluída."

    def invoke(self, message: str) -> str:
        """Processa uma mensagem do usuário.

        Args:
            message: Mensagem do usuário

        Returns:
            Resposta do agente
        """
        # Adiciona a mensagem do usuário ao histórico
        self._conversation_history.append(HumanMessage(content=message))

        # Invoca o agente
        result = self._agent.invoke({
            "messages": self._conversation_history
        })

        # Atualiza o histórico com as novas mensagens
        new_messages = result.get("messages", [])
        if new_messages:
            # Substitui o histórico com as novas mensagens
            self._conversation_history = new_messages

        # Extrai e retorna a resposta
        response = self._extract_response(result)
        return response

    async def ainvoke(self, message: str) -> str:
        """Processa uma mensagem de forma assíncrona.

        Args:
            message: Mensagem do usuário

        Returns:
            Resposta do agente
        """
        # Adiciona a mensagem do usuário ao histórico
        self._conversation_history.append(HumanMessage(content=message))

        # Invoca o agente de forma assíncrona
        result = await self._agent.ainvoke({
            "messages": self._conversation_history
        })

        # Atualiza o histórico com as novas mensagens
        new_messages = result.get("messages", [])
        if new_messages:
            self._conversation_history = new_messages

        # Extrai e retorna a resposta
        response = self._extract_response(result)
        return response

    def stream(self, message: str):
        """Processa uma mensagem com streaming.

        Args:
            message: Mensagem do usuário

        Yields:
            Chunks da resposta
        """
        # Adiciona a mensagem do usuário ao histórico
        self._conversation_history.append(HumanMessage(content=message))

        # Stream do agente
        for event in self._agent.stream({
            "messages": self._conversation_history
        }):
            # Processa eventos do agente
            if "messages" in event:
                for msg in event["messages"]:
                    if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                        yield msg.content

        # Atualiza histórico após streaming completo
        result = self._agent.invoke({
            "messages": self._conversation_history
        })
        self._conversation_history = result.get("messages", self._conversation_history)

    async def astream(self, message: str):
        """Processa uma mensagem com streaming assíncrono.

        Args:
            message: Mensagem do usuário

        Yields:
            Chunks da resposta
        """
        # Adiciona a mensagem do usuário ao histórico
        self._conversation_history.append(HumanMessage(content=message))

        # Stream assíncrono do agente
        async for event in self._agent.astream({
            "messages": self._conversation_history
        }):
            if "messages" in event:
                for msg in event["messages"]:
                    if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                        yield msg.content

    def clear_history(self) -> None:
        """Limpa o histórico de conversação."""
        self._conversation_history = []

    @property
    def conversation_history(self) -> list[BaseMessage]:
        """Retorna o histórico de conversação."""
        return self._conversation_history.copy()


class HueLightAgentBuilder:
    """Builder para construção de HueLightAgent.

    Permite configuração fluente do agente.

    Example:
        agent = (HueLightAgentBuilder()
            .with_controller(controller)
            .with_manager(manager)
            .with_provider("anthropic")
            .with_model("claude-3-5-sonnet-20241022")
            .with_temperature(0.5)
            .build())
    """

    def __init__(self):
        """Inicializa o builder."""
        self._controller: Optional[HueController] = None
        self._manager: Optional[LightSetupsManager] = None
        self._config = AgentConfig()

    def with_controller(self, controller: HueController) -> "HueLightAgentBuilder":
        """Define o controlador Hue.

        Args:
            controller: Instância do HueController

        Returns:
            Self para encadeamento
        """
        self._controller = controller
        return self

    def with_manager(self, manager: LightSetupsManager) -> "HueLightAgentBuilder":
        """Define o gerenciador de configurações.

        Args:
            manager: Instância do LightSetupsManager

        Returns:
            Self para encadeamento
        """
        self._manager = manager
        return self

    def with_provider(self, provider: str) -> "HueLightAgentBuilder":
        """Define o provedor LLM.

        Args:
            provider: Nome do provedor (openai, anthropic, xai)

        Returns:
            Self para encadeamento
        """
        self._config.provider = provider
        return self

    def with_model(self, model: str) -> "HueLightAgentBuilder":
        """Define o modelo LLM.

        Args:
            model: Nome do modelo

        Returns:
            Self para encadeamento
        """
        self._config.model = model
        return self

    def with_temperature(self, temperature: float) -> "HueLightAgentBuilder":
        """Define a temperatura.

        Args:
            temperature: Valor da temperatura (0.0 a 1.0)

        Returns:
            Self para encadeamento
        """
        self._config.temperature = temperature
        return self

    def with_max_tokens(self, max_tokens: int) -> "HueLightAgentBuilder":
        """Define o número máximo de tokens.

        Args:
            max_tokens: Limite de tokens

        Returns:
            Self para encadeamento
        """
        self._config.max_tokens = max_tokens
        return self

    def with_streaming(self, streaming: bool) -> "HueLightAgentBuilder":
        """Define se usa streaming.

        Args:
            streaming: True para habilitar streaming

        Returns:
            Self para encadeamento
        """
        self._config.streaming = streaming
        return self

    def with_system_prompt(self, prompt: str) -> "HueLightAgentBuilder":
        """Define o prompt de sistema.

        Args:
            prompt: Texto do prompt de sistema

        Returns:
            Self para encadeamento
        """
        self._config.system_prompt = prompt
        return self

    def with_extra_params(self, **params) -> "HueLightAgentBuilder":
        """Define parâmetros extras.

        Args:
            **params: Parâmetros adicionais

        Returns:
            Self para encadeamento
        """
        self._config.extra_params.update(params)
        return self

    def build(self) -> HueLightAgent:
        """Constrói o agente.

        Returns:
            Instância configurada do HueLightAgent

        Raises:
            ValueError: Se controller ou manager não foram definidos
        """
        if self._controller is None:
            raise ValueError("Controller não foi definido. Use with_controller().")
        if self._manager is None:
            raise ValueError("Manager não foi definido. Use with_manager().")

        return HueLightAgent(
            controller=self._controller,
            manager=self._manager,
            config=self._config
        )


def create_hue_agent(
    controller: HueController,
    manager: LightSetupsManager,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    **kwargs
) -> HueLightAgent:
    """Factory function para criar um agente de iluminação.

    Forma simplificada de criar um agente com configurações padrão.

    Args:
        controller: Instância do HueController
        manager: Instância do LightSetupsManager
        provider: Nome do provedor LLM
        model: Nome do modelo
        temperature: Temperatura para geração
        **kwargs: Parâmetros adicionais para o AgentConfig

    Returns:
        Instância configurada do HueLightAgent

    Example:
        agent = create_hue_agent(
            controller=hue,
            manager=manager,
            provider="openai",
            model="gpt-4o"
        )
    """
    config = AgentConfig(
        provider=provider,
        model=model,
        temperature=temperature,
        **kwargs
    )

    return HueLightAgent(
        controller=controller,
        manager=manager,
        config=config
    )
