"""HITL (P9): tools que mudam estado de forma ampla/persistente.

Com ``AgentConfig.require_approval`` (padrão: desligado; env
``CHAT_REQUIRE_APPROVAL``), o orquestrador e os subagents pedem aprovação
humana antes delas. Mudanças pontuais de lâmpada (set_light_color,
set_brightness, turn_*, set_color_temperature) ficam fora.

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
  pode divergir: ordenamos por id nos dois caminhos e aceitamos ``id`` em
  cada decisão para o mapeamento explícito.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_APPROVE_REJECT = {"allowed_decisions": ["approve", "reject"]}
_APPROVE_EDIT_REJECT = {"allowed_decisions": ["approve", "edit", "reject"]}

HITL_INTERRUPT_ON: dict[str, dict[str, list[str]]] = {
    "apply_config": _APPROVE_REJECT,
    "save_current_config": _APPROVE_EDIT_REJECT,
    "create_config": _APPROVE_EDIT_REJECT,
    "apply_config_to_group": _APPROVE_REJECT,
    "create_schedule": _APPROVE_REJECT,
    "set_schedule_enabled": _APPROVE_REJECT,
    "start_mirror": _APPROVE_REJECT,
    "stop_mirror": _APPROVE_REJECT,
    "undo_last_scene": _APPROVE_REJECT,
}

# Texto mostrado só ao humano (vai no payload do interrupt, nunca ao modelo).
HITL_DESCRIPTION_PREFIX = "Esta ação precisa da sua aprovação"

# Decisões aceitas pela UI/API. "edit" fica de fora de propósito: o middleware
# monta o novo ToolCall com o NOME vindo do cliente, o que permitiria trocar a
# tool aprovada por outra. "respond" não faz sentido para tools de mutação.
SUPPORTED_DECISIONS: frozenset[str] = frozenset({"approve", "reject"})

# A mensagem de rejeição chega ao modelo como ToolMessage: limite o tamanho.
MAX_REJECT_MESSAGE_CHARS = 500


def interrupt_on_for(tool_names: Iterable[str]) -> dict[str, dict[str, list[str]]]:
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

    type: str = "approval_required"

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
    iid, value = _interrupt_parts(intr)
    actions = value.get("action_requests") or []
    configs = value.get("review_configs") or []
    out: list[ApprovalRequest] = []
    for idx, action in enumerate(actions):
        cfg = configs[idx] if idx < len(configs) else {}
        allowed = tuple(
            d for d in cfg.get("allowed_decisions", ()) if d in SUPPORTED_DECISIONS
        )
        args = action.get("args")
        out.append(
            ApprovalRequest(
                id=f"{iid}:{idx}",
                tool=str(action.get("name", "")),
                args=dict(args) if isinstance(args, Mapping) else {},
                description=str(action.get("description", "")),
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

    Cada decisão pode trazer o ``id`` do pedido (``ApprovalRequest.id``); se
    TODAS trazem, o casamento é por id, senão pela ordem de
    ``approval_from_interrupts``. Falha fechado ANTES de retomar: com
    contagem/tipo errados o middleware levantaria ValueError no meio do grafo.
    """
    if not interrupts:
        raise NoPendingApprovalError("Nenhuma aprovação pendente nesta sessão.")
    grouped: list[tuple[str, list[ApprovalRequest]]] = [
        (_interrupt_parts(intr)[0], _requests_of(intr)) for intr in _ordered(interrupts)
    ]
    total = sum(len(reqs) for _, reqs in grouped)
    if total == 0:
        raise NoPendingApprovalError("Nenhuma aprovação pendente nesta sessão.")
    if len(decisions) != total:
        raise InvalidDecisionError(
            f"Esperadas {total} decisões, recebidas {len(decisions)}."
        )
    if all(d.get("id") for d in decisions):
        by_id = {str(d["id"]): d for d in decisions}
        expected = [req.id for _, reqs in grouped for req in reqs]
        if len(by_id) != len(decisions) or set(by_id) != set(expected):
            raise InvalidDecisionError("Os ids das decisões não batem com os pedidos pendentes.")
        decisions = [by_id[rid] for rid in expected]
    resume: dict[str, dict[str, list[dict[str, Any]]]] = {}
    cursor = 0
    for iid, reqs in grouped:
        normalized = [
            _normalize(decisions[cursor + j], req) for j, req in enumerate(reqs)
        ]
        cursor += len(reqs)
        resume[iid] = {"decisions": normalized}
    return resume
