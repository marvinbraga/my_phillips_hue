"""
WebSocket Management
Gerenciamento de conexões WebSocket para espelhamento e chat.
"""

import asyncio
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from marvin_hue.api.dependencies import (
    get_chat_agent,
    get_chat_unavailable_reason,
    get_mirror_control_service,
)
from marvin_hue.logging_config import get_logger
from marvin_hue.services.mirror_control import (
    MirrorAlreadyActiveError,
    MirrorConfigNotFoundError,
    MirrorControlService,
    MirrorNotActiveError,
    MirrorValidationError,
)

logger = get_logger("websockets")


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
        """WebSocket para comunicação em tempo real com o chat."""
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
                        response = await chat_agent.ainvoke(
                            message, session_id=session_id
                        )
                        await websocket.send_json(
                            {"type": "response", "content": response}
                        )
                    except Exception as e:
                        await websocket.send_json(
                            {"type": "error", "content": f"Erro: {str(e)}"}
                        )
                    finally:
                        await websocket.send_json({"type": "typing", "content": False})

                elif action == "clear":
                    await chat_agent.aclear_history(session_id=session_id)
                    await websocket.send_json(
                        {"type": "cleared", "content": "Histórico limpo"}
                    )

        except WebSocketDisconnect:
            chat_ws_manager.disconnect(websocket)
        except Exception:
            chat_ws_manager.disconnect(websocket)
