from phue import Bridge, Light

from marvin_hue.colors import Color
from marvin_hue.basics import LightConfig
from marvin_hue.utils import RGBtoXYAdapter


class HueController:
    def __init__(self, ip_address):
        self.bridge = Bridge(ip_address)
        self.bridge.connect()
        self.lights = self.bridge.get_light_objects()

    def set_light_color(self, light_name, color: Color) -> Light:
        xy = RGBtoXYAdapter.convert(color.red, color.green, color.blue)
        light = self._get_light_by_name(light_name)
        light.xy = xy
        light.brightness = color.brightness
        return light

    def apply_light_config(self, light_config: LightConfig, transition_time_secs=0):
        for setting in light_config.settings:
            light = self.set_light_color(setting.light_name, setting.color)
            if transition_time_secs:
                light.transitiontime = transition_time_secs * 10
                light.on = True
        return self

    def _get_light_by_name(self, light_name):
        for light in self.lights:
            if light.name == light_name:
                return light
        return None

    def list_groups(self):
        groups = self.bridge.groups
        return [(group.group_id, group.name) for group in groups]

    def list_lights(self):
        return [light.name for light in self.lights]

    def get_lights_status(self) -> list[dict]:
        """Retorna o estado atual de todas as lâmpadas com cores RGB."""
        lights_status = []
        for light in self.lights:
            try:
                status = {
                    "name": light.name,
                    "on": light.on,
                    "brightness": light.brightness if light.on else 0,
                    "reachable": light.reachable,
                }
                # Converter XY para RGB se a lâmpada estiver ligada e tiver cor
                if light.on and hasattr(light, 'xy') and light.xy:
                    rgb = self._xy_to_rgb(light.xy, light.brightness)
                    status["color"] = {
                        "r": rgb[0],
                        "g": rgb[1],
                        "b": rgb[2]
                    }
                else:
                    status["color"] = {"r": 50, "g": 50, "b": 50}  # Cinza quando desligada
                lights_status.append(status)
            except Exception:
                pass  # Ignora lâmpadas com erro
        return lights_status

    def _xy_to_rgb(self, xy: tuple, brightness: int = 254) -> tuple[int, int, int]:
        """Converte coordenadas XY do Hue para RGB."""
        x, y = xy
        z = 1.0 - x - y

        # Evitar divisão por zero
        if y == 0:
            y = 0.00001

        Y = brightness / 254.0
        X = (Y / y) * x
        Z = (Y / y) * z

        # Converter XYZ para RGB
        r = X * 1.656492 - Y * 0.354851 - Z * 0.255038
        g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152
        b = X * 0.051713 - Y * 0.121364 + Z * 1.011530

        # Aplicar correção gamma
        def gamma_correct(value):
            if value <= 0.0031308:
                return 12.92 * value
            return (1.0 + 0.055) * pow(value, (1.0 / 2.4)) - 0.055

        r = gamma_correct(r)
        g = gamma_correct(g)
        b = gamma_correct(b)

        # Normalizar e converter para 0-255
        max_val = max(r, g, b, 1)
        r = int(max(0, min(255, (r / max_val) * 255)))
        g = int(max(0, min(255, (g / max_val) * 255)))
        b = int(max(0, min(255, (b / max_val) * 255)))

        return (r, g, b)
