"""HITL (P9): aprovação humana antes das tools persistentes ou de tomada de controle.

Com ``AgentConfig.require_approval`` (padrão: desligado; env
``CHAT_REQUIRE_APPROVAL``), o orquestrador e os subagents pedem aprovação
humana antes das tools de ``HITL_INTERRUPT_ON``.

Política (evita fadiga de aprovação): só pede aprovação o que GRAVA algo que
fica (catálogo de cenas, agendamentos que disparam sozinhos depois) ou TOMA o
controle contínuo das lâmpadas (espelhamento):

- ``create_config``, ``save_current_config``: gravam cena nova em
  ``.res/setups.json``.
- ``create_schedule``, ``set_schedule_enabled``: criam/ligam ações futuras
  sem ninguém olhando.
- ``start_mirror``: passa a escrever nas lâmpadas a ~25 FPS até alguém parar.

Tools que mudam estado e ficam FORA de propósito (reversíveis na hora, pelo
próprio chat, pela tela Controle ou por ``undo_last_scene``):
``set_light_color``, ``set_brightness``, ``turn_on_lights``,
``turn_off_lights``, ``set_color_temperature``, ``set_room_power``,
``set_room_brightness``, ``add_favorite``, ``remove_favorite``,
``apply_config``, ``apply_config_to_group`` (o snapshot "before apply"
permite desfazer), ``stop_mirror`` (só devolve o controle) e
``undo_last_scene`` (é o próprio desfazer). A segurança ocular não depende do
HITL: é invariante de código (EyeSafetyMiddleware + chokepoint do controller).

Fluxo (langchain 1.3 / langgraph 1.2, conferido na prática):

- ``HumanInTheLoopMiddleware.after_model`` chama ``interrupt(HITLRequest)``;
  o grafo para e o resultado do ``ainvoke`` traz ``__interrupt__``: uma lista
  de ``Interrupt(value={"action_requests": [...], "review_configs": [...]},
  id=...)``. ``aget_state(config).interrupts`` devolve o mesmo.
- Interrupção dentro de um subagent (tool ``task``) SOBE até o orquestrador:
  o subagent não tem checkpointer próprio e herda o do pai pelo config. Na
  retomada ele continua do próprio nó HITL (não reexecuta o modelo), e as
  tools irmãs já concluídas no mesmo passo não rodam de novo.
- Várias ``task`` em paralelo geram várias interrupções pendentes; a retomada
  tem de ser endereçada por id: ``Command(resume={interrupt_id:
  {"decisions": [...]}})``. Usamos sempre essa forma (vale também para uma).
- A ORDEM das interrupções em ``__interrupt__`` e em ``state.interrupts``
  pode divergir. Por isso cada decisão leva OBRIGATORIAMENTE o ``id`` do
  pedido; não há casamento por posição.
- Um grafo montado SEM o middleware (flag desligada) não enxerga as
  interrupções antigas do checkpointer: sobra uma AIMessage com tool_calls
  sem ToolMessage. ``dangling_tool_calls`` acha essas chamadas para o agente
  cancelá-las antes do próximo turno.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from langchain_core.messages import AIMessage, ToolMessage

APPROVAL_REQUIRED = "approval_required"

# A descrição vai só ao humano (payload do interrupt), nunca ao modelo.
HITL_INTERRUPT_ON: dict[str, dict[str, Any]] = {
    "create_config": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "Gravar uma cena nova no catálogo de cenas.",
    },
    "save_current_config": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "Gravar o estado atual das lâmpadas como uma cena nova.",
    },
    "create_schedule": {
        "allowed_decisions": ["approve", "reject"],
        "description": "Criar um agendamento que vai rodar sozinho no horário marcado.",
    },
    "set_schedule_enabled": {
        "allowed_decisions": ["approve", "reject"],
        "description": "Ativar ou desativar um agendamento.",
    },
    "start_mirror": {
        "allowed_decisions": ["approve", "reject"],
        "description": "Iniciar o espelhamento: as lâmpadas passam a seguir a tela ou a música.",
    },
}

# Prefixo usado só se uma tool de HITL_INTERRUPT_ON ficar sem "description".
HITL_DESCRIPTION_PREFIX = "Esta ação precisa da sua aprovação"

# Decisões aceitas pela UI/API. "edit" fica de fora de propósito: o middleware
# monta o novo ToolCall com o NOME vindo do cliente, o que permitiria trocar a
# tool aprovada por outra. "respond" não faz sentido para tools de mutação.
SUPPORTED_DECISIONS: frozenset[str] = frozenset({"approve", "reject"})

# A mensagem de rejeição chega ao modelo como ToolMessage: limite o tamanho.
MAX_REJECT_MESSAGE_CHARS = 500

# ToolMessage sintética para chamadas pendentes canceladas com a flag desligada.
CANCELLED_MESSAGE = "Aprovação desativada; ação cancelada."


def interrupt_on_for(tool_names: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Subconjunto de ``HITL_INTERRUPT_ON`` para as tools dadas."""
    names = set(tool_names)
    return {k: dict(v) for k, v in HITL_INTERRUPT_ON.items() if k in names}


class ApprovalError(ValueError):
    """Base dos erros de decisão HITL."""


class NoPendingApprovalError(ApprovalError):
    """Não há aprovação pendente na sessão (já retomada, limpa ou despejada)."""


class InvalidDecisionError(ApprovalError):
    """Decisões não batem com as aprovações pendentes."""


@dataclass(frozen=True)
class ApprovalRequest:
    """Uma tool call aguardando decisão humana."""

    id: str
    tool: str
    args: dict[str, Any]
    description: str
    allowed_decisions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "args": dict(self.args),
            "description": self.description,
            "allowed_decisions": list(self.allowed_decisions),
        }


