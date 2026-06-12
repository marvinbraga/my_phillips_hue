"""
Chat Routes
Endpoints para interação com o agente de chat.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from marvin_hue.chat import create_hue_agent, HueLightAgent
from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.config import settings
from marvin_hue.api.dependencies import (
    get_chat_agent,
    get_chat_checkpointer,
    get_hue_controller,
    get_manager,
    set_chat_agent,
)
from marvin_hue.api.models import (
    ChatMessageRequest,
    ChatClearRequest,
    ChatConfigRequest,
)
from marvin_hue.logging_config import get_logger

logger = get_logger("chat")

router = APIRouter(tags=["Chat"])

# Configurar templates
templates = Jinja2Templates(directory="web/templates")


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Página de chat com o agente Marvin."""
    return templates.TemplateResponse(request, "chat.html")


@router.get("/api/chat/status")
async def chat_status(chat_agent: HueLightAgent | None = Depends(get_chat_agent)):
    """Retorna o status do agente de chat."""
    if chat_agent is None:
        return {
            "available": False,
            "error": "Agente de chat não inicializado. Verifique as chaves de API.",
        }

    return {
        "available": True,
        "provider": settings.chat_provider,
        "model": settings.chat_model,
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
        dict: Resposta do agente

    Raises:
        HTTPException: Se o agente não estiver disponível ou houver erro
    """
    if chat_agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agente de chat não disponível. Verifique as configurações.",
        )

    # Validação adicional da mensagem
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia")

    try:
        response = await chat_agent.ainvoke(request.message, session_id=request.session_id)
        return {"response": response, "success": True}
    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        raise HTTPException(
            status_code=500, detail=f"Erro ao processar mensagem: {str(e)}"
        )


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
        raise HTTPException(status_code=503, detail="Agente de chat não disponível.")

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
        new_agent = create_hue_agent(
            controller=hue,
            manager=manager,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature,
            # Reusa o checkpointer ativo (lifespan) — sob sqlite, não recai p/ memória.
            checkpointer=get_chat_checkpointer(),
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
