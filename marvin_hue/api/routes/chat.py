"""
Chat Routes
Endpoints para interação com o agente de chat.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from marvin_hue.chat import create_hue_agent, HueLightAgent
from marvin_hue.chat.hitl import (
    ApprovalRequired,
    InvalidDecisionError,
    NoPendingApprovalError,
)
from marvin_hue.chat.services import ChatServices
from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.config import settings
from marvin_hue.api.dependencies import (
    get_chat_agent,
    get_chat_checkpointer,
    get_chat_unavailable_reason,
    get_hue_controller,
    get_manager,
    set_chat_agent,
)
from marvin_hue.api.models import (
    ChatMessageRequest,
    ChatClearRequest,
    ChatConfigRequest,
    ChatResumeRequest,
)
from marvin_hue.logging_config import get_logger

logger = get_logger("chat")

router = APIRouter(tags=["Chat"])

# Configurar templates
templates = Jinja2Templates(directory="web/templates")


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Página de chat com o agente Marvin."""
    return templates.TemplateResponse(request, "chat.html", {"active": "chat"})


def _turn_payload(result: Any, session_id: str) -> dict[str, Any]:
    """Resposta de um turno: texto final ou pedidos de aprovação (HITL)."""
    if isinstance(result, ApprovalRequired):
        return {
            "success": True,
            "approval_required": result.to_list(),
            "session_id": session_id,
        }
    return {"response": result, "success": True}


def _require_agent(chat_agent: HueLightAgent | None) -> HueLightAgent:
    if chat_agent is None:
        reason = get_chat_unavailable_reason()
        raise HTTPException(
            status_code=503,
            detail=reason
            or "Agente de chat não disponível. Verifique as configurações.",
        )
    return chat_agent


def _status_provider_model(chat_agent: HueLightAgent | None) -> tuple[str, str]:
    """Provider/model efetivos: config do agente vivo, senão settings."""
    if chat_agent is not None:
        live = getattr(chat_agent, "_config", None)
        provider = getattr(live, "provider", None)
        model = getattr(live, "model", None)
        if provider and model:
            return str(provider), str(model)
    return settings.chat_provider, settings.chat_model


@router.get("/api/chat/status")
async def chat_status(chat_agent: HueLightAgent | None = Depends(get_chat_agent)):
    """Retorna o status do agente de chat."""
    provider, model = _status_provider_model(chat_agent)
    if chat_agent is None:
        reason = get_chat_unavailable_reason()
        return {
            "available": False,
            "error": reason
            or "Agente de chat não inicializado. Verifique as chaves de API.",
            "provider": provider,
            "model": model,
        }

    return {
        "available": True,
        "provider": provider,
        "model": model,
    }


@router.post("/api/chat/message")
async def send_chat_message(
    request: ChatMessageRequest,
    chat_agent: HueLightAgent | None = Depends(get_chat_agent),
):
    """
    Envia uma mensagem para o agente e retorna a resposta.

    Args:
        request: Mensagem do usuário

    Returns:
        dict: ``{"response", "success"}`` ou, com CHAT_REQUIRE_APPROVAL, quando
        o agente para pedindo aprovação: ``{"approval_required": [...],
        "session_id", "success"}`` — retome com POST /api/chat/resume. Com
        aprovação já pendente a mensagem não é processada e os pedidos
        pendentes voltam.

    Raises:
        HTTPException: Se o agente não estiver disponível ou houver erro
    """
    chat_agent = _require_agent(chat_agent)

    # Validação adicional da mensagem
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia")

    try:
        result = await chat_agent.ainvoke(request.message, session_id=request.session_id)
        return _turn_payload(result, request.session_id)
    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao processar mensagem: {str(e)}"
        )


@router.post("/api/chat/resume")
async def resume_chat(
    request: ChatResumeRequest,
    chat_agent: HueLightAgent | None = Depends(get_chat_agent),
):
    """Retoma um turno que parou pedindo aprovação (HITL).

    ``decisions``: uma por pedido pendente, cada uma com o ``id`` do pedido
    (obrigatório; sem casamento por posição). 409 se não há nada pendente;
    400 se os ids não cobrem exatamente os pedidos ou o tipo não é permitido.
    """
    chat_agent = _require_agent(chat_agent)
    decisions = [d.model_dump(exclude_none=True) for d in request.decisions]
    try:
        result = await chat_agent.aresume(request.session_id, decisions)
    except NoPendingApprovalError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except InvalidDecisionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error resuming chat: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao retomar a conversa: {str(e)}"
        )
    return _turn_payload(result, request.session_id)


@router.get("/api/chat/pending")
async def pending_chat_approvals(
    session_id: str = Query(default="default", max_length=128),
    chat_agent: HueLightAgent | None = Depends(get_chat_agent),
):
    """Pedidos de aprovação pendentes da sessão (lista vazia se nenhum)."""
    chat_agent = _require_agent(chat_agent)
    pending = await chat_agent.apending(session_id)
    return {
        "session_id": session_id,
        "approval_required": pending.to_list() if pending is not None else [],
    }


@router.post("/api/chat/clear")
async def clear_chat_history(
    request: ChatClearRequest | None = None,
    chat_agent: HueLightAgent | None = Depends(get_chat_agent),
):
    """Limpa o histórico de conversação DA SESSÃO informada.

    NÃO limpa globalmente: o checkpointer é compartilhado, então um clear sem
    session_id apagaria o histórico de todas as sessões. O default 'default'
    existe só para retrocompatibilidade — o cliente DEVE enviar seu session_id.
    Body é opcional para retrocompatibilidade (clientes antigos sem body).
    """
    if chat_agent is None:
        reason = get_chat_unavailable_reason()
        raise HTTPException(
            status_code=503,
            detail=reason or "Agente de chat não disponível.",
        )

    session_id = request.session_id if request is not None else "default"
    await chat_agent.aclear_history(session_id=session_id)
    return {"message": "Histórico limpo com sucesso"}


@router.post("/api/chat/configure")
async def configure_chat(
    request: ChatConfigRequest,
    hue: HueController = Depends(get_hue_controller),
    manager: LightSetupsManager = Depends(get_manager),
):
    """Reconfigura o agente de chat com novos parâmetros."""
    if hue is None or manager is None:
        raise HTTPException(status_code=503, detail="Controlador Hue não inicializado.")

    try:
        room_index: dict[str, list[str]] | None = None
        try:
            from marvin_hue.api.dependencies import get_light_registry_service
            from marvin_hue.chat.tools.rooms import build_room_index_from_registry_rows

            reg = get_light_registry_service()
            room_index = build_room_index_from_registry_rows(await reg.list_lights())
        except Exception:
            room_index = None

        new_agent = create_hue_agent(
            controller=hue,
            manager=manager,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature,
            require_approval=settings.chat_require_approval,
            # Reusa o checkpointer ativo (lifespan) — sob sqlite, não recai p/ memória.
            checkpointer=get_chat_checkpointer(),
            room_index=room_index,
            services=ChatServices(),
        )
        set_chat_agent(new_agent)
        return {
            "message": "Agente reconfigurado com sucesso",
            "provider": request.provider,
            "model": request.model,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao reconfigurar agente: {str(e)}"
        )
