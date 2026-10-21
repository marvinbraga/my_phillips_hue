"""
ReAct Agent - Agente ReAct para controle de lâmpadas Philips Hue.

Utiliza LangGraph para implementar o padrão ReAct (Reason + Act)
para interação inteligente com as lâmpadas.
"""

import asyncio
import time
import weakref
from typing import Optional, Any
from collections.abc import Iterator, AsyncIterator
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware, SummarizationMiddleware
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.chat.providers import LLMProviderFactory
from marvin_hue.chat.messages import message_text as _message_text
from marvin_hue.chat.services import ChatServices
from marvin_hue.chat.tools import build_all_tools
from marvin_hue.chat.hitl import (
    HITL_DESCRIPTION_PREFIX,
    HITL_INTERRUPT_ON,
    ApprovalRequired,
    approval_from_interrupts,
    build_resume_map,
    cancellation_messages,
    dangling_tool_calls,
)
from marvin_hue.chat.middleware.eye_safety import EyeSafetyMiddleware
from marvin_hue.chat.middleware.hue_context import HueContextMiddleware


# Limite de sessões mantidas no checkpointer em memória (eviction LRU).
# Cada session_id novo cria uma thread que nunca seria coletada -> vazamento
# monotônico num servidor de longa duração. O LRU descarta a mais antiga.
MAX_SESSIONS = 100


# Versão da superfície de prompt (system prompt + prompts dos subagents +
# nome/descrição/schema das tools). Qualquer mudança nela é eval-gated: bump
# aqui, rode tests/eval/run_tool_selection.py e atualize
# tests/eval/prompt_version.json (o hash é conferido no CI).
PROMPT_VERSION = "hue.chat.prompt@2"

# Um turno por sessão de cada vez (async): impede que dois cliques/abas
# retomem o mesmo checkpoint e executem a ação aprovada duas vezes. É de
# MÓDULO (não do agente) para valer também entre a instância antiga e a nova
# após /api/chat/configure. WeakValueDictionary: o lock some sozinho quando
# ninguém o segura — nunca é removido à mão, então um lock em uso não some.
_SESSION_LOCKS: "weakref.WeakValueDictionary[str, asyncio.Lock]" = (
    weakref.WeakValueDictionary()
)


def session_lock(session_id: str) -> asyncio.Lock:
    """Lock do turno da sessão, compartilhado por todas as instâncias."""
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    return lock


# Teto de passos do grafo do orquestrador por turno (LLM04: loop/custo
# runaway). Cada tool call custa ~2 passos; 25 cobre pedidos compostos.
AGENT_RECURSION_LIMIT = 25


