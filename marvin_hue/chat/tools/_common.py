"""Peças comuns das tools do chat: resolução por nome e tools de serviço async.

Tools de serviço (P7): o trabalho real fica no ``coroutine`` (``ainvoke`` /
``astream`` — chat REST e WebSocket). Os serviços com aiosqlite (favoritos,
histórico, grupos, agendamentos; espelhamento e saúde passam por eles) ficam
presos ao event loop do FastAPI, então o ``func`` síncrono nunca roda a
coroutine em outro loop: devolve uma mensagem ("disponível apenas no app").
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from marvin_hue.basics import LightSetupsManager
from marvin_hue.logging_config import get_logger

T = TypeVar("T")

logger = get_logger("chat.tools")

# Texto livre que volta ao contexto do modelo: uma linha só (sem \r/\n), para
# não abrir espaço a instruções injetadas em linhas extras.
SINGLE_LINE = r"^[^\r\n]*$"


def pct_to_hue(pct: int) -> int:
    """Brilho 0-100% → escala Hue 0-254 (floor, como o controller)."""
    return max(0, min(254, int((max(0, min(100, pct)) / 100) * 254)))


def hue_to_pct(value: int) -> int:
    """Escala Hue 0-254 → 0-100% (arredondado, só para exibição)."""
    return int(round(max(0, min(254, value)) / 254 * 100))


def unexpected_error(action: str, exc: BaseException, *, verb: str = "Erro inesperado ao") -> str:
    """Loga a exceção no servidor e devolve mensagem genérica ao modelo.

    Detalhes (paths, SQL, stack) ficam fora do contexto do LLM; erros de
    domínio continuam com mensagem própria em cada tool.
    """
    logger.opt(exception=exc).warning(f"Chat tool falhou ao {action}: {exc!r}")
    return f"{verb} {action}. Detalhes no log do servidor."


class NoArgs(BaseModel):
    """Schema vazio para tools sem argumentos."""


def unavailable(label: str) -> str:
    return f"{label}: indisponível no momento (serviço não inicializado)."


def app_only(label: str) -> str:
    return (
        f"{label}: só funciona pelo chat do servidor (web/API), "
        "disponível apenas no app."
    )


def service_tool(
    *,
    name: str,
    description: str,
    coroutine: Callable[..., Awaitable[str]],
    label: str,
    is_available: Callable[[], bool],
    args_schema: type[BaseModel] = NoArgs,
) -> StructuredTool:
    """StructuredTool async com fallback síncrono que não toca o serviço."""

    def _sync(**_kwargs: Any) -> str:
        return app_only(label) if is_available() else unavailable(label)

    return StructuredTool.from_function(
        func=_sync,
        coroutine=coroutine,
        name=name,
        description=description,
        args_schema=args_schema,
    )


def resolve_scene(
    manager: LightSetupsManager, name: str
) -> tuple[str | None, str | None]:
    """(nome canônico, None) ou (None, mensagem). Exato, depois sem maiúsculas."""
    if manager.get_config(name) is not None:
        return name, None
    key = name.strip().casefold()
    matches = sorted({c.name for c in manager.configs if c.name.casefold() == key})
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, (
            f"Nome '{name}' é ambíguo: {', '.join(matches)}. Use o nome exato."
        )
    return None, (
        f"A cena '{name}' não existe. Use list_configs para ver os nomes disponíveis."
    )


def resolve_by_name(
    items: Sequence[T],
    query: str,
    *,
    kind: str,
    id_of: Callable[[T], str],
    name_of: Callable[[T], str],
) -> tuple[T | None, str | None]:
    """Acha um item pelo id ou pelo nome sem diferenciar maiúsculas (P3).

    Nenhum → mensagem com a lista; mais de um → pede para desambiguar pelo id.
    """
    q = (query or "").strip()
    for item in items:
        if id_of(item) == q:
            return item, None
    key = q.casefold()
    matches = [item for item in items if name_of(item).casefold() == key]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        options = ", ".join(f"{name_of(i)} (id {id_of(i)})" for i in matches)
        return None, f"Nome '{q}' é ambíguo para {kind}: {options}. Informe o id."
    available = ", ".join(name_of(i) for i in items) or "nenhum cadastrado"
    return None, f"{kind.capitalize()} '{q}' não encontrado. Disponíveis: {available}."
