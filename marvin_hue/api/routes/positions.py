"""
Position Routes
Endpoints para gerenciar posicionamento de lâmpadas para espelhamento.
"""
import json
from pathlib import Path
from typing import Any
import aiofiles
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from marvin_hue.api.models import PositionsUpdate

router = APIRouter(tags=["Positions"])

# Configurar templates
templates = Jinja2Templates(directory="web/templates")

# Constantes
POSITIONS_FILE = Path(".res/light_positions.json")


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


@router.get("/positions-config", response_class=HTMLResponse)
async def positions_page(request: Request):
    """Página de configuração de posicionamento."""
    return templates.TemplateResponse("positions.html", {"request": request})


@router.get("/positions")
async def get_positions():
    """Retorna a configuração de posicionamento das lâmpadas."""
    data = await load_json_file(POSITIONS_FILE)
    if not data:
        # Retorna configuração padrão
        return await reset_positions()
    return data


@router.post("/positions")
async def save_positions(request: PositionsUpdate):
    """Salva a configuração de posicionamento."""
    current = await load_json_file(POSITIONS_FILE)
    current["lights"] = [light.model_dump() for light in request.lights]
    await save_json_file(POSITIONS_FILE, current)
    return {"message": "Configuração salva com sucesso"}


@router.post("/positions/reset")
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
