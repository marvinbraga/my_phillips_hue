"""Preview de cena: como cada lâmpada de um ``LightConfig`` ficaria ao ser aplicada.

Função pura (sem I/O, sem bridge). Reproduz o caminho do ``HueController``:
- brilho efetivo via ``effective_hue_brightness`` (mesma regra do controller);
- ``enabled`` segundo a política de runtime (lâmpadas desabilitadas são puladas
  no apply);
- cor exibida passa por RGB → XY → RGB, o mesmo espaço de cor usado por
  ``HueController.get_lights_status``, para o preview casar com o card de
  estado real.
"""

from __future__ import annotations

from dataclasses import dataclass

from marvin_hue.basics import LightConfig
from marvin_hue.eye_safety import effective_hue_brightness, is_enabled_for_app
from marvin_hue.utils import ColorConverter


@dataclass(frozen=True)
class ScenePreviewLight:
    """Preview de uma lâmpada: cor configurada + resultado efetivo previsto."""

    light_name: str
    color: dict[str, int]
    r: int
    g: int
    b: int
    brightness: int
    enabled: bool


def build_scene_preview(config: LightConfig) -> list[ScenePreviewLight]:
    """Monta o preview de cada ``LightSetting`` da cena, na ordem configurada."""
    preview: list[ScenePreviewLight] = []
    for setting in config.settings:
        color = setting.color
        brightness = effective_hue_brightness(setting.light_name, color.brightness)
        # rgb_to_xy devolve o ponto branco para (0, 0, 0); não levanta.
        xy = ColorConverter.rgb_to_xy(color.red, color.green, color.blue)
        r, g, b = ColorConverter.xy_to_rgb(xy, brightness)
        preview.append(
            ScenePreviewLight(
                light_name=setting.light_name,
                color=color.to_dict(),
                r=r,
                g=g,
                b=b,
                brightness=brightness,
                enabled=is_enabled_for_app(setting.light_name),
            )
        )
    return preview
