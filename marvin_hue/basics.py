import json
import os
from json import JSONDecodeError

from marvin_hue.colors import Color


class LightSetting:
    """
    Classe para guardar a configuração de uma lâmpada.
    """

    def __init__(self, light_name, color: Color):
        self.light_name = light_name
        self.color = color

    def to_dict(self):
        return {
            "light_name": self.light_name,
            "color": self.color.to_dict(),
        }


class LightConfig:
    """
    Classe para guardar a configuração de várias lâmpadas para um ambiente.
    """

    def __init__(self, name, settings, description=""):
        self.name = name
        self.description = description
        self.settings: list[LightSetting] = settings

    def __str__(self):
        return self.name

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "settings": [s.to_dict() for s in self.settings]
        }


class LightSetupsManager:
    """
    Classe para gerenciar várias configurações de lâmpadas para um ambiente.
    """

    def __init__(self, filename: str):
        self._filename = filename
        self._data = {"setups": []}
        self._configs: list[LightConfig] = []
        self.load().update()

    @property
    def data(self):
        return self._data

    @property
    def configs(self):
        return self._configs

    def get_config(self, name):
        return next((cfg for cfg in self._configs if cfg.name == name), None)

    def load(self):
        if not os.path.exists(self._filename):
            raise FileNotFoundError(f"{self._filename} does not exist.")
        try:
            with open(self._filename, "r") as f:
                self._data = json.load(f)
        except (IOError, JSONDecodeError) as e:
            print(f"An error occurred while reading the file: {str(e)}.")
        return self

    def update(self):
        self._configs = []
        for config in self._data.get("setups", []):
            light_settings: list[LightSetting] = [
                LightSetting(setting["light_name"], Color(**setting["color"]))
                for setting in config["settings"]
            ]
            self._configs.append(LightConfig(config["name"], light_settings, config["description"]))
        return self

    def save(self):
        try:
            with open(self._filename, "w") as f:
                json.dump(
                    {"setups": [config.to_dict() for config in self._configs]}, f, indent=2, ensure_ascii=False
                )
        except IOError as e:
            print(f"An error occurred while writing to the file: {str(e)}")
        return self
