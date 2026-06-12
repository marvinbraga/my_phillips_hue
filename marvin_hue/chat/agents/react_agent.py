"""
ReAct Agent - Agente ReAct para controle de lâmpadas Philips Hue.

Utiliza LangGraph para implementar o padrão ReAct (Reason + Act)
para interação inteligente com as lâmpadas.
"""

import time
from typing import Optional, Any
from collections.abc import Iterator, AsyncIterator
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import InMemorySaver

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat.providers import LLMProviderFactory
from marvin_hue.chat.tools import configure_tools, get_all_tools


# Limite de sessões mantidas no checkpointer em memória (eviction LRU).
# Cada session_id novo cria uma thread que nunca seria coletada -> vazamento
# monotônico num servidor de longa duração. O LRU descarta a mais antiga.
MAX_SESSIONS = 100


# System prompt para o agente
SYSTEM_PROMPT = """Você é Marvin, um assistente inteligente especializado em controle de iluminação Philips Hue.

Suas capacidades incluem:
- Listar todas as lâmpadas disponíveis
- Verificar o status atual das lâmpadas (cor, brilho, estado)
- Alterar a cor de lâmpadas individuais usando valores RGB
- Aplicar configurações de iluminação predefinidas (temas)
- Ligar e desligar lâmpadas
- Ajustar o brilho
- Consultar a localização física das lâmpadas no ambiente

⚠️ RESTRIÇÕES IMPORTANTES DE INTENSIDADE:
- "Fita Led" (embaixo do monitor): Intensidade MÁXIMA 25% (64/254 brilho Hue)
- "Led cima" (em cima do monitor): Intensidade MÁXIMA 25% (64/254 brilho Hue)
- Estas lâmpadas estão muito próximas aos olhos do usuário. Intensidades maiores forçam a vista!
- SEMPRE respeite esses limites ao configurar essas lâmpadas, mesmo que o usuário não mencione

Diretrizes:
1. Sempre seja prestativo e amigável
2. Quando o usuário pedir para mudar cores, use os valores RGB apropriados
3. Se o usuário mencionar um tema ou ambiente (ex: "relaxante", "festa"), procure uma configuração adequada
4. Ao listar lâmpadas ou configurações, formate a saída de forma clara
5. Se houver erro, explique o problema de forma simples
6. Responda sempre em português brasileiro
7. Considere a localização física das lâmpadas:
   - Use a ferramenta get_light_locations_tool quando relevante para entender o posicionamento
   - Faça sugestões inteligentes baseadas na posição (ex: "teto para ambiente", "atrás do monitor para destaque")
   - SEMPRE respeite os limites de intensidade das lâmpadas frontais (Fita Led e Led cima: máx 25%)
   - Lâmpadas do teto podem usar intensidade total
   - Hue Play (atrás do monitor) são ideais para criar atmosfera
8. Ao salvar uma nova configuração:
   - SEMPRE forneça um nome criativo e descritivo (sem espaços, use underscores)
   - SEMPRE forneça uma descrição de uma linha que capture o mood/ambiente
   - Base o nome e descrição nas cores atuais das lâmpadas e no contexto da conversa
   - Exemplos:
     * Cores vermelhas/verdes → nome: "natal_festivo", descrição: "Tema natalino com cores tradicionais"
     * Cores azuis/roxas → nome: "noite_relaxante", descrição: "Ambiente calmo para relaxar"
     * Cores laranjas/amarelas → nome: "por_do_sol", descrição: "Cores quentes inspiradas no pôr do sol"

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
        config: Optional[AgentConfig] = None,
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

        # Memória por sessão via checkpointer (thread_id = session_id).
        # Substitui o antigo _conversation_history de instância (bug #2: estado
        # compartilhado entre todas as sessões).
        self._checkpointer = InMemorySaver()
        self._session_last_access: dict[str, float] = {}
        self._max_sessions = MAX_SESSIONS

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
            checkpointer=self._checkpointer,
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

    @staticmethod
    def _config_for(session_id: str) -> RunnableConfig:
        """Config do checkpointer: thread_id isola o histórico por sessão."""
        return {"configurable": {"thread_id": session_id}}

    def _touch_session(self, session_id: str) -> None:
        """Marca a sessão como acessada e aplica eviction LRU se exceder o limite."""
        self._session_last_access[session_id] = time.monotonic()
        while len(self._session_last_access) > self._max_sessions:
            oldest = min(
                self._session_last_access,
                key=self._session_last_access.__getitem__,
            )
            self._checkpointer.delete_thread(oldest)
            del self._session_last_access[oldest]

    def invoke(self, message: str, session_id: str = "default") -> str:
        """Processa uma mensagem do usuário.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer). É o ÚNICO
                mecanismo de isolamento de histórico — clientes distintos DEVEM
                enviar ids distintos e estáveis.

        Returns:
            Resposta do agente
        """
        self._touch_session(session_id)
        result = self._agent.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=self._config_for(session_id),
        )
        return self._extract_response(result)

    async def ainvoke(self, message: str, session_id: str = "default") -> str:
        """Processa uma mensagem de forma assíncrona.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer).

        Returns:
            Resposta do agente
        """
        self._touch_session(session_id)
        result = await self._agent.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config=self._config_for(session_id),
        )
        return self._extract_response(result)

    def stream(self, message: str, session_id: str = "default") -> Iterator[str]:
        """Processa uma mensagem com streaming.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer).

        Yields:
            Chunks da resposta
        """
        self._touch_session(session_id)
        for chunk in self._agent.stream(
            {"messages": [HumanMessage(content=message)]},
            config=self._config_for(session_id),
            stream_mode="values",
        ):
            messages = chunk.get("messages", [])
            if messages:
                last = messages[-1]
                if isinstance(last, AIMessage) and last.content and not last.tool_calls:
                    yield last.content if isinstance(last.content, str) else str(last.content)
        # NÃO re-invocar: o checkpointer já persistiu o histórico (corrige bug #1).

    async def astream(self, message: str, session_id: str = "default") -> AsyncIterator[str]:
        """Processa uma mensagem com streaming assíncrono.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer).

        Yields:
            Chunks da resposta
        """
        self._touch_session(session_id)
        async for chunk in self._agent.astream(
            {"messages": [HumanMessage(content=message)]},
            config=self._config_for(session_id),
            stream_mode="values",
        ):
            messages = chunk.get("messages", [])
            if messages:
                last = messages[-1]
                if isinstance(last, AIMessage) and last.content and not last.tool_calls:
                    yield last.content if isinstance(last.content, str) else str(last.content)

    def clear_history(self, session_id: str = "default") -> None:
        """Limpa o histórico de uma sessão zerando o thread no checkpointer."""
        self._checkpointer.delete_thread(session_id)
        self._session_last_access.pop(session_id, None)


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
            controller=self._controller, manager=self._manager, config=self._config
        )


def create_hue_agent(
    controller: HueController,
    manager: LightSetupsManager,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    **kwargs,
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
        provider=provider, model=model, temperature=temperature, **kwargs
    )

    return HueLightAgent(controller=controller, manager=manager, config=config)
