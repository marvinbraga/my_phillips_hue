"""
Configuration Routes
Endpoints para gerenciar configurações de iluminação.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from marvin_hue.api.dependencies import (
    get_hue_controller,
    get_manager,
    get_scene_history_service,
)
from marvin_hue.api.models import (
    ApplyConfigDetails,
    ApplyConfigRequest,
    ApplyConfigResponse,
    ApplyFailedLight,
)
from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.services.apply_config import (
    ApplyConfigNotFoundError,
    ApplyConfigService,
)
from marvin_hue.services.scene_history import SceneHistoryService

logger = get_logger("configurations")

router = APIRouter(tags=["Configurations"])


def _apply_http_status(result: ApplyResult) -> int:
    if result.ok:
        return 200
    if result.partial:
        return 207
    return 500


def _apply_message(config_name: str, result: ApplyResult) -> str:
    if result.ok:
        return f"Applying configuration {config_name}"
    if result.partial:
        return (
            f"Configuração '{config_name}' aplicada parcialmente; "
            "algumas lâmpadas falharam"
        )
    return f"Falha ao aplicar configuração '{config_name}'; nenhuma lâmpada aplicada"


def _apply_response(
    config_name: str, transition_time_secs: float, result: ApplyResult
) -> ApplyConfigResponse:
    return ApplyConfigResponse(
        message=_apply_message(config_name, result),
        applied=list(result.applied),
        failed=[
            ApplyFailedLight(name=name, error=error) for name, error in result.failed
        ],
        details=ApplyConfigDetails(
            config_name=config_name,
            transition_time_secs=transition_time_secs,
        ),
    )


def get_sorted_configs(manager: LightSetupsManager) -> list[dict[str, str]]:
    """Retorna configurações ordenadas."""
    unique_configs = {item.name: item for item in manager.configs}.values()
    sorted_list = sorted(unique_configs, key=lambda item: item.name)
    return [
        {"name": item.name, "description": item.description} for item in sorted_list
    ]


def get_apply_config_service(
    hue: Annotated[HueController, Depends(get_hue_controller)],
    manager: Annotated[LightSetupsManager, Depends(get_manager)],
    history: Annotated[SceneHistoryService, Depends(get_scene_history_service)],
) -> ApplyConfigService:
    """Compose ApplyConfigService at the HTTP edge (not a module locator)."""
    return ApplyConfigService(manager, hue, history)


@router.get("/configurations")
async def get_configurations(
    manager: Annotated[LightSetupsManager, Depends(get_manager)],
) -> list[dict[str, str]]:
    """Retorna todas as configurações de iluminação disponíveis."""
    return get_sorted_configs(manager)


@router.post(
    "/apply",
    response_model=ApplyConfigResponse,
    responses={
        200: {
            "model": ApplyConfigResponse,
            "description": "Todas as lâmpadas aplicadas",
        },
        207: {
            "model": ApplyConfigResponse,
            "description": "Aplicação parcial: algumas lâmpadas falharam",
        },
        404: {"description": "Configuração não encontrada"},
        500: {
            "model": ApplyConfigResponse,
            "description": "Todas as lâmpadas tentadas falharam",
        },
    },
)
async def apply_configuration(
    request: ApplyConfigRequest,
    response: Response,
    manager: Annotated[LightSetupsManager, Depends(get_manager)],
    service: Annotated[ApplyConfigService, Depends(get_apply_config_service)],
) -> ApplyConfigResponse:
    """Aplica uma configuração de iluminação e devolve o ApplyResult por lâmpada."""
    if manager is None:
        raise HTTPException(
            status_code=503, detail="Gerenciador de configurações não disponível"
        )

    if not request.config_name:
        raise HTTPException(
            status_code=400, detail="Nome da configuração é obrigatório"
        )

    try:
        result = await service.apply(
            request.config_name,
            transition_time=request.transition_time_secs,
            source="apply",
        )
        status = _apply_http_status(result)
        logger.info(
            f"Apply '{request.config_name}': {len(result.applied)} applied, "
            f"{len(result.failed)} failed, http={status}"
        )
        response.status_code = status
        return _apply_response(
            request.config_name, request.transition_time_secs, result
        )
    except ApplyConfigNotFoundError:
        available = [cfg["name"] for cfg in get_sorted_configs(manager)]
        raise HTTPException(
            status_code=404,
            detail=(
                f"Configuração '{request.config_name}' não encontrada. "
                f"Disponíveis: {', '.join(available[:5])}"
            ),
        ) from None
    except ValueError as e:
        logger.error(f"Validation error applying config '{request.config_name}': {e}")
        raise HTTPException(status_code=400, detail=f"Erro de validação: {e!s}") from e
    except Exception as e:
        logger.exception(f"Unexpected error applying config '{request.config_name}'")
        raise HTTPException(
            status_code=500, detail=f"Erro ao aplicar configuração: {e!s}"
        ) from e
