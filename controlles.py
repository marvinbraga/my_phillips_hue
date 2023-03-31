from phue import Bridge, Light

from colors import Color
from setups import LightConfig
from utils import RGBtoXYAdapter


class HueController:
    def __init__(self, ip_address):
        self.bridge = Bridge(ip_address)
        self.bridge.connect()
        self.lights = self.bridge.get_light_objects()

    def set_light_color(self, light_name, color: Color):
        xy = RGBtoXYAdapter.convert(color.red, color.green, color.blue)
        light = self._get_light_by_name(light_name)
        if light:
            light.xy = xy
            light.brightness = color.brightness

    def apply_light_config(self, light_config: LightConfig):
        for setting in light_config.settings:
            self.set_light_color(setting.light_name, setting.color)

    def _get_light_by_name(self, light_name):
        for light in self.lights:
            if light.name == light_name:
                return light
        return None

    def list_groups(self):
        groups = self.bridge.groups
        return [(group.group_id, group.name) for group in groups]

    def list_lights(self):
        result = []
        for i in range(len(self.lights) - 1):
            l: Light = self.lights[i]
            result.append(l.name)
        return result