@dataclass(frozen=True)
class ApprovalRequired:
    """Resultado de um turno interrompido: o agente espera aprovação."""

    requests: tuple[ApprovalRequest, ...]

    type: ClassVar[str] = APPROVAL_REQUIRED

    def to_list(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.requests]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "requests": self.to_list()}


def _ordered(interrupts: Sequence[Any]) -> list[Any]:
    return sorted(interrupts, key=lambda i: str(getattr(i, "id", "")))


def _interrupt_parts(intr: Any) -> tuple[str, Mapping[str, Any]]:
    value = getattr(intr, "value", None)
    return str(getattr(intr, "id", "")), value if isinstance(value, Mapping) else {}


def _requests_of(intr: Any) -> list[ApprovalRequest]:
    """Um pedido por action_request, alinhado por índice com o middleware.

    Itens malformados (None, sem config) viram pedidos sem decisão permitida
    em vez de sumirem: o middleware exige uma decisão por action_request.
    """
    iid, value = _interrupt_parts(intr)
    actions = value.get("action_requests") or []
    configs = value.get("review_configs") or []
    out: list[ApprovalRequest] = []
    for idx, raw_action in enumerate(actions):
        action = raw_action if isinstance(raw_action, Mapping) else {}
        raw_cfg = configs[idx] if idx < len(configs) else None
        cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
        allowed = tuple(
            d for d in (cfg.get("allowed_decisions") or ()) if d in SUPPORTED_DECISIONS
        )
        args = action.get("args")
        out.append(
            ApprovalRequest(
                id=f"{iid}:{idx}",
                tool=str(action.get("name") or ""),
                args=dict(args) if isinstance(args, Mapping) else {},
                description=str(action.get("description") or ""),
                allowed_decisions=allowed,
            )
        )
    return out


def approval_from_interrupts(interrupts: Sequence[Any] | None) -> ApprovalRequired | None:
    """Converte os ``Interrupt`` do LangGraph no payload da API (ou None)."""
    if not interrupts:
        return None
    requests = [r for intr in _ordered(interrupts) for r in _requests_of(intr)]
    if not requests:
        return None
    return ApprovalRequired(requests=tuple(requests))


def _normalize(decision: Mapping[str, Any], request: ApprovalRequest) -> dict[str, Any]:
    kind = decision.get("type")
    if kind not in SUPPORTED_DECISIONS or kind not in request.allowed_decisions:
        raise InvalidDecisionError(
            f"Decisão {kind!r} não permitida para {request.tool} "
            f"(permitidas: {', '.join(request.allowed_decisions) or 'nenhuma'})."
        )
    if kind == "approve":
        return {"type": "approve"}
    message = decision.get("message")
    if message is None or not str(message).strip():
        return {"type": "reject"}
    text = str(message).strip()[:MAX_REJECT_MESSAGE_CHARS]
    return {
        "type": "reject",
        "message": (
            f"O usuário rejeitou `{request.tool}`; a ferramenta não foi executada. "
            f"Motivo informado: {text}"
        ),
    }


def build_resume_map(
    interrupts: Sequence[Any] | None, decisions: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Valida as decisões e agrupa por interrupt id.

    Cada decisão TEM de trazer o ``id`` do pedido (``ApprovalRequest.id``) e
    os ids têm de cobrir exatamente os pedidos pendentes: id ausente,
    repetido, desconhecido ou de um conjunto antigo → ``InvalidDecisionError``.
    Falha fechado ANTES de retomar: o middleware levantaria ValueError no
    meio do grafo.
    """
    if not interrupts:
        raise NoPendingApprovalError("Nenhuma aprovação pendente nesta sessão.")
    grouped: list[tuple[str, list[ApprovalRequest]]] = [
        (_interrupt_parts(intr)[0], _requests_of(intr)) for intr in _ordered(interrupts)
    ]
    expected = [req.id for _, reqs in grouped for req in reqs]
    if not expected:
        raise NoPendingApprovalError("Nenhuma aprovação pendente nesta sessão.")

    ids = [str(d.get("id") or "") for d in decisions]
    if not all(ids):
        raise InvalidDecisionError("Toda decisão precisa do id do pedido.")
    if len(set(ids)) != len(ids):
        raise InvalidDecisionError("Há decisões repetidas para o mesmo pedido.")
    if set(ids) != set(expected):
        raise InvalidDecisionError(
            "Os ids das decisões não batem com os pedidos pendentes "
            f"(esperados {len(expected)}, recebidos {len(ids)})."
        )
    by_id = dict(zip(ids, decisions))

    return {
        iid: {"decisions": [_normalize(by_id[req.id], req) for req in reqs]}
        for iid, reqs in grouped
    }


def dangling_tool_calls(messages: Sequence[Any] | None) -> list[dict[str, Any]]:
    """Tool calls da última AIMessage que ficaram sem ToolMessage."""
    answered: set[str] = set()
    for msg in reversed(list(messages or [])):
        if isinstance(msg, ToolMessage):
            answered.add(str(msg.tool_call_id))
            continue
        if isinstance(msg, AIMessage):
            return [tc for tc in (msg.tool_calls or []) if str(tc.get("id")) not in answered]
        return []
    return []


def cancellation_messages(tool_calls: Sequence[Mapping[str, Any]]) -> list[ToolMessage]:
    """ToolMessages de erro que fecham chamadas pendentes sem executá-las."""
    return [
        ToolMessage(
            content=CANCELLED_MESSAGE,
            name=str(tc.get("name") or ""),
            tool_call_id=str(tc.get("id")),
            status="error",
        )
        for tc in tool_calls
    ]
