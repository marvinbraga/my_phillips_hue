"""
Configuration Routes
Endpoints para gerenciar configurações de iluminação.
"""

import asyncio
from fastapi import APIRouter, HTTPException, Depends
from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.api.dependencies import get_hue_controller, get_manager
from marvin_hue.api.models import ApplyConfigRequest
from marvin_hue.logging_config import get_logger

logger = get_logger("configurations")

router = APIRouter(tags=["Configurations"])


def get_sorted_configs(manager: LightSetupsManager) -> list[dict[str, str]]:
    """Retorna configurações ordenadas."""
    unique_configs = {item.name: item for item in manager.configs}.values()
    sorted_list = sorted(unique_configs, key=lambda item: item.name)
    return [
        {"name": item.name, "description": item.description} for item in sorted_list
    ]


@router.get("/configurations")
async def get_configurations(manager: LightSetupsManager = Depends(get_manager)):
    """Retorna todas as configurações de iluminação disponíveis."""
    return get_sorted_configs(manager)


@router.post("/apply")
async def apply_configuration(
    request: ApplyConfigRequest,
    hue: HueController = Depends(get_hue_controller),
    manager: LightSetupsManager = Depends(get_manager),
):
    """
    Aplica uma configuração de iluminação.

    Args:
        request: Requisição com nome da configuração e parâmetros

    Returns:
        dict: Confirmação da aplicação

    Raises:
        HTTPException: Se a configuração não for encontrada ou houver erro
    """
    # Valida que o manager está disponível
    if manager is None:
        raise HTTPException(
            status_code=503, detail="Gerenciador de configurações não disponível"
        )

    # Valida nome da configuração
    if not request.config_name:
        raise HTTPException(
            status_code=400, detail="Nome da configuração é obrigatório"
        )

    config_obj = manager.get_config(request.config_name)
    if not config_obj:
        # Lista configurações disponíveis para ajudar o usuário
        available = [cfg["name"] for cfg in get_sorted_configs(manager)]
        raise HTTPException(
            status_code=404,
            detail=f"Configuração '{request.config_name}' não encontrada. Disponíveis: {', '.join(available[:5])}",
        )

    try:
        # Aplica em uma task separada para não bloquear
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: hue.apply_light_config(config_obj, request.transition_time_secs),
        )

        return {
            "message": f"Applying configuration {request.config_name}",
            "details": {
                "config_name": request.config_name,
                "transition_time_secs": request.transition_time_secs,
                "duration_minutes": request.duration_minutes,
            },
        }
    except ValueError as e:
        logger.error(f"Validation error applying config '{request.config_name}': {e}")
        raise HTTPException(status_code=400, detail=f"Erro de validação: {str(e)}")
    except Exception as e:
        logger.error(
            f"Unexpected error applying config '{request.config_name}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Erro ao aplicar configuração: {str(e)}"
        )
