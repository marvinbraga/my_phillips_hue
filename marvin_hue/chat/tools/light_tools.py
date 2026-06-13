"""
Light Tools - Ferramentas para controle de lâmpadas Philips Hue.

Define a factory ``build_light_tools(controller, manager)`` que cria as tools do
agente como closures (sem estado global), usando SOMENTE a API pública do
HueController.
"""

import json
from pathlib import Path
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.colors import Color


_DEFAULT_LOCATIONS_PATH = ".res/light_physical_locations.json"


def build_light_tools(
    controller: HueController,
    manager: LightSetupsManager,
    locations_path: str = _DEFAULT_LOCATIONS_PATH,
) -> list[BaseTool]:
    """Cria as 10 tools de iluminação com closures (sem estado global).

    Args:
        controller: HueController (usa SOMENTE métodos públicos).
        manager: LightSetupsManager.
        locations_path: caminho do JSON de localizações físicas (injetável p/ testes).

    Returns:
        Lista de 10 BaseTool prontas para create_agent.
    """

    # ----- schemas de argumentos (guiam o LLM) -----
    class _SetColorArgs(BaseModel):
        light_name: str = Field(description="Nome exato da lâmpada")
        red: int = Field(ge=0, le=255, description="Vermelho 0-255")
        green: int = Field(ge=0, le=255, description="Verde 0-255")
        blue: int = Field(ge=0, le=255, description="Azul 0-255")
        brightness: int = Field(default=200, ge=0, le=254, description="Brilho 0-254")

    class _ApplyConfigArgs(BaseModel):
        config_name: str = Field(description="Nome da configuração/preset de iluminação")
        transition_time: float = Field(default=0.0, ge=0, description="Transição (s)")

    class _ListConfigsArgs(BaseModel):
        search: str = Field(default="", description="Termo opcional para filtrar pelo nome")

    class _LightNameAllArgs(BaseModel):
        light_name: str = Field(default="all", description="Nome da lâmpada ou 'all' para todas")

    class _SetBrightnessArgs(BaseModel):
        light_name: str = Field(description="Nome da lâmpada ou 'all' para todas")
        brightness: int = Field(ge=0, le=100, description="Brilho em porcentagem (0-100)")

    class _SaveConfigArgs(BaseModel):
        # pattern ^\w+$ : letras (incl. acentuadas)/dígitos/underscore — rejeita
        # espaços e quebras de linha. Além de impor "sem espaços", fecha o vetor
        # de injeção de prompt via nome de preset reinjetado no system message.
        config_name: str = Field(
            pattern=r"^\w+$",
            description="Nome único, sem espaços (use underscores). Crie um nome "
            "criativo baseado nas cores atuais (ex: 'sunset_warm', 'natal_festivo')."
        )
        description: str = Field(
            description="Descrição de uma linha capturando o mood/ambiente das cores."
        )

    # ----- implementações (closures) -----
    def _list_lights() -> str:
        return f"Lâmpadas disponíveis: {', '.join(controller.list_lights())}"

    def _get_light_status() -> str:
        result_parts = ["Status das lâmpadas:"]
        for light in controller.get_lights_status():
            state = "Ligada" if light["on"] else "Desligada"
            color = light["color"]
            rgb_str = f"RGB({color['r']}, {color['g']}, {color['b']})"
            brightness = int((light["brightness"] / 254) * 100)
            reachable = "Sim" if light["reachable"] else "Não"
            result_parts.append(
                f"- {light['name']}: {state}, Cor: {rgb_str}, "
                f"Brilho: {brightness}%, Acessível: {reachable}"
            )
        return "\n".join(result_parts)

    def _set_light_color(light_name: str, red: int, green: int, blue: int,
                         brightness: int = 200) -> str:
        # Clamp defensivo (alguns valores podem ser derivados/computados).
        red, green, blue = (max(0, min(255, v)) for v in (red, green, blue))
        brightness = max(0, min(254, brightness))
        try:
            controller.set_light_color(light_name, Color(red, green, blue, brightness))
            return f"Cor de '{light_name}' -> RGB({red},{green},{blue}) brilho {brightness}."
        except Exception as e:  # noqa: BLE001
            return f"Erro ao alterar '{light_name}': {e}"

    def _apply_config(config_name: str, transition_time: float = 0.0) -> str:
        config = manager.get_config(config_name)
        if not config:
            available = [c.name for c in manager.configs[:10]]
            return (
                f"Configuração '{config_name}' não encontrada. "
                f"Algumas disponíveis: {', '.join(available)}..."
            )
        try:
            controller.apply_light_config(config, transition_time)
            return f"Configuração '{config_name}' aplicada! Descrição: {config.description}"
        except Exception as e:  # noqa: BLE001
            return f"Erro ao aplicar '{config_name}': {e}"

    def _list_configs(search: str = "") -> str:
        configs = manager.configs
        if search:
            s = search.lower()
            configs = [c for c in configs if s in c.name.lower()]
        if not configs:
            return f"Nenhuma configuração encontrada com o termo '{search}'."
        shown = sorted(configs, key=lambda c: c.name)[:15]
        result_parts = ["Configurações disponíveis:"]
        for config in shown:
            desc = (config.description[:60] + "...") if len(config.description) > 60 else config.description
            result_parts.append(f"- {config.name}: {desc}")
        if len(manager.configs) > 15:
            result_parts.append(f"\n(Mostrando 15 de {len(manager.configs)} configurações)")
        return "\n".join(result_parts)

    def _turn_off_lights(light_name: str = "all") -> str:
        if light_name.lower() == "all":
            controller.set_all(False)
            return "Todas as lâmpadas foram desligadas."
        if controller.turn_off(light_name):
            return f"Lâmpada '{light_name}' foi desligada."
        return f"Lâmpada '{light_name}' não encontrada."

    def _turn_on_lights(light_name: str = "all") -> str:
        if light_name.lower() == "all":
            controller.set_all(True)
            return "Todas as lâmpadas foram ligadas."
        if controller.turn_on(light_name):
            return f"Lâmpada '{light_name}' foi ligada."
        return f"Lâmpada '{light_name}' não encontrada."

    def _set_brightness(light_name: str, brightness: int) -> str:
        pct = max(0, min(100, brightness))
        hue_brightness = max(0, min(254, int((pct / 100) * 254)))
        if light_name.lower() == "all":
            controller.set_all_brightness(hue_brightness)
            return f"Brilho de todas as lâmpadas ajustado para {pct}%."
        if controller.set_brightness(light_name, hue_brightness):
            return f"Brilho da lâmpada '{light_name}' ajustado para {pct}%."
        return f"Lâmpada '{light_name}' não encontrada."

    def _save_current_config(config_name: str, description: str) -> str:
        if manager.get_config(config_name):
            return (
                f"Já existe uma configuração com o nome '{config_name}'. "
                "Escolha outro nome ou delete a existente primeiro."
            )
        from marvin_hue.basics import LightSetting, LightConfig

        settings = []
        for light in controller.get_lights_status():
            if light["on"] and light["reachable"]:
                c = light["color"]
                settings.append(
                    LightSetting(light["name"], Color(c["r"], c["g"], c["b"], light["brightness"]))
                )
        if not settings:
            return "Nenhuma lâmpada ligada encontrada. Ligue algumas lâmpadas primeiro."
        new_config = LightConfig(
            name=config_name, settings=settings,
            description=description or "Configuração salva pelo chat",
        )
        manager.configs.append(new_config)
        manager.save()
        names = ", ".join(s.light_name for s in settings)
        return (
            f"Configuração '{config_name}' salva com sucesso!\n"
            f"Descrição: {new_config.description}\nLâmpadas incluídas: {names}"
        )

    def _get_light_locations(light_name: str = "all") -> str:
        path = Path(locations_path)
        if not path.exists():
            return "Arquivo de localizações físicas não encontrado."
        # Try/except cobre TODA a leitura/parse/acesso (espelha _locations_block):
        # um JSON malformado/forma inesperada vira erro de tool, não exceção.
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lights = data.get("lights", []) if isinstance(data, dict) else []
            if light_name.lower() == "all":
                parts = ["Localizações físicas das lâmpadas:"]
                for light in lights:
                    if "name" not in light or "location" not in light:
                        continue
                    info = f"\n• {light['name']}: {light['location']}"
                    if "max_brightness_percent" in light:
                        info += f"\n  ⚠️ Intensidade máxima recomendada: {light['max_brightness_percent']}%"
                    if light.get("notes"):
                        info += f"\n  📝 {light['notes']}"
                    if "recommendations" in light:
                        info += "\n  💡 Recomendações:" + "".join(f"\n     - {r}" for r in light["recommendations"])
                    parts.append(info)
                env = data.get("environment_info", {})
                if "considerations" in env:
                    parts.append("\n⚙️ Considerações importantes:")
                    parts.extend(f"  • {c}" for c in env["considerations"])
                return "\n".join(parts)
            for light in lights:
                if light.get("name", "").lower() == light_name.lower():
                    info = f"Lâmpada '{light['name']}':\n• Localização: {light.get('location', '?')}"
                    if "max_brightness_percent" in light:
                        info += f"\n• ⚠️ Intensidade máxima recomendada: {light['max_brightness_percent']}%"
                    if light.get("notes"):
                        info += f"\n• Observação: {light['notes']}"
                    if "recommendations" in light:
                        info += "\n• Recomendações:" + "".join(f"\n  - {r}" for r in light["recommendations"])
                    return info
        except Exception as e:  # noqa: BLE001
            return f"Erro ao ler arquivo de localizações: {e}"
        return f"Lâmpada '{light_name}' não encontrada no arquivo de localizações."

    # ----- montagem das StructuredTools -----
    return [
        StructuredTool.from_function(
            func=_list_lights, name="list_lights",
            description="Lista todas as lâmpadas disponíveis no sistema.",
        ),
        StructuredTool.from_function(
            func=_get_light_status, name="get_light_status",
            description="Status atual de todas as lâmpadas (estado, cor, brilho).",
        ),
        StructuredTool.from_function(
            func=_set_light_color, name="set_light_color",
            description="Define cor RGB e brilho de UMA lâmpada.",
            args_schema=_SetColorArgs,
        ),
        StructuredTool.from_function(
            func=_apply_config, name="apply_config",
            description="Aplica uma configuração/preset de iluminação predefinida.",
            args_schema=_ApplyConfigArgs,
        ),
        StructuredTool.from_function(
            func=_list_configs, name="list_configs",
            description="Lista os presets de iluminação disponíveis (filtro opcional).",
            args_schema=_ListConfigsArgs,
        ),
        StructuredTool.from_function(
            func=_turn_off_lights, name="turn_off_lights",
            description="Desliga uma lâmpada específica ou todas ('all').",
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_turn_on_lights, name="turn_on_lights",
            description="Liga uma lâmpada específica ou todas ('all').",
            args_schema=_LightNameAllArgs,
        ),
        StructuredTool.from_function(
            func=_set_brightness, name="set_brightness",
            description="Ajusta o brilho (0-100%) de uma lâmpada ou de todas ('all').",
            args_schema=_SetBrightnessArgs,
        ),
        StructuredTool.from_function(
            func=_save_current_config, name="save_current_config",
            description="Salva o estado atual das lâmpadas como um novo preset.",
            args_schema=_SaveConfigArgs,
        ),
        StructuredTool.from_function(
            func=_get_light_locations, name="get_light_locations",
            description="Localização física das lâmpadas e restrições de intensidade.",
            args_schema=_LightNameAllArgs,
        ),
    ]
