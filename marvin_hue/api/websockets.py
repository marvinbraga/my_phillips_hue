"""
WebSocket Management
Gerenciamento de conexões WebSocket para espelhamento e chat.
"""
import asyncio
from fastapi import WebSocket, WebSocketDisconnect, FastAPI
from marvin_hue.api.dependencies import get_screen_mirror, get_chat_agent
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

        # Remove conexões desconectadas
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


# Instâncias globais dos managers
ws_manager = ConnectionManager()
chat_ws_manager = ChatConnectionManager()


def setup_websockets(app: FastAPI) -> None:
    """Configura os endpoints WebSocket na aplicação."""

    @app.websocket("/ws/mirror")
    async def websocket_mirror(websocket: WebSocket):
        """WebSocket para streaming de cores em tempo real."""
        await ws_manager.connect(websocket)
        screen_mirror = get_screen_mirror()

        try:
            while True:
                # Envia status a cada 100ms quando espelhamento está ativo
                if screen_mirror and screen_mirror.is_running():
                    status = screen_mirror.get_status()
                    await websocket.send_json(status)
                    await asyncio.sleep(0.1)  # 10 FPS para o WebSocket
                else:
                    # Quando inativo, apenas verifica mensagens do cliente
                    await asyncio.sleep(0.5)

                # Verifica se há mensagem do cliente (não-bloqueante)
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=0.01
                    )
                    # Processa comandos do cliente
                    if data.get("action") == "start":
                        fps = data.get("fps", 25)
                        brightness = data.get("brightness", 200)
                        if not screen_mirror.is_running():
                            screen_mirror.start(fps=fps, brightness=brightness)
                    elif data.get("action") == "stop":
                        if screen_mirror.is_running():
                            screen_mirror.stop()
                    elif data.get("action") == "settings":
                        if "fps" in data:
                            screen_mirror.fps = data["fps"]
                        if "brightness" in data:
                            screen_mirror.brightness = data["brightness"]
                        if "saturation_boost" in data:
                            screen_mirror.saturation_boost = data["saturation_boost"]
                        if "smoothing_factor" in data:
                            screen_mirror.smoothing_factor = data["smoothing_factor"]
                        if "transition_time" in data:
                            screen_mirror.transition_time = data["transition_time"]
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
        chat_agent = get_chat_agent()

        try:
            while True:
                data = await websocket.receive_json()

                if chat_agent is None:
                    await websocket.send_json({
                        "type": "error",
                        "content": "Agente de chat não disponível."
                    })
                    continue

                action = data.get("action", "message")

                if action == "message":
                    message = data.get("message", "")
                    if not message:
                        continue

                    await websocket.send_json({
                        "type": "typing",
                        "content": True
                    })

                    try:
                        response = await chat_agent.ainvoke(message)
                        await websocket.send_json({
                            "type": "response",
                            "content": response
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "content": f"Erro: {str(e)}"
                        })
                    finally:
                        await websocket.send_json({
                            "type": "typing",
                            "content": False
                        })

                elif action == "clear":
                    chat_agent.clear_history()
                    await websocket.send_json({
                        "type": "cleared",
                        "content": "Histórico limpo"
                    })

        except WebSocketDisconnect:
            chat_ws_manager.disconnect(websocket)
        except Exception:
            chat_ws_manager.disconnect(websocket)
