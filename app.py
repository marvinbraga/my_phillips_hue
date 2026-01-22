"""
Marvin Hue Controller - FastAPI Application
Aplicação assíncrona para controle de luzes Philips Hue.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.screen_mirror import ScreenMirror
from marvin_hue.chat import create_hue_agent
from marvin_hue.logging_config import get_logger
from marvin_hue.config import settings
from marvin_hue.api import dependencies
from marvin_hue.api.routes import status, configurations, positions, mirror, chat
from marvin_hue.api.websockets import setup_websockets

logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    # Startup
    logger.info("Starting Marvin Hue application")
    logger.info(f"Configuration: bridge_ip={settings.bridge_ip}, api_port={settings.api_port}, log_level={settings.log_level}")

    # Inicializa componentes principais
    hue = HueController(ip_address=settings.bridge_ip)
    manager = LightSetupsManager(settings.setups_file)
    screen_mirror = ScreenMirror(hue, settings.positions_file)

    # Registra dependências
    dependencies.set_hue_controller(hue)
    dependencies.set_manager(manager)
    dependencies.set_screen_mirror(screen_mirror)

    # Inicializa o agente de chat
    logger.info(f"Initializing chat agent with provider='{settings.chat_provider}', model='{settings.chat_model}'")

    try:
        chat_agent = create_hue_agent(
            controller=hue,
            manager=manager,
            provider=settings.chat_provider,
            model=settings.chat_model,
            temperature=settings.chat_temperature,
        )
        dependencies.set_chat_agent(chat_agent)
        logger.info("Chat agent initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing chat agent: {e}", exc_info=True)
        dependencies.set_chat_agent(None)

    yield

    # Shutdown
    logger.info("Shutting down Marvin Hue application")
    if screen_mirror and screen_mirror.is_running():
        screen_mirror.stop()
    logger.info("Application shutdown complete")


# Aplicação FastAPI
app = FastAPI(
    title="Marvin Hue Controller",
    description="Controle de luzes Philips Hue com espelhamento de tela",
    version="2.0.0",
    lifespan=lifespan
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configurar arquivos estáticos e templates
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")

# Registrar routers
app.include_router(status.router)
app.include_router(configurations.router)
app.include_router(positions.router)
app.include_router(mirror.router)
app.include_router(chat.router)

# Configurar WebSockets
setup_websockets(app)


# Página principal
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página principal."""
    return templates.TemplateResponse("index.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )
