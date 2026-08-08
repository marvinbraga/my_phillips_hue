"""
WebSocket Management
Gerenciamento de conexões WebSocket para espelhamento e chat.
"""

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from marvin_hue.api.dependencies import (
    get_audio_mirror,
    get_chat_agent,
    get_chat_unavailable_reason,
    get_screen_mirror,
)
from marvin_hue.api.routes.mirror import _unified_status
from marvin_hue.logging_config import get_logger

logger = get_logger("websockets")


class ConnectionManager:
    """Gerencia conexões WebSocket."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
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

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)


ws_manager = ConnectionManager()
chat_ws_manager = ChatConnectionManager()


def setup_websockets(app: FastAPI) -> None:
    """Configura os endpoints WebSocket na aplicação."""

    @app.websocket("/ws/mirror")
    async def websocket_mirror(websocket: WebSocket):
        """WebSocket para streaming de cores/spectrum em tempo real."""
        await ws_manager.connect(websocket)
        screen_mirror = get_screen_mirror()
        audio_mirror = get_audio_mirror()

        try:
            while True:
                any_running = screen_mirror.is_running() or audio_mirror.is_running()
                if any_running:
                    status = _unified_status(screen_mirror, audio_mirror)
                    await websocket.send_json(status)
                    await asyncio.sleep(0.1)  # 10 FPS para o WebSocket
                else:
                    await asyncio.sleep(0.5)

                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(), timeout=0.01
                    )
                    action = data.get("action")
                    mode = data.get("mode") or "screen"

                    if action == "start":
                        profile = data.get("profile")
                        fps = data.get("fps")
                        brightness = data.get("brightness")
                        if mode == "audio":
                            if audio_mirror.is_running():
                                continue
                            if screen_mirror.is_running():
                                screen_mirror.stop()
                            try:
                                audio_mirror.start(
                                    fps=fps,
                                    brightness=brightness,
                                    profile=profile,
                                )
                            except (ValueError, RuntimeError) as e:
                                logger.warning(f"Invalid audio mirror start: {e}")
                                await websocket.send_json(
                                    {"error": str(e), "running": False, "mode": "audio"}
                                )
                        else:
                            if screen_mirror.is_running():
                                continue
                            if audio_mirror.is_running():
                                audio_mirror.stop()
                            try:
                                screen_mirror.start(
                                    fps=fps,
                                    brightness=brightness,
                                    profile=profile,
                                )
                            except ValueError as e:
                                logger.warning(f"Invalid mirror start: {e}")

                    elif action == "stop":
                        if audio_mirror.is_running():
                            audio_mirror.stop()
                        if screen_mirror.is_running():
                            screen_mirror.stop()

                    elif action == "settings":
                        target = data.get("mode") or (
                            "audio"
                            if audio_mirror.is_running()
                            else "screen"
                        )
                        try:
                            if target == "audio":
                                if data.get("profile"):
                                    audio_mirror.apply_profile(data["profile"])
                                if "fps" in data:
                                    audio_mirror.fps = data["fps"]
                                if "brightness" in data:
                                    audio_mirror.brightness = data["brightness"]
                                if "smoothing_factor" in data:
                                    audio_mirror.smoothing_factor = data[
                                        "smoothing_factor"
                                    ]
                                if "transition_time" in data:
                                    audio_mirror.transition_time = data[
                                        "transition_time"
                                    ]
                                if "energy_gain" in data:
                                    audio_mirror.energy_gain = data["energy_gain"]
                            else:
                                if data.get("profile"):
                                    screen_mirror.apply_profile(data["profile"])
                                if "fps" in data:
                                    screen_mirror.fps = data["fps"]
                                if "brightness" in data:
                                    screen_mirror.brightness = data["brightness"]
                                if "saturation_boost" in data:
                                    screen_mirror.saturation_boost = data[
                                        "saturation_boost"
                                    ]
                                if "smoothing_factor" in data:
                                    screen_mirror.smoothing_factor = data[
                                        "smoothing_factor"
                                    ]
                                if "transition_time" in data:
                                    screen_mirror.transition_time = data[
                                        "transition_time"
                                    ]
                        except ValueError as e:
                            logger.warning(f"Invalid mirror settings: {e}")
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
