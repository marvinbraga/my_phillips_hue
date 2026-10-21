"""Tools de favoritos do chat (list_favorites / add_favorite / remove_favorite).

Usa um serviço fake (sem SQLite) injetado via ``ChatServices.favorites_provider``.
"""
from __future__ import annotations

import pytest

from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.services.scene_favorites import FavoriteConfigNotFoundError


FAVORITE_TOOLS = {"list_favorites", "add_favorite", "remove_favorite"}


class _FakeFavorites:
    """Imita SceneFavoritesService (async) sobre um set em memória."""

    def __init__(self, manager, initial: set[str] | None = None) -> None:
        self._manager = manager
        self.names: set[str] = set(initial or ())
        self.add_calls: list[str] = []
        self.remove_calls: list[str] = []

    async def list_existing(self) -> list[str]:
        return sorted(n for n in self.names if self._manager.get_config(n) is not None)

    async def add(self, name: str) -> None:
        self.add_calls.append(name)
        if self._manager.get_config(name) is None:
            raise FavoriteConfigNotFoundError(f"Configuração '{name}' não encontrada")
        self.names.add(name)

    async def remove(self, name: str) -> None:
        self.remove_calls.append(name)
        self.names.discard(name)


@pytest.fixture
def manager(fake_manager):
    fake_manager.configs.append(
        LightConfig(
            name="Por_do_Sol",
            settings=[LightSetting("Lâmpada 1", Color(255, 120, 0, 200))],
            description="Laranja quente",
        )
    )
    return fake_manager


def _tools(controller, manager, provider):
    from marvin_hue.chat.services import ChatServices
    from marvin_hue.chat.tools import build_all_tools

    return {
        t.name: t
        for t in build_all_tools(
            controller, manager, services=ChatServices(favorites_provider=provider)
        )
    }


def test_build_all_tools_exposes_favorite_tools(fake_controller, manager):
    names = set(_tools(fake_controller, manager, lambda: None))
    assert FAVORITE_TOOLS <= names


def test_favorite_tools_have_async_path(fake_controller, manager):
    tools = _tools(fake_controller, manager, lambda: None)
    for name in FAVORITE_TOOLS:
        assert tools[name].coroutine is not None, name
        assert tools[name].func is not None, name


async def test_list_favorites_empty(fake_controller, manager):
    svc = _FakeFavorites(manager)
    out = await _tools(fake_controller, manager, lambda: svc)["list_favorites"].ainvoke({})
    assert "Nenhuma" in out


async def test_list_favorites_lists_names(fake_controller, manager):
    svc = _FakeFavorites(manager, {"noite_relaxante", "Por_do_Sol"})
    out = await _tools(fake_controller, manager, lambda: svc)["list_favorites"].ainvoke({})
    assert "noite_relaxante" in out and "Por_do_Sol" in out