# System prompt para o agente.
# NOTA: o status vivo das lâmpadas, as restrições físicas (limites de
# intensidade) e a lista de presets são INJETADOS a cada turno pelo
# HueContextMiddleware — não são hardcoded aqui. A garantia ocular (<=25% para
# Fita Led/Led cima) é um INVARIANTE DE CÓDIGO no chokepoint do HueController +
# EyeSafetyMiddleware; o prompt apenas a reforça.
SYSTEM_PROMPT = """Você é Marvin, um assistente inteligente especializado em controle de iluminação Philips Hue.

Você controla as lâmpadas via ferramentas: listar/ver status, mudar cor (RGB),
ajustar brilho, ligar/desligar, aplicar e salvar presets, e consultar a
localização física das lâmpadas. Além disso:
- Cenas: buscar (search_configs), detalhar (describe_config), criar
  (create_config), desfazer a última mudança (undo_last_scene) e favoritas
  (list/add/remove_favorite, estrela na tela Controle).
- create_config grava uma cena nova pela especificação de cada lâmpada, sem
  aplicar; save_current_config salva o estado atual "como está agora".
- Grupos: listar e aplicar uma cena só a um grupo (apply_config_to_group).
- Agendamentos: listar, criar (dias 0=segunda … 6=domingo; vazio = todo dia)
  e ativar/desativar.
- Espelhamento de tela/música: status, iniciar e parar.
- Temperatura de cor em Kelvin (set_color_temperature, 2000–6500 K) e saúde
  do sistema (get_system_health).

Diretrizes:
1. Seja prestativo, amigável e responda sempre em português brasileiro.
2. As lâmpadas frontais "Fita Led" e "Led cima" ficam muito próximas aos olhos:
   prefira intensidades baixas. O sistema impõe um teto de segurança por código,
   mas evite pedir brilho alto para elas mesmo assim.
3. Para um tema/ambiente (ex: "aconchegante", "festa"), procure um preset adequado
   antes de montar a cena manualmente.
4. Use o status e as localizações que você recebe no contexto para fazer
   sugestões inteligentes (teto para ambiente, atrás do monitor para atmosfera).
5. Se houver erro, explique de forma simples.
6. Ao salvar uma nova configuração, SEMPRE forneça um nome criativo sem espaços
   (use underscores) e uma descrição de uma linha capturando o mood — baseados
   nas cores atuais e no contexto (ex: "festa_vibrante", "amanhecer_suave").

Quando o pedido for complexo, DELEGUE via a tool `task`:
- Mood/cena multi-lâmpada -> subagent "scene-designer".
- Buscar/recomendar/salvar presets -> "config-librarian".
- Status e dúvidas gerais -> "general-purpose" (ou responda direto se trivial).
Forneça uma description autossuficiente: o subagent não vê o histórico inteiro.
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
    # HITL opcional (env CHAT_REQUIRE_APPROVAL): exige aprovação humana para as
    # tools de mutação ampla (marvin_hue.chat.hitl). Com ele ligado, ainvoke/
    # astream podem devolver ApprovalRequired; retome com aresume(). Requer
    # checkpointer (sempre há um: InMemorySaver ou o do lifespan).
    require_approval: bool = False


class BaseAgent(ABC):
    """Classe base abstrata para agentes de chat.

    Define a interface que todos os agentes devem implementar.
    """

    @abstractmethod
    def invoke(self, message: str, session_id: str = "default") -> "str | ApprovalRequired":
        """Processa uma mensagem e retorna a resposta.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (isolamento de histórico)

        Returns:
            Resposta do agente
        """
        pass

    @abstractmethod
    async def ainvoke(
        self, message: str, session_id: str = "default"
    ) -> "str | ApprovalRequired":
        """Processa uma mensagem de forma assíncrona.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (isolamento de histórico)

        Returns:
            Resposta do agente
        """
        pass

    @abstractmethod
    def stream(
        self, message: str, session_id: str = "default"
    ) -> "Iterator[str | ApprovalRequired]":
        """Processa uma mensagem com streaming.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (isolamento de histórico)

        Yields:
            Chunks da resposta
        """
        pass

    @abstractmethod
    def astream(
        self, message: str, session_id: str = "default"
    ) -> "AsyncIterator[str | ApprovalRequired]":
        """Processa uma mensagem com streaming assíncrono.

        Declarada como `def` (não `async def`) retornando AsyncIterator: é o
        padrão para abstrair um async generator sem que mypy a trate como
        coroutine. A implementação concreta é um `async def` com `yield`.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (isolamento de histórico)

        Yields:
            Chunks da resposta
        """
        ...

    @abstractmethod
    def clear_history(self, session_id: str = "default") -> None:
        """Limpa o histórico de uma sessão.

        Args:
            session_id: Id da sessão cujo histórico será limpo
        """
        pass


class HueLightAgent(BaseAgent):
    """Agente ReAct para controle de lâmpadas Philips Hue.

    Utiliza langchain.agents.create_agent com pilha de middleware (harness).
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
        *,
        checkpointer: Optional[Any] = None,
        room_index: Optional[dict[str, list[str]]] = None,
        services: Optional[ChatServices] = None,
    ):
        """Inicializa o agente.

        Args:
            controller: Instância do HueController
            manager: Instância do LightSetupsManager
            config: Configuração do agente (usa padrão se não fornecido)
            checkpointer: Checkpointer LangGraph injetado. Se None, usa
                InMemorySaver (volátil). O ciclo de vida de um checkpointer
                persistente (ex.: SqliteSaver) é do CHAMADOR (lifespan/with) —
                o agente NUNCA abre SQLite sozinho (evita vazar a conexão).
            room_index: Snapshot sala → nomes (registry). None → tools usam
                fallback de localizações físicas. Mudanças de room no registry
                exigem rebuild do agente (lifespan / reconfigure).
            services: Providers preguiçosos dos serviços do app usados pelas
                tools (favoritos, histórico, grupos, agendamentos,
                espelhamento, saúde). None → padrão (dependencies, fail-open).
        """
        self._controller = controller
        self._manager = manager
        self._config = config or AgentConfig()
        self._room_index = room_index
        self._services = services or ChatServices()

        # Memória por sessão via checkpointer (thread_id = session_id).
        # Substitui o antigo _conversation_history de instância (bug #2: estado
        # compartilhado entre todas as sessões). Injeção-pura: sem fallback que
        # abra SQLite aqui dentro.
        self._checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self._session_last_access: dict[str, float] = {}
        self._max_sessions = MAX_SESSIONS

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

    def _build_middleware(self) -> list:
        """Monta a pilha de middleware do harness.

        A instância de HueContextMiddleware é guardada em self._hue_context para
        ser COMPARTILHADA com os subagents (Fase 4) — compartilha o cache TTL do
        status e evita I/O redundante na bridge.
        """
        self._hue_context = HueContextMiddleware(self._controller, self._manager)
        stack: list = [
            self._hue_context,
            EyeSafetyMiddleware(),
            TodoListMiddleware(),
            SummarizationMiddleware(model=self._llm, trigger=("tokens", 3000)),
        ]
        # PromptCaching só faz sentido com Anthropic.
        if self._config.provider == "anthropic":
            from marvin_hue.chat.middleware.caching import prompt_caching_middleware
            stack.append(prompt_caching_middleware())
        # HITL opcional para tools de mutação ampla (aprovação humana).
        if self._config.require_approval:
            from langchain.agents.middleware import HumanInTheLoopMiddleware
            stack.append(HumanInTheLoopMiddleware(
                interrupt_on=dict(HITL_INTERRUPT_ON),
                description_prefix=HITL_DESCRIPTION_PREFIX,
            ))
        return stack

    def _create_agent(self) -> CompiledStateGraph:
        """Cria o orquestrador com create_agent + middleware + tool `task`.

        Returns:
            Grafo compilado do agente
        """
        from marvin_hue.chat.subagents.definitions import build_subagents
        from marvin_hue.chat.subagents.task import build_task_tool

        tools = build_all_tools(
            self._controller, self._manager, room_index=self._room_index,
            services=self._services,
        )
        middleware = self._build_middleware()  # cria self._hue_context (cache compartilhado)
        subagents = build_subagents(
            self._llm, self._controller, self._manager,
            context_middleware=self._hue_context,  # MESMA instância -> mesmo cache TTL
            room_index=self._room_index,
            services=self._services,
            require_approval=self._config.require_approval,
            prompt_caching=self._config.provider == "anthropic",
        )
        task_tool = build_task_tool(subagents)
        return create_agent(
            model=self._llm,
            tools=[*tools, task_tool],
            system_prompt=self._config.system_prompt,
            middleware=middleware,
            checkpointer=self._checkpointer,
        )

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
                    text = _message_text(message.content)
                    if text:
                        return text

        return "Operação concluída."

    @staticmethod
    def _config_for(session_id: str) -> RunnableConfig:
        """thread_id isola o histórico por sessão; recursion_limit limita o turno."""
        return {
            "configurable": {"thread_id": session_id},
            "recursion_limit": AGENT_RECURSION_LIMIT,
        }

    def _touch_session(self, session_id: str) -> list[str]:
        """Marca a sessão como acessada e RETORNA as threads a despejar (LRU).

        NÃO deleta aqui: o caller (sync ou async) decide como apagar a thread no
        checkpointer — `delete_thread` síncrono quebra sob `AsyncSqliteSaver`
        chamado do event loop. Sync deleta direto; async aguarda `adelete_thread`.
        """
        self._session_last_access[session_id] = time.monotonic()
        evicted: list[str] = []
        while len(self._session_last_access) > self._max_sessions:
            oldest = min(
                self._session_last_access,
                key=self._session_last_access.__getitem__,
            )
            del self._session_last_access[oldest]
            evicted.append(oldest)
        return evicted

    async def _adelete_thread(self, session_id: str) -> None:
        """Apaga a thread de forma async-safe (await adelete_thread se houver)."""
        adelete = getattr(self._checkpointer, "adelete_thread", None)
        if adelete is not None:
            await adelete(session_id)
        else:
            self._checkpointer.delete_thread(session_id)

    def _outcome(self, result: dict) -> "str | ApprovalRequired":
        """Texto final do turno, ou ApprovalRequired se o grafo parou num HITL."""
        pending = approval_from_interrupts(result.get("__interrupt__"))
        if pending is not None:
            return pending
        return self._extract_response(result)

    def _stream_item(self, chunk: dict) -> "str | ApprovalRequired | None":
        """Um chunk ``stream_mode="values"`` → texto visível, interrupt ou nada."""
        pending = approval_from_interrupts(chunk.get("__interrupt__"))
        if pending is not None:
            return pending
        messages = chunk.get("messages", [])
        if messages:
            last = messages[-1]
            if isinstance(last, AIMessage) and last.content and not last.tool_calls:
                text = _message_text(last.content)
                if text:
                    return text
        return None

    async def _aevict(self, session_id: str) -> None:
        for tid in self._touch_session(session_id):
            await self._adelete_thread(tid)

    def _evict(self, session_id: str) -> None:
        for tid in self._touch_session(session_id):
            self._checkpointer.delete_thread(tid)

    async def _apending_interrupts(self, session_id: str) -> tuple:
        state = await self._agent.aget_state(self._config_for(session_id))
        return tuple(getattr(state, "interrupts", ()) or ())

    def _pending_interrupts(self, session_id: str) -> tuple:
        state = self._agent.get_state(self._config_for(session_id))
        return tuple(getattr(state, "interrupts", ()) or ())

    async def apending(self, session_id: str = "default") -> Optional[ApprovalRequired]:
        """Aprovações pendentes da sessão (ex.: a página recarregou), ou None."""
        return approval_from_interrupts(await self._apending_interrupts(session_id))

    def _stale_calls(self, state: Any) -> list[dict[str, Any]]:
        values = getattr(state, "values", None) or {}
        return dangling_tool_calls(values.get("messages"))

    async def _abefore_turn(self, session_id: str) -> Optional[ApprovalRequired]:
        """Prepara a thread para uma mensagem nova (async).

        - Flag ligada + aprovação pendente → devolve o pedido (a mensagem não
          é processada: uma tool call sem ToolMessage quebraria a thread nos
          provedores reais).
        - Flag desligada + tool calls órfãs (pendências de quando a flag
          estava ligada, ex.: SQLite após restart) → fecha cada uma com uma
          ToolMessage de cancelamento SEM executar a tool.
        """
        config = self._config_for(session_id)
        state = await self._agent.aget_state(config)
        if self._config.require_approval:
            return approval_from_interrupts(getattr(state, "interrupts", None))
        stale = self._stale_calls(state)
        if stale:
            await self._agent.aupdate_state(
                config, {"messages": cancellation_messages(stale)}, as_node="tools"
            )
        return None

    def _before_turn(self, session_id: str) -> Optional[ApprovalRequired]:
        """Versão síncrona de ``_abefore_turn`` (CLI / InMemorySaver)."""
        config = self._config_for(session_id)
        state = self._agent.get_state(config)
        if self._config.require_approval:
            return approval_from_interrupts(getattr(state, "interrupts", None))
        stale = self._stale_calls(state)
        if stale:
            self._agent.update_state(
                config, {"messages": cancellation_messages(stale)}, as_node="tools"
            )
        return None

    def invoke(self, message: str, session_id: str = "default") -> "str | ApprovalRequired":
        """Processa uma mensagem do usuário.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer). É o ÚNICO
                mecanismo de isolamento de histórico — clientes distintos DEVEM
                enviar ids distintos e estáveis.

        Returns:
            Resposta do agente, ou ``ApprovalRequired`` quando o turno parou
            pedindo aprovação (só com ``require_approval``). Se já houver
            aprovação pendente, a mensagem NÃO é processada e o pedido
            pendente volta (ver ``_abefore_turn``).
        """
        self._evict(session_id)
        pending = self._before_turn(session_id)
        if pending is not None:
            return pending
        result = self._agent.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=self._config_for(session_id),
        )
        return self._outcome(result)

    async def ainvoke(
        self, message: str, session_id: str = "default"
    ) -> "str | ApprovalRequired":
        """Processa uma mensagem de forma assíncrona.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer).

        Returns:
            Resposta do agente, ou ``ApprovalRequired`` (ver ``invoke``).
        """
        async with session_lock(session_id):
            await self._aevict(session_id)
            pending = await self._abefore_turn(session_id)
            if pending is not None:
                return pending
            result = await self._agent.ainvoke(
                {"messages": [HumanMessage(content=message)]},
                config=self._config_for(session_id),
            )
            return self._outcome(result)

    async def aresume(
        self, session_id: str, decisions: list[dict[str, Any]]
    ) -> "str | ApprovalRequired":
        """Retoma o turno interrompido com as decisões humanas.

        Args:
            session_id: Id da sessão (thread_id) que está aguardando.
            decisions: Uma decisão por pedido pendente, cada uma com o ``id``
                do pedido (``ApprovalRequest.id``): ``{"id", "type":
                "approve"}`` ou ``{"id", "type": "reject", "message"?}``.

        Returns:
            Resposta final, ou outro ``ApprovalRequired`` (ex.: o modelo ou o
            subagent pediu uma segunda aprovação).

        Raises:
            NoPendingApprovalError: nada pendente (já retomado, limpo ou
                despejado pelo LRU).
            InvalidDecisionError: id ausente/repetido/desconhecido ou tipo de
                decisão não permitido.

        A tool aprovada roda pelo caminho normal do grafo: schema Pydantic e
        EyeSafetyMiddleware revalidam os args — aprovar não contorna nada.
        """
        async with session_lock(session_id):
            await self._aevict(session_id)
            resume = build_resume_map(
                await self._apending_interrupts(session_id), decisions
            )
            result = await self._agent.ainvoke(
                Command(resume=resume), config=self._config_for(session_id)
            )
            return self._outcome(result)

    def stream(
        self, message: str, session_id: str = "default"
    ) -> "Iterator[str | ApprovalRequired]":
        """Processa uma mensagem com streaming.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer).

        Yields:
            Chunks da resposta; um ``ApprovalRequired`` se o turno parar num HITL.
        """
        self._evict(session_id)
        pending = self._before_turn(session_id)
        if pending is not None:
            yield pending
            return
        for chunk in self._agent.stream(
            {"messages": [HumanMessage(content=message)]},
            config=self._config_for(session_id),
            stream_mode="values",
        ):
            item = self._stream_item(chunk)
            if item is not None:
                yield item
        # NÃO re-invocar: o checkpointer já persistiu o histórico (corrige bug #1).

    async def astream(
        self, message: str, session_id: str = "default"
    ) -> "AsyncIterator[str | ApprovalRequired]":
        """Processa uma mensagem com streaming assíncrono.

        Args:
            message: Mensagem do usuário
            session_id: Id da sessão (thread_id do checkpointer).

        Yields:
            Chunks da resposta; um ``ApprovalRequired`` se o turno parar num HITL.
        """
        async with session_lock(session_id):
            await self._aevict(session_id)
            pending = await self._abefore_turn(session_id)
            if pending is not None:
                yield pending
                return
            async for chunk in self._agent.astream(
                {"messages": [HumanMessage(content=message)]},
                config=self._config_for(session_id),
                stream_mode="values",
            ):
                item = self._stream_item(chunk)
                if item is not None:
                    yield item

    def clear_history(self, session_id: str = "default") -> None:
        """Limpa o histórico de uma sessão (caminho SÍNCRONO — CLI/InMemory).

        Para o caminho async (FastAPI) use `aclear_history`: `delete_thread`
        síncrono quebra sob `AsyncSqliteSaver` chamado do event loop.
        """
        self._checkpointer.delete_thread(session_id)
        self._session_last_access.pop(session_id, None)

    async def aclear_history(self, session_id: str = "default") -> None:
        """Limpa o histórico de uma sessão (caminho ASYNC — rotas/WS).

        Pega o lock da sessão: um clear no meio de um resume esperaria o
        turno terminar em vez de apagar a thread por baixo dele.
        """
        async with session_lock(session_id):
            await self._adelete_thread(session_id)
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
        self._services: Optional[ChatServices] = None

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

    def with_services(self, services: ChatServices) -> "HueLightAgentBuilder":
        """Define os providers dos serviços do app usados pelas tools.

        Args:
            services: Container ChatServices

        Returns:
            Self para encadeamento
        """
        self._services = services
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
            controller=self._controller, manager=self._manager, config=self._config,
            services=self._services,
        )


def create_hue_agent(
    controller: HueController,
    manager: LightSetupsManager,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    *,
    checkpointer: Optional[Any] = None,
    room_index: Optional[dict[str, list[str]]] = None,
    services: Optional[ChatServices] = None,
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
        checkpointer: Checkpointer LangGraph opcional
        room_index: Snapshot sala → lâmpadas do registry (opcional)
        services: Providers dos serviços do app para as tools (opcional)
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

    return HueLightAgent(
        controller=controller,
        manager=manager,
        config=config,
        checkpointer=checkpointer,
        room_index=room_index,
        services=services,
    )
