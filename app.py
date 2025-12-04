"""
Marvin Hue Controller - FastAPI Application
Aplicação assíncrona para controle de luzes Philips Hue.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiofiles
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.chat import create_hue_agent, HueLightAgent

# Constantes
POSITIONS_FILE = Path(".res/light_positions.json")
SETUPS_FILE = Path(".res/setups.json")

# Instâncias globais
hue: HueController | None = None
manager: LightSetupsManager | None = None
screen_mirror: ScreenMirror | None = None
chat_agent: HueLightAgent | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    global hue, manager, screen_mirror, chat_agent

    # Startup
    hue = HueController(ip_address=os.getenv("BRIDGE_IP"))
    manager = LightSetupsManager(str(SETUPS_FILE))
    screen_mirror = ScreenMirror(hue, str(POSITIONS_FILE))

    # Inicializa o agente de chat
    # Configurado via variáveis de ambiente ou valores padrão
    chat_provider = os.getenv("CHAT_PROVIDER", "openai")
    chat_model = os.getenv("CHAT_MODEL", "gpt-4o-mini")

    print(f"[Chat] Inicializando agente com provider='{chat_provider}', model='{chat_model}'")

    try:
        chat_agent = create_hue_agent(
            controller=hue,
            manager=manager,
            provider=chat_provider,
            model=chat_model,
            temperature=0.7,
        )
        print(f"[Chat] Agente inicializado com sucesso!")
    except Exception as e:
        print(f"[Chat] Erro ao inicializar agente: {e}")
        chat_agent = None

    yield

    # Shutdown
    if screen_mirror and screen_mirror.is_running():
        screen_mirror.stop()


# Aplicação FastAPI
app = FastAPI(
    title="Marvin Hue Controller",
    description="Controle de luzes Philips Hue com espelhamento de tela",
    version="2.0.0",
    lifespan=lifespan
)

# Configurar arquivos estáticos e templates
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")


# ==================== MODELOS PYDANTIC ====================

class ApplyConfigRequest(BaseModel):
    config_name: str
    transition_time_secs: float = 0
    duration_minutes: float | None = None


class LightPosition(BaseModel):
    name: str
    position: str
    enabled: bool


class PositionsUpdate(BaseModel):
    lights: list[LightPosition]


class MirrorStartRequest(BaseModel):
    fps: int = 25
    brightness: int = 200


class MirrorSettingsRequest(BaseModel):
    fps: int | None = None
    brightness: int | None = None
    saturation_boost: float | None = None
    smoothing_factor: float | None = None
    transition_time: float | None = None


class ChatMessageRequest(BaseModel):
    message: str


class ChatConfigRequest(BaseModel):
    provider: str
    model: str
    temperature: float = 0.7


# ==================== FUNÇÕES AUXILIARES ====================

async def load_json_file(filepath: Path) -> dict[str, Any]:
    """Carrega um arquivo JSON de forma assíncrona."""
    if not filepath.exists():
        return {}
    async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
        content = await f.read()
        return json.loads(content)


async def save_json_file(filepath: Path, data: dict[str, Any]) -> None:
    """Salva um arquivo JSON de forma assíncrona."""
    async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))


def get_sorted_configs() -> list[dict[str, str]]:
    """Retorna configurações ordenadas."""
    unique_configs = {item.name: item for item in manager.configs}.values()
    sorted_list = sorted(unique_configs, key=lambda item: item.name)
    return [{"name": item.name, "description": item.description} for item in sorted_list]


# ==================== ROTAS DE STATUS ====================

@app.get("/api/bridge/status")
async def bridge_status():
    """Retorna o status de conexão com a bridge Hue."""
    try:
        # Tenta obter informações da bridge
        lights = hue.bridge.get_light_objects()
        light_count = len(lights) if lights else 0
        return {
            "connected": True,
            "bridge_ip": hue.bridge.ip,
            "light_count": light_count
        }
    except Exception as e:
        return {
            "connected": False,
            "error": str(e)
        }


@app.get("/api/lights/status")
async def lights_status():
    """Retorna o estado atual de todas as lâmpadas com suas cores."""
    try:
        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(None, hue.get_lights_status)
        return {"lights": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ROTAS DE PÁGINAS ====================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página principal."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/positions-config", response_class=HTMLResponse)
async def positions_page(request: Request):
    """Página de configuração de posicionamento."""
    return templates.TemplateResponse("positions.html", {"request": request})


@app.get("/mirror", response_class=HTMLResponse)
async def mirror_page(request: Request):
    """Página de espelhamento de tela."""
    return templates.TemplateResponse("mirror.html", {"request": request})


# ==================== ROTAS DE CONFIGURAÇÕES ====================

@app.get("/configurations")
async def get_configurations():
    """Retorna todas as configurações de iluminação disponíveis."""
    return get_sorted_configs()


@app.post("/apply")
async def apply_configuration(request: ApplyConfigRequest):
    """Aplica uma configuração de iluminação."""
    config_obj = manager.get_config(request.config_name)
    if not config_obj:
        raise HTTPException(status_code=404, detail=f"Configuração '{request.config_name}' não encontrada")

    # Aplica em uma task separada para não bloquear
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: hue.apply_light_config(config_obj, request.transition_time_secs)
    )

    return {
        "message": f"Applying configuration {request.config_name}",
        "details": {
            "config_name": request.config_name,
            "transition_time_secs": request.transition_time_secs,
            "duration_minutes": request.duration_minutes
        }
    }


# ==================== ROTAS DE POSICIONAMENTO ====================

@app.get("/positions")
async def get_positions():
    """Retorna a configuração de posicionamento das lâmpadas."""
    data = await load_json_file(POSITIONS_FILE)
    if not data:
        # Retorna configuração padrão
        return await reset_positions()
    return data


@app.post("/positions")
async def save_positions(request: PositionsUpdate):
    """Salva a configuração de posicionamento."""
    current = await load_json_file(POSITIONS_FILE)
    current["lights"] = [light.model_dump() for light in request.lights]
    await save_json_file(POSITIONS_FILE, current)
    return {"message": "Configuração salva com sucesso"}


@app.post("/positions/reset")
async def reset_positions():
    """Restaura a configuração padrão de posicionamento."""
    default_config = {
        "lights": [
            {"name": "Lâmpada 1", "position": "none", "enabled": True},
            {"name": "Lâmpada 2", "position": "none", "enabled": True},
            {"name": "Lâmpada 4", "position": "none", "enabled": True},
            {"name": "Hue Iris", "position": "none", "enabled": True},
            {"name": "Hue Play 1", "position": "left", "enabled": True},
            {"name": "Hue Play 2", "position": "right", "enabled": True},
            {"name": "Fita Led", "position": "top", "enabled": True},
            {"name": "Led cima", "position": "top", "enabled": True}
        ],
        "positions": [
            {"id": "none", "label": "Não usar", "description": "Lâmpada não participa do espelhamento"},
            {"id": "left", "label": "Esquerda", "description": "Lado esquerdo do monitor"},
            {"id": "right", "label": "Direita", "description": "Lado direito do monitor"},
            {"id": "top", "label": "Topo", "description": "Parte superior do monitor"},
            {"id": "bottom", "label": "Base", "description": "Parte inferior do monitor"},
            {"id": "top-left", "label": "Topo Esquerdo", "description": "Canto superior esquerdo"},
            {"id": "top-right", "label": "Topo Direito", "description": "Canto superior direito"},
            {"id": "bottom-left", "label": "Base Esquerda", "description": "Canto inferior esquerdo"},
            {"id": "bottom-right", "label": "Base Direita", "description": "Canto inferior direito"},
            {"id": "center", "label": "Centro", "description": "Região central da tela"},
            {"id": "ambient", "label": "Ambiente", "description": "Cor média de toda a tela"}
        ]
    }
    await save_json_file(POSITIONS_FILE, default_config)
    return default_config


# ==================== ROTAS DE ESPELHAMENTO ====================

@app.post("/mirror/start")
async def start_mirror(request: MirrorStartRequest):
    """Inicia o espelhamento de tela."""
    if screen_mirror.is_running():
        raise HTTPException(status_code=400, detail="Espelhamento já está ativo")

    screen_mirror.start(fps=request.fps, brightness=request.brightness)
    return {
        "message": "Espelhamento iniciado",
        "status": screen_mirror.get_status()
    }


@app.post("/mirror/stop")
async def stop_mirror():
    """Para o espelhamento de tela."""
    if not screen_mirror.is_running():
        raise HTTPException(status_code=400, detail="Espelhamento não está ativo")

    screen_mirror.stop()
    return {"message": "Espelhamento parado"}


@app.get("/mirror/status")
async def mirror_status():
    """Retorna o status atual do espelhamento."""
    return screen_mirror.get_status()


@app.post("/mirror/settings")
async def update_mirror_settings(request: MirrorSettingsRequest):
    """Atualiza configurações do espelhamento em tempo real."""
    if request.fps is not None:
        screen_mirror.fps = request.fps
    if request.brightness is not None:
        screen_mirror.brightness = request.brightness
    if request.saturation_boost is not None:
        screen_mirror.saturation_boost = request.saturation_boost
    if request.smoothing_factor is not None:
        screen_mirror.smoothing_factor = request.smoothing_factor
    if request.transition_time is not None:
        screen_mirror.transition_time = request.transition_time

    return {
        "message": "Configurações atualizadas",
        "status": screen_mirror.get_status()
    }


# ==================== WEBSOCKET PARA ESPELHAMENTO ====================

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


ws_manager = ConnectionManager()


@app.websocket("/ws/mirror")
async def websocket_mirror(websocket: WebSocket):
    """WebSocket para streaming de cores em tempo real."""
    await ws_manager.connect(websocket)

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


# ==================== ROTAS DO CHAT ====================

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Página de chat com o agente Marvin."""
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/api/chat/status")
async def chat_status():
    """Retorna o status do agente de chat."""
    if chat_agent is None:
        return {
            "available": False,
            "error": "Agente de chat não inicializado. Verifique as chaves de API."
        }

    return {
        "available": True,
        "provider": os.getenv("CHAT_PROVIDER", "openai"),
        "model": os.getenv("CHAT_MODEL", "gpt-4o-mini")
    }


