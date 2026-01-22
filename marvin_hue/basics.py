import json
import os
import time
from json import JSONDecodeError
from typing import Any

import aiofiles

from marvin_hue.colors import Color
from marvin_hue.logging_config import get_logger

logger = get_logger("basics")


class LightSetting:
    """
    Classe para guardar a configuração de uma lâmpada.
    """

    def __init__(self, light_name: str, color: Color) -> None:
        self.light_name = light_name
        self.color = color

    def to_dict(self) -> dict[str, str | dict[str, int]]:
        return {
            "light_name": self.light_name,
            "color": self.color.to_dict(),
        }


class LightConfig:
    """
    Classe para guardar a configuração de várias lâmpadas para um ambiente.
    """

    def __init__(self, name: str, settings: list[LightSetting], description: str = "") -> None:
        self.name = name
        self.description = description
        self.settings: list[LightSetting] = settings

    def __str__(self) -> str:
        return self.name

    def to_dict(self) -> dict[str, str | list[dict[str, str | dict[str, int]]]]:
        return {
            "name": self.name,
            "description": self.description,
            "settings": [s.to_dict() for s in self.settings]
        }


class LightSetupsManager:
    """
    Classe para gerenciar várias configurações de lâmpadas para um ambiente.

    Performance optimizations:
    - Cache de leitura de JSON com TTL de 60 segundos
    - Invalidação automática do cache se o arquivo for modificado (check mtime)
    - Reduz I/O repetido em chamadas frequentes
    """

    # Cache class-level para compartilhar entre instâncias
    _cache: dict[str, tuple[dict[str, Any], float, float]] = {}  # filename -> (data, timestamp, mtime)
    _cache_ttl: float = 60.0  # 60 segundos

    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._data: dict[str, Any] = {"setups": []}
        self._configs: list[LightConfig] = []
        self.load().update()

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @property
    def configs(self) -> list[LightConfig]:
        return self._configs

    def get_config(self, name: str) -> LightConfig | None:
        return next((cfg for cfg in self._configs if cfg.name == name), None)

    def load(self) -> "LightSetupsManager":
        """
        Carrega configurações do arquivo JSON com cache inteligente.

        Otimizações:
        - Cache com TTL de 60 segundos
        - Invalidação automática se o arquivo foi modificado (mtime check)
        - Reduz I/O em chamadas repetidas
        """
        if not os.path.exists(self._filename):
            logger.error(f"File not found: {self._filename}")
            raise FileNotFoundError(f"{self._filename} does not exist.")

        # Verifica cache
        current_time = time.time()
        file_mtime = os.path.getmtime(self._filename)

        if self._filename in self._cache:
            cached_data, cache_time, cached_mtime = self._cache[self._filename]
            cache_age = current_time - cache_time

            # Cache hit: válido se não expirou e arquivo não foi modificado
            if cache_age < self._cache_ttl and cached_mtime == file_mtime:
                self._data = cached_data
                logger.debug(f"Cache hit for {self._filename} (age: {cache_age:.1f}s)")
                return self
            else:
                logger.debug(f"Cache miss for {self._filename} (expired or file modified)")

        # Cache miss: carrega do arquivo
        try:
            with open(self._filename, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            # Atualiza cache
            self._cache[self._filename] = (self._data, current_time, file_mtime)

            logger.info(f"Successfully loaded {len(self._data.get('setups', []))} configurations from {self._filename}")
        except (IOError, JSONDecodeError) as e:
            logger.error(f"Error reading file {self._filename}: {str(e)}", exc_info=True)
        return self

    def update(self) -> "LightSetupsManager":
        self._configs = []
        for config in self._data.get("setups", []):
            light_settings: list[LightSetting] = [
                LightSetting(setting["light_name"], Color(**setting["color"]))
                for setting in config["settings"]
            ]
            self._configs.append(LightConfig(config["name"], light_settings, config["description"]))
        return self

    def save(self) -> "LightSetupsManager":
        """
        Salva configurações no arquivo JSON (versão síncrona).

        Para código assíncrono, use save_async() que oferece melhor performance.
        Mantido para compatibilidade retroativa.
        """
        try:
            with open(self._filename, "w", encoding="utf-8") as f:
                json.dump(
                    {"setups": [config.to_dict() for config in self._configs]}, f, indent=2, ensure_ascii=False
                )

            # Invalida cache após salvar
            if self._filename in self._cache:
                del self._cache[self._filename]

            logger.info(f"Successfully saved {len(self._configs)} configurations to {self._filename}")
        except IOError as e:
            logger.error(f"Error writing to file {self._filename}: {str(e)}", exc_info=True)
        return self

    async def load_async(self) -> "LightSetupsManager":
        """
        Carrega configurações do arquivo JSON de forma assíncrona.

        Otimizações:
        - I/O não bloqueante com aiofiles
        - Cache com TTL e mtime check (compartilhado com versão síncrona)
        - Ideal para uso em aplicações async (FastAPI, etc.)
        """
        if not os.path.exists(self._filename):
            logger.error(f"File not found: {self._filename}")
            raise FileNotFoundError(f"{self._filename} does not exist.")

        # Verifica cache
        current_time = time.time()
        file_mtime = os.path.getmtime(self._filename)

        if self._filename in self._cache:
            cached_data, cache_time, cached_mtime = self._cache[self._filename]
            cache_age = current_time - cache_time

            # Cache hit
            if cache_age < self._cache_ttl and cached_mtime == file_mtime:
                self._data = cached_data
                logger.debug(f"Cache hit for {self._filename} (age: {cache_age:.1f}s)")
                return self
            else:
                logger.debug(f"Cache miss for {self._filename} (expired or file modified)")

        # Cache miss: carrega do arquivo de forma assíncrona
        try:
            async with aiofiles.open(self._filename, "r", encoding="utf-8") as f:
                content = await f.read()
                self._data = json.loads(content)

            # Atualiza cache
            self._cache[self._filename] = (self._data, current_time, file_mtime)

            logger.info(f"Successfully loaded (async) {len(self._data.get('setups', []))} configurations from {self._filename}")
        except (IOError, JSONDecodeError) as e:
            logger.error(f"Error reading file {self._filename}: {str(e)}", exc_info=True)
        return self

    async def save_async(self) -> "LightSetupsManager":
        """
        Salva configurações no arquivo JSON de forma assíncrona.

        Otimizações:
        - I/O não bloqueante com aiofiles
        - Ideal para uso em aplicações async (FastAPI, etc.)
        - Invalida cache automaticamente
        """
        try:
            data = {"setups": [config.to_dict() for config in self._configs]}
            content = json.dumps(data, indent=2, ensure_ascii=False)

            async with aiofiles.open(self._filename, "w", encoding="utf-8") as f:
                await f.write(content)

            # Invalida cache após salvar
            if self._filename in self._cache:
                del self._cache[self._filename]

            logger.info(f"Successfully saved (async) {len(self._configs)} configurations to {self._filename}")
        except IOError as e:
            logger.error(f"Error writing to file {self._filename}: {str(e)}", exc_info=True)
        return self
