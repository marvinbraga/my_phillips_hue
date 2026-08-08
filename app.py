"""
Marvin Hue Controller - FastAPI Application
Aplicação assíncrona para controle de luzes Philips Hue.
"""

from contextlib import asynccontextmanager, AsyncExitStack

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from marvin_hue.basics import LightSetupsManager  # noqa: E402
from marvin_hue.controllers import HueController  # noqa: E402
from marvin_hue.screen_mirror import ScreenMirror  # noqa: E402
from marvin_hue.chat import create_hue_agent  # noqa: E402
from marvin_hue.logging_config import get_logger  # noqa: E402
from marvin_hue.config import settings  # noqa: E402
from marvin_hue.api import dependencies  # noqa: E402
from marvin_hue.api.middleware.api_key import ApiKeyMiddleware  # noqa: E402
from marvin_hue.api.routes import (  # noqa: E402
    status,
    configurations,
    positions,
    mirror,
    chat,
    lights,
    health,
    backup,
)
from marvin_hue.api.websockets import setup_websockets  # noqa: E402

logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    # Startup
    logger.info("Starting Marvin Hue application")
    logger.info(
        f"Configuration: bridge_ip={settings.bridge_ip}, api_port={settings.api_port}, log_level={settings.log_level}"
    )

    # Inicializa componentes principais
    hue = HueController(ip_address=settings.bridge_ip)
    manager = LightSetupsManager(settings.setups_file)
    screen_mirror = ScreenMirror(hue, settings.positions_file)

    # Registra dependências
    dependencies.set_hue_controller(hue)
    dependencies.set_manager(manager)
    dependencies.set_screen_mirror(screen_mirror)

    # App-owned lights registry (separate SQLite from chat checkpointer)
    from marvin_hue.persistence.schema import init_db
    from marvin_hue.persistence.light_repository import SqliteLightRegistryRepository
    from marvin_hue.services.light_registry import LightRegistryService

    light_repo: SqliteLightRegistryRepository | None = None
    try:
        await init_db(settings.app_db_path)
        light_repo = await SqliteLightRegistryRepository.open(settings.app_db_path)
        light_registry = LightRegistryService(light_repo, bridge=hue)
        dependencies.set_light_registry_service(light_registry)
        await light_registry.refresh_runtime_policy()
        logger.info(f"Light registry initialized at {settings.app_db_path}")
        logger.info("Eye-safety / enabled_for_app policy loaded from registry")
    except Exception as e:
        logger.exception(f"Error initializing light registry: {e}")
        dependencies.set_light_registry_service(None)
        # Fail closed for registry: hard-fail startup so misconfig is visible.
        raise

    # Inicializa o agente de chat
    logger.info(
        f"Initializing chat agent with provider='{settings.chat_provider}', "
        f"model='{settings.chat_model}', checkpoint='{settings.chat_checkpoint}'"
    )

    # O ciclo de vida do checkpointer é do COMPOSITOR (este lifespan), não do
    # agente. Para sqlite usamos AsyncSqliteSaver — REQUERIDO sob concorrência de
    # sessões (FastAPI async); o SqliteSaver síncrono daria "database is locked".
    async with AsyncExitStack() as stack:
        checkpointer = None
        if settings.chat_checkpoint == "sqlite":
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            checkpointer = await stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(settings.chat_checkpoint_db)
            )
        # Registra o checkpointer p/ que o reconfigure reuse o MESMO (não recaia
        # em InMemorySaver sob sqlite).
        dependencies.set_chat_checkpointer(checkpointer)

        try:
            # Room snapshot at agent build time (tools stay sync). Room edits
            # in the registry need agent rebuild (reconfigure / restart).
            from marvin_hue.chat.tools.light_tools import (
                build_room_index_from_registry_rows,
            )

            room_index: dict[str, list[str]] | None = None
            try:
                room_index = build_room_index_from_registry_rows(
                    await light_registry.list_lights()
                )
                logger.info(
                    f"Chat room_index built: {len(room_index)} room(s) from registry"
                )
            except Exception as room_exc:
                logger.warning(
                    f"Chat room_index unavailable (locations fallback): {room_exc}"
                )
                room_index = None

            chat_agent = create_hue_agent(
                controller=hue,
                manager=manager,
                provider=settings.chat_provider,
                model=settings.chat_model,
                temperature=settings.chat_temperature,
                checkpointer=checkpointer,
                room_index=room_index,
            )
            dependencies.set_chat_agent(chat_agent)
            logger.info("Chat agent initialized successfully")
        except Exception as e:
            logger.exception(f"Error initializing chat agent: {e}")
            # Diagnóstico para clientes da API (sem secrets): key ausente tem
            # prioridade; senão, primeira linha sanitizada da exceção.
            reason = dependencies.diagnose_chat_credentials(settings.chat_provider)
            if reason is None:
                sanitized = dependencies.sanitize_chat_init_error(e)
                reason = f"Falha ao inicializar agente: {sanitized}"
            dependencies.set_chat_agent(None, reason=reason)

        try:
            yield
        finally:
            if light_repo is not None:
                await light_repo.close()
            dependencies.set_light_registry_service(None)
            from marvin_hue.eye_safety import clear_runtime_policy

            clear_runtime_policy()
    # Saída do AsyncExitStack fecha o AsyncSqliteSaver (se usado) no shutdown.

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
    lifespan=lifespan,
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key for /api/* only (no-op when settings.api_key is empty).
# Starlette: last added middleware is outermost; add after CORS so CORS runs first.
app.add_middleware(ApiKeyMiddleware, api_key=settings.api_key)

# Configurar arquivos estáticos e templates
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")

# Registrar routers (status before lights so GET /api/lights/status is not shadowed)
app.include_router(status.router)
app.include_router(lights.router)
app.include_router(configurations.router)
app.include_router(positions.router)
app.include_router(mirror.router)
app.include_router(chat.router)
app.include_router(health.router)
app.include_router(backup.router)

# Configurar WebSockets
setup_websockets(app)


# Página principal
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página principal."""
    return templates.TemplateResponse(request, "index.html", {"active": "controle"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=settings.api_host, port=settings.api_port, reload=True)
