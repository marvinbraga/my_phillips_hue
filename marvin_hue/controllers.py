from typing import Any

from phue import Bridge, Light

from marvin_hue.apply_result import ApplyResult
from marvin_hue.basics import LightConfig, LightSetting
from marvin_hue.colors import Color
from marvin_hue.eye_safety import effective_hue_brightness, is_enabled_for_app
from marvin_hue.logging_config import get_logger
from marvin_hue.utils import ColorConverter

logger = get_logger("controllers")


def _bridge_error_descriptions(reply: Any) -> list[str]:
    """Extract ``error.description`` entries from a phue ``set_light`` reply."""
    errors: list[str] = []
    if not isinstance(reply, list):
        return errors
    for request_result in reply:
        items = request_result if isinstance(request_result, list) else [request_result]
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("error"), dict):
                errors.append(str(item["error"].get("description", "erro da bridge")))
    return errors


def _uncached_light_name(light: Any) -> str:
    """Name for a light missing from the cache (rare: one GET, never raises)."""
    try:
        return str(light.name)
    except Exception:  # noqa: BLE001 — bridge down: fall back to the id
        return str(getattr(light, "light_id", "?"))


class HueController:
    """
    Controlador para interação com Philips Hue Bridge.

    Attributes:
        bridge: Instância da conexão com a bridge
        lights: Lista de objetos Light disponíveis
    """

    def __init__(self, ip_address: str):
        """
        Inicializa o controlador.

        Args:
            ip_address: Endereço IP da Philips Hue Bridge

        Raises:
            ValueError: Se o IP for inválido
            ConnectionError: Se não conseguir conectar à bridge
        """
        if not ip_address or not isinstance(ip_address, str):
            raise ValueError(f"IP address inválido: {ip_address}")

        logger.info(f"Initializing Hue Controller with bridge IP: {ip_address}")
        try:
            self.bridge = Bridge(ip_address)
            self.bridge.connect()
            self.lights = self.bridge.get_light_objects()
            self._light_cache: dict[str, Light] = {}
            self._refresh_cache()
            logger.info(f"Connected to Hue Bridge. Found {len(self.lights)} lights")
        except Exception as e:
            logger.error(f"Erro ao conectar à bridge {ip_address}: {e}")
            raise ConnectionError(f"Não foi possível conectar à bridge Hue: {e}") from e

    def set_light_color(self, light_name: str, color: Color) -> None:
        """
        Define a cor de uma lâmpada específica.

        Args:
            light_name: Nome da lâmpada
            color: Objeto Color com RGB e brightness

        Raises:
            ValueError: Se a lâmpada não for encontrada ou valores forem inválidos
        """
        logger.debug(
            f"Setting light '{light_name}' to RGB({color.red}, {color.green}, "
            f"{color.blue}), brightness={color.brightness}"
        )

        light = self._require_light(light_name)

        try:
            # Converte RGB para XY (mesma conversão usada pelo preview de cena)
            xy = ColorConverter.rgb_to_xy(color.red, color.green, color.blue)

            # Valida coordenadas XY
            if not self._validate_xy(xy):
                logger.warning(f"Coordenadas XY fora do gamut: {xy}, usando valores corrigidos")
                xy = self._clamp_xy(xy)

            # Aplica as configurações.
            # Invariante ocular (defesa em profundidade): clampa o brilho na
            # ORIGEM, cobrindo presets (apply_light_config -> set_light_color),
            # screen-mirror e tools diretas. Escala "hue" (0-254).
            light.xy = xy
            light.brightness = effective_hue_brightness(light_name, color.brightness)
            logger.debug(f"Successfully applied color to '{light_name}'")

        except ValueError as e:
            logger.error(f"Erro ao definir cor para '{light_name}': {e}")
            raise
        except Exception as e:
            logger.error(f"Erro inesperado ao definir cor para '{light_name}': {e}")
            raise RuntimeError(f"Erro ao aplicar cor: {e}") from e

    def set_transition_time(self, light_name: str, tenths: int) -> None:
        """Set Hue transition time in tenths of a second (phue ``transitiontime``).

        Hides ``phue.Light`` from callers that previously mutated the object
        returned by ``set_light_color``.
        """
        if tenths < 0:
            raise ValueError(f"Transition time negativo: {tenths}")
        light = self._require_light(light_name)
        light.transitiontime = int(tenths)
        logger.debug(f"Transition time for '{light_name}' set to {tenths} tenths")

    def apply_light_config(
        self, light_config: LightConfig, transition_time_secs: float = 0
    ) -> ApplyResult:
        """Apply a full lighting configuration, one light at a time.

        Disabled lights (``enabled_for_app=false``) are skipped and omitted
        from both ``applied`` and ``failed``. Per-light errors are recorded
        and do not abort the remaining settings.

        Returns:
            ApplyResult: names that succeeded and (name, error) pairs that failed.
        """
        if not light_config or not hasattr(light_config, "settings"):
            raise ValueError("LightConfig inválido")

        if transition_time_secs < 0:
            logger.warning(f"Transition time negativo ({transition_time_secs}), usando 0")
            transition_time_secs = 0

        logger.info(
            f"Applying configuration '{light_config.name}' with "
            f"{len(light_config.settings)} lights "
            f"(transition: {transition_time_secs}s)"
        )

        applied: list[str] = []
        failed: list[tuple[str, str]] = []
        for setting in light_config.settings:
            if not is_enabled_for_app(setting.light_name):
                logger.debug(
                    f"Skipping disabled light '{setting.light_name}' in apply_light_config"
                )
                continue
            try:
                self._apply_one_setting(setting, transition_time_secs)
            except ValueError as e:
                logger.warning(f"Erro ao aplicar configuração para '{setting.light_name}': {e}")
                failed.append((setting.light_name, str(e)))
            except Exception as e:  # noqa: BLE001 — isolate per-light failures
                logger.error(
                    f"Erro inesperado ao aplicar configuração para '{setting.light_name}': {e}"
                )
                failed.append((setting.light_name, str(e)))
            else:
                applied.append(setting.light_name)

        result = ApplyResult(applied=tuple(applied), failed=tuple(failed))
        if result.failed:
            logger.warning(
                f"Configuração aplicada com {len(result.failed)} erro(s): {list(result.failed)}"
            )
        else:
            logger.info(f"Configuration '{light_config.name}' applied successfully")
        return result

    def _apply_one_setting(self, setting: LightSetting, transition_time_secs: float) -> None:
        """Apply one setting; raises on failure (caught by apply_light_config)."""
        self.set_light_color(setting.light_name, setting.color)
        if transition_time_secs > 0:
            self.set_transition_time(setting.light_name, int(transition_time_secs * 10))
        self.turn_on(setting.light_name)

    def _require_light(self, light_name: str) -> Light:
        light = self._get_light_by_name(light_name)
        if light is None:
            logger.warning(f"Light '{light_name}' not found")
            raise ValueError(
                f"Lâmpada '{light_name}' não encontrada. Lâmpadas disponíveis: {self.list_lights()}"
            )
        if not is_enabled_for_app(light_name):
            logger.warning(f"Light '{light_name}' desabilitada no app (enabled_for_app=false)")
            raise ValueError(f"Lâmpada '{light_name}' desabilitada no app (enabled_for_app=false)")
        return light

    def _refresh_cache(self) -> None:
        """
        Atualiza o cache de lâmpadas por nome.

        Este método constrói um dicionário para lookup O(1) de lâmpadas por nome.
        Deve ser chamado após mudanças na topologia da bridge (adicionar/remover luzes).
        """
        self._light_cache = {light.name: light for light in self.lights}
        logger.debug(f"Light cache refreshed with {len(self._light_cache)} lights")

    def refresh_lights(self) -> None:
        """
        Atualiza a lista de lâmpadas e o cache.

        Use este método quando a topologia da bridge mudar
        (ex: novas lâmpadas adicionadas ou removidas).
        """
        logger.info("Refreshing lights from bridge")
        self.lights = self.bridge.get_light_objects()
        self._refresh_cache()
        logger.info(f"Lights refreshed. Found {len(self.lights)} lights")

    def _get_light_by_name(self, light_name: str) -> Light | None:
        """
        Busca lâmpada por nome usando cache O(1).

        Args:
            light_name: Nome da lâmpada

        Returns:
            Light | None: Objeto da lâmpada ou None se não encontrada
        """
        return self._light_cache.get(light_name)

    def turn_on(self, light_name: str) -> bool:
        """Liga uma lâmpada pelo nome. Retorna False se não encontrada ou desabilitada."""
        if not is_enabled_for_app(light_name):
            logger.debug(f"turn_on skipped: '{light_name}' desabilitada no app")
            return False
        light = self._get_light_by_name(light_name)
        if light is None:
            return False
        light.on = True
        return True

    def turn_off(self, light_name: str) -> bool:
        """Desliga uma lâmpada pelo nome. Retorna False se não encontrada ou desabilitada."""
        if not is_enabled_for_app(light_name):
            logger.debug(f"turn_off skipped: '{light_name}' desabilitada no app")
            return False
        light = self._get_light_by_name(light_name)
        if light is None:
            return False
        light.on = False
        return True

    def turn_off_with_transition(self, light_name: str, tenths: int) -> bool:
        """Desliga com transição one-shot (``set_light(..., transitiontime=)``).

        Não altera ``Light.transitiontime`` (persistente no phue: vazaria para
        todo comando seguinte daquela lâmpada). ``tenths == 0`` omite o campo.
        Retorna False se a lâmpada não existir ou estiver desabilitada no app;
        levanta ``RuntimeError`` se a bridge responder com erro.
        """
        if tenths < 0:
            raise ValueError(f"Transition time negativo: {tenths}")
        if not is_enabled_for_app(light_name):
            logger.debug(f"turn_off skipped: '{light_name}' desabilitada no app")
            return False
        light = self._get_light_by_name(light_name)
        if light is None:
            return False
        kwargs: dict[str, Any] = {"transitiontime": int(tenths)} if tenths else {}
        reply = self.bridge.set_light(light.light_id, "on", False, **kwargs)
        errors = _bridge_error_descriptions(reply)
        if errors:
            raise RuntimeError("; ".join(errors))
        if tenths:
            # Espelha o workaround do setter ``Light.on`` do phue (desligar com
            # transição faz a lâmpada voltar com bri=1): o próximo
            # ``light.on = True`` reaplica o brilho guardado.
            light._on = False
            light._reset_bri_after_on = True
        return True

    def set_brightness(self, light_name: str, hue_brightness: int) -> bool:
        """Define o brilho (0-254) de uma lâmpada, clampado pelo invariante ocular.

        Retorna False se a lâmpada não for encontrada ou estiver desabilitada no app.
        """
        if not is_enabled_for_app(light_name):
            logger.debug(f"set_brightness skipped: '{light_name}' desabilitada no app")
            return False
        light = self._get_light_by_name(light_name)
        if light is None:
            return False
        light.brightness = effective_hue_brightness(light_name, hue_brightness)
        return True

    def set_all(self, on: bool) -> None:
        """Liga/desliga lâmpadas habilitadas no app."""
        for light in self.lights:
            if not is_enabled_for_app(light.name):
                logger.debug(f"set_all skipped: '{light.name}' desabilitada no app")
                continue
            light.on = on

    def set_all_brightness(self, hue_brightness: int) -> None:
        """Brilho de lâmpadas habilitadas — clampado POR LÂMPADA (fecha o furo "all")."""
        for light in self.lights:
            self.set_brightness(light.name, hue_brightness)

    def _validate_xy(self, xy: tuple[float, float]) -> bool:
        """
        Valida se coordenadas XY estão dentro do gamut válido.

        Args:
            xy: Tupla com coordenadas (x, y)

        Returns:
            bool: True se válidas, False caso contrário
        """
        x, y = xy
        return (0.0 <= x <= 1.0) and (0.0 <= y <= 1.0) and (x + y <= 1.0)

    def _clamp_xy(self, xy: tuple[float, float]) -> tuple[float, float]:
        """
        Corrige coordenadas XY para valores válidos.

        Args:
            xy: Tupla com coordenadas (x, y)

        Returns:
            tuple[float, float]: Coordenadas corrigidas
        """
        x, y = xy
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        if x + y > 1.0:
            total = x + y
            x = x / total
            y = y / total
        return (x, y)

    def list_groups(self) -> list[tuple[Any, Any]]:
        """
        Lista todos os grupos de lâmpadas.

        Returns:
            list[tuple[Any, Any]]: Lista de tuplas (id, nome)
        """
        try:
            groups = self.bridge.groups
            return [(group.group_id, group.name) for group in groups]
        except Exception as e:
            logger.error(f"Erro ao listar grupos: {e}")
            return []

    def list_lights(self) -> list[str]:
        """
        Lista nomes de todas as lâmpadas.

        Returns:
            list[str]: Lista de nomes das lâmpadas (do cache; sem GET na bridge —
            cada ``Light.name`` do phue é um GET). Use ``refresh_lights()`` se a
            topologia mudou.
        """
        return list(self._light_cache)

    def list_bridge_lights(self) -> list[dict[str, Any]]:
        """Inventory for catalog sync: name + optional stable bridge light id.

        Field mapping:
        - name ← light.name
        - bridge_light_id ← uniqueid (preferred, stable) else light_id (volatile)

        Does not hit extra HTTP if lights already cached on the controller.
        Call refresh_lights() first if topology may have changed.
        """
        inventory: list[dict[str, Any]] = []
        for light in self.lights:
            bridge_id: str | None = None
            uniqueid = getattr(light, "uniqueid", None)
            if uniqueid:
                bridge_id = str(uniqueid)
            elif hasattr(light, "light_id") and light.light_id is not None:
                bridge_id = str(light.light_id)
            inventory.append(
                {
                    "name": light.name,
                    "bridge_light_id": bridge_id,
                }
            )
        return inventory

    def get_lights_status(self) -> list[dict[str, Any]]:
        """Estado atual de todas as lâmpadas (cores RGB) com UM ``GET /lights/``.

        Cada propriedade de ``phue.Light`` é um GET na bridge (~5 por lâmpada);
        aqui lemos o inventário completo uma vez e montamos a mesma forma de
        saída, na ordem de ``self.lights``. Lâmpada ausente da resposta ou com
        chave de estado faltando vira linha de erro (como antes). Falha do GET
        único propaga — quem chama decide (ex.: ``LightsOffService``).
        """
        bridge_lights = self.bridge.get_light()
        cached_names = {id(light): name for name, light in self._light_cache.items()}
        lights_status: list[dict[str, Any]] = []
        for light in self.lights:
            name = cached_names.get(id(light))
            try:
                entry = bridge_lights[str(light.light_id)]
                state = entry["state"]
                if name is None:
                    name = str(entry["name"])
                is_on = state["on"]
                # Hidrata o cache interno do phue como as leituras por
                # propriedade faziam: o workaround do setter ``Light.on``
                # (bri=1 após desligar com transição) reaplica ``_brightness``.
                light._on = is_on
                if "bri" in state:
                    light._brightness = state["bri"]
                brightness = state["bri"] if is_on else 0
                status: dict[str, Any] = {
                    "name": str(entry.get("name", name)),
                    "on": is_on,
                    "brightness": brightness,
                    "reachable": state["reachable"],
                }
                xy = state.get("xy")
                if is_on and xy:
                    rgb = ColorConverter.xy_to_rgb(xy, brightness)
                    status["color"] = {"r": rgb[0], "g": rgb[1], "b": rgb[2]}
                else:
                    status["color"] = {"r": 50, "g": 50, "b": 50}  # Cinza quando desligada
                lights_status.append(status)
            except Exception as e:  # noqa: BLE001 — uma lâmpada não derruba o status
                display = name if name is not None else _uncached_light_name(light)
                logger.warning(f"Error getting status for light '{display}': {e!s}")
                lights_status.append(
                    {
                        "name": display,
                        "on": False,
                        "brightness": 0,
                        "reachable": False,
                        "color": {"r": 50, "g": 50, "b": 50},
                        "error": str(e),
                    }
                )
        return lights_status

    def _xy_to_rgb(self, xy: tuple[float, float], brightness: int = 254) -> tuple[int, int, int]:
        """
        DEPRECATED: Use ColorConverter.xy_to_rgb() instead.

        Mantido para compatibilidade retroativa.
        """
        return ColorConverter.xy_to_rgb(xy, brightness)
