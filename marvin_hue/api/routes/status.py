"""
Status Routes
Endpoints para status da bridge e das lâmpadas.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from marvin_hue.controllers import HueController
from marvin_hue.api.dependencies import get_hue_controller

router = APIRouter(tags=["Status"])


@router.get("/api/bridge/status")
async def bridge_status(hue: HueController = Depends(get_hue_controller)):
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


@router.get("/api/lights/status")
async def lights_status(hue: HueController = Depends(get_hue_controller)):
    """Retorna o estado atual de todas as lâmpadas com suas cores."""
    try:
        loop = asyncio.get_event_loop()
        status = await loop.run_in_executor(None, hue.get_lights_status)
        return {"lights": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