async def test_add_favorite_marks_scene(fake_controller, manager):
    svc = _FakeFavorites(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["add_favorite"]
    out = await tool.ainvoke({"config_name": "noite_relaxante"})
    assert svc.names == {"noite_relaxante"}
    assert "favorita" in out and "noite_relaxante" in out
    assert "Controle" in out


async def test_add_favorite_idempotent(fake_controller, manager):
    svc = _FakeFavorites(manager, {"noite_relaxante"})
    tool = _tools(fake_controller, manager, lambda: svc)["add_favorite"]
    out = await tool.ainvoke({"config_name": "noite_relaxante"})
    assert "já era favorita" in out
    assert svc.add_calls == []


async def test_add_favorite_unknown_scene(fake_controller, manager):
    svc = _FakeFavorites(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["add_favorite"]
    out = await tool.ainvoke({"config_name": "nao_existe"})
    assert "não existe" in out and "list_configs" in out
    assert svc.add_calls == [] and svc.names == set()


async def test_add_favorite_case_insensitive_unique_match(fake_controller, manager):
    svc = _FakeFavorites(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["add_favorite"]
    out = await tool.ainvoke({"config_name": "por_do_sol"})
    assert svc.names == {"Por_do_Sol"}
    assert "Por_do_Sol" in out


async def test_add_favorite_ambiguous_case_insensitive(fake_controller, manager):
    manager.configs.append(
        LightConfig(
            name="POR_DO_SOL",
            settings=[LightSetting("Lâmpada 1", Color(255, 0, 0, 200))],
            description="dup",
        )
    )
    svc = _FakeFavorites(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["add_favorite"]
    out = await tool.ainvoke({"config_name": "por_do_sol"})
    assert svc.add_calls == []
    assert "Por_do_Sol" in out and "POR_DO_SOL" in out


async def test_add_favorite_service_race_not_found(fake_controller, manager):
    """Manager recarregado entre a checagem e o add: service levanta, tool não."""

    class _Racy(_FakeFavorites):
        async def add(self, name: str) -> None:
            raise FavoriteConfigNotFoundError(name)

    svc = _Racy(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["add_favorite"]
    out = await tool.ainvoke({"config_name": "noite_relaxante"})
    assert "não existe" in out


async def test_remove_favorite(fake_controller, manager):
    svc = _FakeFavorites(manager, {"noite_relaxante"})
    tool = _tools(fake_controller, manager, lambda: svc)["remove_favorite"]
    out = await tool.ainvoke({"config_name": "noite_relaxante"})
    assert svc.names == set()
    assert "removida" in out


async def test_remove_favorite_idempotent(fake_controller, manager):
    svc = _FakeFavorites(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["remove_favorite"]
    out = await tool.ainvoke({"config_name": "noite_relaxante"})
    assert "não era favorita" in out
    assert svc.remove_calls == []


async def test_remove_favorite_case_insensitive(fake_controller, manager):
    svc = _FakeFavorites(manager, {"Por_do_Sol"})
    tool = _tools(fake_controller, manager, lambda: svc)["remove_favorite"]
    await tool.ainvoke({"config_name": "POR_do_sol"})
    assert svc.remove_calls == ["Por_do_Sol"]
    assert svc.names == set()


async def test_remove_favorite_unknown_scene(fake_controller, manager):
    svc = _FakeFavorites(manager)
    tool = _tools(fake_controller, manager, lambda: svc)["remove_favorite"]
    out = await tool.ainvoke({"config_name": "nao_existe"})
    assert "não existe" in out and "list_configs" in out


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("list_favorites", {}),
        ("add_favorite", {"config_name": "noite_relaxante"}),
        ("remove_favorite", {"config_name": "noite_relaxante"}),
    ],
)
async def test_unavailable_service_fails_open(fake_controller, manager, name, args):
    tool = _tools(fake_controller, manager, lambda: None)[name]
    out = await tool.ainvoke(args)
    assert "indisponíve" in out


async def test_provider_raising_fails_open(fake_controller, manager):
    def boom():
        raise RuntimeError("SceneFavoritesService não inicializado")

    out = await _tools(fake_controller, manager, boom)["list_favorites"].ainvoke({})
    assert "indisponíve" in out


async def test_service_error_returns_message(fake_controller, manager):
    class _Broken(_FakeFavorites):
        async def list_existing(self) -> list[str]:
            raise OSError("disk I/O error")

    svc = _Broken(manager)
    out = await _tools(fake_controller, manager, lambda: svc)["list_favorites"].ainvoke({})
    assert "Erro" in out


def test_sync_path_does_not_touch_service(fake_controller, manager):
    """Sync invoke nunca roda o coroutine fora do loop do servidor."""
    svc = _FakeFavorites(manager)
    tools = _tools(fake_controller, manager, lambda: svc)
    out = tools["add_favorite"].invoke({"config_name": "noite_relaxante"})
    assert svc.add_calls == [] and svc.names == set()
    assert "servidor" in out


def test_sync_path_unavailable(fake_controller, manager):
    out = _tools(fake_controller, manager, lambda: None)["list_favorites"].invoke({})
    assert "indisponíve" in out


def test_default_provider_returns_none_when_unset(monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import default_favorites_provider

    monkeypatch.setattr(dependencies, "_scene_favorites_service", None)
    assert default_favorites_provider() is None


def test_default_provider_returns_registered_service(monkeypatch):
    from marvin_hue.api import dependencies
    from marvin_hue.chat.services import default_favorites_provider

    sentinel = object()
    monkeypatch.setattr(dependencies, "_scene_favorites_service", sentinel)
    assert default_favorites_provider() is sentinel


def test_config_librarian_has_favorite_tools():
    from marvin_hue.chat.subagents.definitions import CONFIG_LIBRARIAN_TOOLS

    assert FAVORITE_TOOLS <= set(CONFIG_LIBRARIAN_TOOLS)


def test_agent_threads_favorites_provider(
    fake_controller, fake_manager, monkeypatch, bindable_model_factory
):
    """create_hue_agent repassa o ChatServices (favoritos) ao orquestrador e
    aos subagents."""
    from marvin_hue.chat.agents import react_agent as ra
    from marvin_hue.chat.subagents import definitions as d

    seen: list[object] = []
    real_build = ra.build_all_tools

    def spy(*a, **k):
        seen.append(k["services"].favorites_provider)
        return real_build(*a, **k)

    monkeypatch.setattr(ra, "build_all_tools", spy)
    monkeypatch.setattr(d, "build_all_tools", spy)
    monkeypatch.setattr(ra.HueLightAgent, "_create_llm", lambda self: bindable_model_factory())

    def provider():
        return None

    from marvin_hue.chat.services import ChatServices

    ra.create_hue_agent(
        fake_controller, fake_manager, services=ChatServices(favorites_provider=provider)
    )
    assert seen and all(p is provider for p in seen)


def test_system_prompt_mentions_favorites():
    from marvin_hue.chat.agents.react_agent import SYSTEM_PROMPT

    assert "favorit" in SYSTEM_PROMPT.lower()


def test_configure_chat_wires_favorites_provider(fastapi_test_client, monkeypatch):
    """POST /api/chat/configure recria o agente com o provider de favoritos.

    create_hue_agent é substituído: nenhum LLM nem lâmpada real é tocado.
    """
    from marvin_hue.api import dependencies
    from marvin_hue.api.routes import chat as chat_routes
    from marvin_hue.chat.services import ChatServices
    from marvin_hue.chat.services import default_favorites_provider

    captured: dict = {}
    original_agent = dependencies._chat_agent

    def fake_create(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(chat_routes, "create_hue_agent", fake_create)
    resp = fastapi_test_client.post(
        "/api/chat/configure", json={"provider": "openai", "model": "gpt-4o-mini"}
    )
    dependencies._chat_agent = original_agent
    assert resp.status_code == 200, resp.text
    assert isinstance(captured["services"], ChatServices)
    assert captured["services"].favorites_provider is default_favorites_provider


async def test_add_favorite_through_compiled_graph_uses_async_path(
    fake_controller, manager, monkeypatch
):
    """Tool call do modelo atravessa o grafo REAL via ainvoke e usa o coroutine
    (não o func síncrono) — o favorito é gravado no serviço."""
    import marvin_hue.chat.agents.react_agent as ra
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, ToolMessage

    class _ToolCallingFake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    responses = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "add_favorite",
                "args": {"config_name": "noite_relaxante"},
                "id": "tc-fav",
            }],
        ),
        AIMessage(content="favoritada"),
    ]

    class _FakeProvider:
        model = _ToolCallingFake(responses=responses)

    monkeypatch.setattr(
        ra.LLMProviderFactory, "create", classmethod(lambda cls, **kw: _FakeProvider())
    )
    svc = _FakeFavorites(manager)
    from marvin_hue.chat.services import ChatServices

    agent = ra.create_hue_agent(
        controller=fake_controller,
        manager=manager,
        services=ChatServices(favorites_provider=lambda: svc),
    )

    await agent.ainvoke("marca noite_relaxante como favorita", session_id="fav")

    assert svc.names == {"noite_relaxante"}
    state = await agent._agent.aget_state(agent._config_for("fav"))
    tool_msgs = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs and "marcada como favorita" in str(tool_msgs[-1].content)
    assert "servidor" not in str(tool_msgs[-1].content)


async def test_add_and_remove_return_updated_list(fake_controller, manager):
    # Evita a leitura de estado antigo quando o modelo chama list_favorites
    # em paralelo no mesmo turno: add/remove já devolvem a lista atualizada.
    svc = _FakeFavorites(manager)
    tools = _tools(fake_controller, manager, lambda: svc)
    added = await tools["add_favorite"].ainvoke({"config_name": "noite_relaxante"})
    assert "Favoritas agora: noite_relaxante." in added
    removed = await tools["remove_favorite"].ainvoke({"config_name": "noite_relaxante"})
    assert "Favoritas agora: nenhuma." in removed