@app.post("/api/chat/message")
async def send_chat_message(request: ChatMessageRequest):
    """Envia uma mensagem para o agente e retorna a resposta."""
    if chat_agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agente de chat não disponível. Verifique as configurações."
        )

    try:
        response = await chat_agent.ainvoke(request.message)
        return {
            "response": response,
            "success": True
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao processar mensagem: {str(e)}"
        )


@app.post("/api/chat/clear")
async def clear_chat_history():
    """Limpa o histórico de conversação."""
    if chat_agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agente de chat não disponível."
        )

    chat_agent.clear_history()
    return {"message": "Histórico limpo com sucesso"}


@app.post("/api/chat/configure")
async def configure_chat(request: ChatConfigRequest):
    """Reconfigura o agente de chat com novos parâmetros."""
    global chat_agent

    if hue is None or manager is None:
        raise HTTPException(
            status_code=503,
            detail="Controlador Hue não inicializado."
        )

    try:
        chat_agent = create_hue_agent(
            controller=hue,
            manager=manager,
            provider=request.provider,
            model=request.model,
            temperature=request.temperature,
        )
        return {
            "message": "Agente reconfigurado com sucesso",
            "provider": request.provider,
            "model": request.model
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao reconfigurar agente: {str(e)}"
        )


# ==================== WEBSOCKET DO CHAT ====================

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


chat_ws_manager = ChatConnectionManager()


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket para comunicação em tempo real com o chat."""
    await chat_ws_manager.connect(websocket)

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


# ==================== EXECUÇÃO ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=5000,
        reload=True
    )
