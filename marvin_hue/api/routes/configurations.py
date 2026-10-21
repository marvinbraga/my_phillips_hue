"""
Configuration Routes
Endpoints para gerenciar configurações de iluminação.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from marvin_hue.api.dependencies import (
    get_hue_controller,
    get_manager,
    get_scene_favorites_service,
    get_scene_history_service,
)
from marvin_hue.api.models import (
    ApplyConfigDetails,
    ApplyConfigRequest,
    ApplyConfigResponse,
    ApplyFailedLight,
    ConfigurationColor,
    ConfigurationPreview,
    ConfigurationSetting,
    ConfigurationWithSettings,
    FavoritesListResponse,
    FavoriteStatusResponse,
)
from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.logging_config import get_logger
from marvin_hue.services.apply_config import (
    ApplyConfigNotFoundError,
    ApplyConfigService,
)
from marvin_hue.services.scene_favorites import (
    FavoriteConfigNotFoundError,
    SceneFavoritesService,
)
from marvin_hue.services.scene_history import SceneHistoryService
from marvin_hue.services.scene_preview import build_scene_preview

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


def _sorted_unique_configs(manager: LightSetupsManager) -> list[LightConfig]:
    """Deduplica por nome (primeiro vence, como ``get_config``/apply) e ordena."""
    unique_configs: dict[str, LightConfig] = {}
    for item in manager.configs:
        unique_configs.setdefault(item.name, item)
    return sorted(unique_configs.values(), key=lambda item: item.name)


def get_sorted_configs(manager: LightSetupsManager) -> list[dict[str, str]]:
    """Retorna configurações ordenadas."""
    return [
        {"name": item.name, "description": item.description}
        for item in _sorted_unique_configs(manager)
    ]


def get_sorted_configs_with_settings(
    manager: LightSetupsManager,
) -> list[ConfigurationWithSettings]:
    """Configurações ordenadas com settings e preview por lâmpada."""
    return [
        ConfigurationWithSettings(
            name=item.name,
            description=item.description,
            settings=[
                ConfigurationSetting(
                    light_name=light.light_name,
                    color=ConfigurationColor(**light.color),
                    preview=ConfigurationPreview(
                        r=light.r,
                        g=light.g,
                        b=light.b,
                        brightness=light.brightness,
                        enabled=light.enabled,
                    ),
                )
                for light in build_scene_preview(item)
            ],
        )
        for item in _sorted_unique_configs(manager)
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
    include_settings: Annotated[
        bool,
        Query(description="Inclui settings por lâmpada com cor configurada e preview"),
    ] = False,
) -> list[ConfigurationWithSettings] | list[dict[str, str]]:
    """Retorna todas as configurações de iluminação disponíveis.

    Sem ``include_settings`` a resposta continua ``[{name, description}]``.
    """
    if include_settings:
        return get_sorted_configs_with_settings(manager)
    return get_sorted_configs(manager)


@router.get("/configurations/favorites", response_model=FavoritesListResponse)
async def list_favorite_configurations(
    service: Annotated[SceneFavoritesService, Depends(get_scene_favorites_service)],
) -> FavoritesListResponse:
    """Nomes das cenas favoritas que existem hoje em ``setups.json``.

    Favoritos de cenas removidas/renomeadas ficam no banco, mas não aparecem.
    """
    return FavoritesListResponse(favorites=await service.list_existing())


@router.put(
    "/configurations/favorites/{name:path}",
    response_model=FavoriteStatusResponse,
    responses={404: {"description": "Configuração não encontrada"}},
)
async def add_favorite_configuration(
    name: str,
    service: Annotated[SceneFavoritesService, Depends(get_scene_favorites_service)],
) -> FavoriteStatusResponse:
    """Marca a cena como favorita (idempotente)."""
    try:
        await service.add(name)
    except FavoriteConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FavoriteStatusResponse(name=name, favorite=True)


@router.delete(
    "/configurations/favorites/{name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_favorite_configuration(
    name: str,
    service: Annotated[SceneFavoritesService, Depends(get_scene_favorites_service)],
) -> None:
    """Desmarca a cena (idempotente; nome desconhecido também devolve 204)."""
    await service.remove(name)


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
