import asyncio
import json
import os
import threading
import time
from json import JSONDecodeError
from typing import Any

import aiofiles

from marvin_hue.atomic_io import write_json_atomic
from marvin_hue.colors import Color
from marvin_hue.logging_config import get_logger

logger = get_logger("basics")


class DuplicateConfigError(ValueError):
    """Já existe uma cena com esse nome (comparação sem maiúsculas)."""


class ConfigNotFoundError(LookupError):
    """Nenhuma cena com esse nome exato (comparação com maiúsculas)."""


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

    def __init__(
        self, name: str, settings: list[LightSetting], description: str = ""
    ) -> None:
        self.name = name
        self.description = description
        self.settings: list[LightSetting] = settings

    def __str__(self) -> str:
        return self.name

    def to_dict(self) -> dict[str, str | list[dict[str, str | dict[str, int]]]]:
        return {
            "name": self.name,
            "description": self.description,
            "settings": [s.to_dict() for s in self.settings],
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
    _cache: dict[
        str, tuple[dict[str, Any], float, float]
    ] = {}  # filename -> (data, timestamp, mtime)
    _cache_ttl: float = 60.0  # 60 segundos

    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._data: dict[str, Any] = {"setups": []}
        self._configs: list[LightConfig] = []
        # Serializa check-append-save (tools do chat rodam em threads do executor).
        self._lock = threading.RLock()
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
                logger.debug(
                    f"Cache miss for {self._filename} (expired or file modified)"
                )

        # Cache miss: carrega do arquivo
        try:
            with open(self._filename, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            # Atualiza cache
            self._cache[self._filename] = (self._data, current_time, file_mtime)

            logger.info(
                f"Successfully loaded {len(self._data.get('setups', []))} configurations from {self._filename}"
            )
        except (IOError, JSONDecodeError) as e:
            logger.exception(
                f"Error reading file {self._filename}: {str(e)}"
            )
        return self

    def update(self) -> "LightSetupsManager":
        self._configs = []
        for config in self._data.get("setups", []):
            light_settings: list[LightSetting] = [
                LightSetting(setting["light_name"], Color(**setting["color"]))
                for setting in config["settings"]
            ]
            self._configs.append(
                LightConfig(config["name"], light_settings, config["description"])
            )
        return self

    def save(self) -> "LightSetupsManager":
        """Salva as configurações no JSON de forma atômica (temp + ``os.replace``).

        Raises:
            OSError: a escrita falhou; o arquivo anterior fica intacto.
        """
        with self._lock:
            payload = {"setups": [config.to_dict() for config in self._configs]}
            try:
                write_json_atomic(self._filename, payload)
            except OSError as e:
                logger.exception(f"Error writing to file {self._filename}: {e}")
                raise
            # Invalida cache após salvar
            self._cache.pop(self._filename, None)
            logger.info(
                f"Successfully saved {len(self._configs)} configurations to {self._filename}"
            )
        return self

    def add_config(self, config: LightConfig) -> "LightSetupsManager":
        """Acrescenta uma cena e persiste, sob lock (check-append-save atômico).

        Raises:
            DuplicateConfigError: já existe cena com o mesmo nome (sem
                diferenciar maiúsculas).
            OSError: a gravação falhou; a cena é removida da memória.
        """
        with self._lock:
            key = config.name.casefold()
            if any(c.name.casefold() == key for c in self._configs):
                raise DuplicateConfigError(config.name)
            self._configs.append(config)
            try:
                self.save()
            except Exception:
                self._configs.remove(config)
                raise
        return self

    def remove_config(self, name: str) -> int:
        """Remove todas as cenas com o nome exato e persiste, sob lock.

        Returns:
            Quantas entradas foram removidas (duplicatas legadas contam).

        Raises:
            ConfigNotFoundError: nenhuma cena com esse nome exato.
            OSError: a gravação falhou; a lista anterior é restaurada.
        """
        with self._lock:
            previous = list(self._configs)
            remaining = [c for c in previous if c.name != name]
            removed = len(previous) - len(remaining)
            if removed == 0:
                raise ConfigNotFoundError(name)
            # Slice assignment: quem guardou ``configs`` continua vendo a lista.
            self._configs[:] = remaining
            try:
                self.save()
            except Exception:
                self._configs[:] = previous
                raise
        logger.info(f"Removed configuration {name!r} (entries={removed})")
        return removed

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
                logger.debug(
                    f"Cache miss for {self._filename} (expired or file modified)"
                )

        # Cache miss: carrega do arquivo de forma assíncrona
        try:
            async with aiofiles.open(self._filename, "r", encoding="utf-8") as f:
                content = await f.read()
                self._data = json.loads(content)

            # Atualiza cache
            self._cache[self._filename] = (self._data, current_time, file_mtime)

            logger.info(
                f"Successfully loaded (async) {len(self._data.get('setups', []))} configurations from {self._filename}"
            )
        except (IOError, JSONDecodeError) as e:
            logger.exception(
                f"Error reading file {self._filename}: {str(e)}"
            )
        return self

    async def save_async(self) -> "LightSetupsManager":
        """Versão assíncrona de :meth:`save` (atômica; roda em thread).

        Raises:
            OSError: a escrita falhou; o arquivo anterior fica intacto.
        """
        await asyncio.to_thread(self.save)
        return self
