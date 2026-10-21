"""
WebSocket Management
Gerenciamento de conexões WebSocket para espelhamento e chat.
"""

import asyncio
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from marvin_hue.api.dependencies import (
    get_chat_agent,
    get_chat_unavailable_reason,
    get_mirror_control_service,
)
from marvin_hue.api.models import ChatResumeRequest
from marvin_hue.chat.hitl import ApprovalError, ApprovalRequired
from marvin_hue.logging_config import get_logger
from marvin_hue.services.mirror_control import (
    MirrorAlreadyActiveError,
    MirrorConfigNotFoundError,
    MirrorControlService,
    MirrorNotActiveError,
    MirrorValidationError,
)

logger = get_logger("websockets")

# Código de fechamento WebSocket "policy violation" (RFC 6455).
_WS_POLICY_VIOLATION = 1008


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Same-origin check para WebSockets do navegador (anti-CSWSH).

    Sem ``Origin`` (CLI/scripts, fora do navegador) → permitido: o chat fica
    aberto na LAN por design. Com ``Origin``, o host:porta tem de bater com o
    ``Host`` da requisição; ``null`` (iframes sandbox, file://) é recusado.
    """
    if origin is None:
        return True
    if not host:
        return False
    netloc = urlsplit(origin).netloc
    return bool(netloc) and netloc.casefold() == host.strip().casefold()


async def dispatch_ws_mirror_action(
    data: dict[str, Any],
    service: MirrorControlService,
) -> dict[str, Any] | None:
    """Adapt a WS command payload to MirrorControlService start/stop/settings."""
    action = data.get("action")
    if action == "start":
        mode = data.get("mode") or "screen"
        try:
            result = await service.start(
                mode,
                profile=data.get("profile"),
                fps=data.get("fps"),
                brightness=data.get("brightness"),
                area_id=data.get("area_id"),
                transport_preference=data.get("transport_preference"),
                config_name=data.get("config_name"),
            )
        except MirrorAlreadyActiveError:
            return None
        except (
            MirrorValidationError,
            MirrorConfigNotFoundError,
            RuntimeError,
            ValueError,
        ) as exc:
            logger.warning(f"Invalid mirror start: {exc}")
            return {"error": str(exc), "running": False, "mode": mode}
        if isinstance(result, dict):
            status = result.get("status")
            if isinstance(status, dict):
                return status
        return None

    if action == "stop":
        try:
            await service.stop()
        except MirrorNotActiveError:
            return None
        return service.unified_status()

    if action == "settings":
        try:
            result = await service.apply_settings(
                mode=data.get("mode"),
                profile=data.get("profile"),
                fps=data.get("fps") if "fps" in data else None,
                brightness=data.get("brightness") if "brightness" in data else None,
                saturation_boost=(
                    data.get("saturation_boost") if "saturation_boost" in data else None
                ),
                smoothing_factor=(
                    data.get("smoothing_factor") if "smoothing_factor" in data else None
                ),
                transition_time=(
                    data.get("transition_time") if "transition_time" in data else None
                ),
                energy_gain=data.get("energy_gain") if "energy_gain" in data else None,
                entertainment_area_id=data.get("entertainment_area_id"),
                transport_preference=data.get("transport_preference"),
                config_name=data.get("config_name"),
                config_name_provided="config_name" in data,
            )
        except (
            MirrorValidationError,
            MirrorConfigNotFoundError,
            ValueError,
        ) as exc:
            logger.warning(f"Invalid mirror settings: {exc}")
            return {"error": str(exc)}
        if isinstance(result, dict):
            status = result.get("status")
            if isinstance(status, dict):
                return status
        return None

    return None


def chat_turn_frame(result: Any) -> dict[str, Any]:
    """Frame WS de um turno: resposta final ou pedidos de aprovação."""
    if isinstance(result, ApprovalRequired):
        return result.to_dict()
    return {"type": "response", "content": result}


def parse_ws_resume(data: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    """Valida ``{"action": "resume", "decisions": [...]}`` com o modelo REST."""
    req = ChatResumeRequest(session_id=session_id, decisions=data.get("decisions") or [])
    return [d.model_dump(exclude_none=True) for d in req.decisions]


class ConnectionManager:
    """Gerencia conexões WebSocket."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Envia mensagem para todas as conexões ativas."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


class ChatConnectionManager:
    """Gerencia conexões WebSocket do chat."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)


ws_manager = ConnectionManager()
chat_ws_manager = ChatConnectionManager()


def setup_websockets(app: FastAPI) -> None:
    """Configura os endpoints WebSocket na aplicação."""

    @app.websocket("/ws/mirror")
    async def websocket_mirror(websocket: WebSocket) -> None:
        """WebSocket para streaming de cores/spectrum em tempo real."""
        await ws_manager.connect(websocket)
        svc = get_mirror_control_service()

        try:
            while True:
                status = svc.unified_status()
                running = bool(status.get("running")) or status.get("mode") in (
                    "screen",
                    "audio",
                )
                if running:
                    await websocket.send_json(status)
                    timeout = 0.04 if status.get("mode") == "audio" else 0.08
                else:
                    timeout = 0.5
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(), timeout=timeout
                    )
                    reply = await dispatch_ws_mirror_action(data, svc)
                    if reply is not None:
                        await websocket.send_json(reply)
                except asyncio.TimeoutError:
                    pass

        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception:
            ws_manager.disconnect(websocket)

    @app.websocket("/ws/chat")
    async def websocket_chat(websocket: WebSocket):
        """WebSocket para comunicação em tempo real com o chat.

        O chat é um canal com privilégio total (luzes, cenas, agendamentos,
        espelhamento): conexões de navegador cross-origin são recusadas antes
        do accept.
        """
        origin = websocket.headers.get("origin")
        if not origin_allowed(origin, websocket.headers.get("host")):
            logger.warning(f"/ws/chat recusado: origin cross-site {origin!r}")
            await websocket.close(code=_WS_POLICY_VIOLATION)
            return
        await chat_ws_manager.connect(websocket)

        try:
            while True:
                data = await websocket.receive_json()

                chat_agent = get_chat_agent()
                if chat_agent is None:
                    reason = (
                        get_chat_unavailable_reason()
                        or "Agente de chat não disponível."
                    )
                    await websocket.send_json({"type": "error", "content": reason})
                    continue

                action = data.get("action", "message")
                session_id = str(data.get("session_id") or "default")[:128]

                if action == "message":
                    message = data.get("message", "")
                    if not message:
                        continue

                    await websocket.send_json({"type": "typing", "content": True})

                    try:
                        result = await chat_agent.ainvoke(
                            message, session_id=session_id
                        )
                        await websocket.send_json(chat_turn_frame(result))
                    except Exception as e:
                        await websocket.send_json(
                            {"type": "error", "content": f"Erro: {str(e)}"}
                        )
                    finally:
                        await websocket.send_json({"type": "typing", "content": False})

                elif action == "resume":
                    try:
                        decisions = parse_ws_resume(data, session_id)
                    except ValidationError:
                        await websocket.send_json(
                            {"type": "error", "content": "Decisões de aprovação inválidas."}
                        )
                        continue

                    await websocket.send_json({"type": "typing", "content": True})
                    try:
                        result = await chat_agent.aresume(session_id, decisions)
                        await websocket.send_json(chat_turn_frame(result))
                    except ApprovalError as e:
                        await websocket.send_json({"type": "error", "content": str(e)})
                    except Exception as e:
                        await websocket.send_json(
                            {"type": "error", "content": f"Erro: {str(e)}"}
                        )
                    finally:
                        await websocket.send_json({"type": "typing", "content": False})

                elif action == "pending":
                    # Página recarregada: reapresenta o cartão de aprovação.
                    try:
                        pending = await chat_agent.apending(session_id)
                    except Exception as e:
                        logger.warning(f"/ws/chat pending falhou: {e}")
                        pending = None
                    if pending is not None:
                        await websocket.send_json(pending.to_dict())

                elif action == "clear":
                    await chat_agent.aclear_history(session_id=session_id)
                    await websocket.send_json(
                        {"type": "cleared", "content": "Histórico limpo"}
                    )

        except WebSocketDisconnect:
            chat_ws_manager.disconnect(websocket)
        except Exception:
            chat_ws_manager.disconnect(websocket)
