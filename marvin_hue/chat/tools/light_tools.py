"""
Light Tools - Ferramentas para controle de lâmpadas Philips Hue.

Define ferramentas que podem ser usadas pelo agente ReAct para
interagir com as lâmpadas através do HueController.
"""

import json
from pathlib import Path
from typing import Optional, Annotated
from langchain_core.tools import tool, BaseTool, StructuredTool
from pydantic import BaseModel, Field

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.colors import Color


# Referências globais para controller e manager
# Serão configuradas pelo agente na inicialização
_hue_controller: Optional[HueController] = None
_setups_manager: Optional[LightSetupsManager] = None


def configure_tools(controller: HueController, manager: LightSetupsManager) -> None:
    """Configura as referências globais para o controller e manager.

    Args:
        controller: Instância do HueController
        manager: Instância do LightSetupsManager
    """
    global _hue_controller, _setups_manager
    _hue_controller = controller
    _setups_manager = manager


def _get_controller() -> HueController:
    """Obtém o controller configurado."""
    if _hue_controller is None:
        raise RuntimeError(
            "HueController não configurado. Chame configure_tools() primeiro."
        )
    return _hue_controller


def _get_manager() -> LightSetupsManager:
    """Obtém o manager configurado."""
    if _setups_manager is None:
        raise RuntimeError(
            "LightSetupsManager não configurado. Chame configure_tools() primeiro."
        )
    return _setups_manager


@tool
def list_lights_tool() -> str:
    """Lista todas as lâmpadas disponíveis no sistema.

    Retorna uma lista com os nomes de todas as lâmpadas conectadas
    à bridge Philips Hue.

    Returns:
        Lista de nomes das lâmpadas disponíveis
    """
    controller = _get_controller()
    lights = controller.list_lights()
    return f"Lâmpadas disponíveis: {', '.join(lights)}"


@tool
def get_light_status_tool() -> str:
    """Obtém o status atual de todas as lâmpadas.

    Retorna informações sobre cada lâmpada incluindo:
    - Nome
    - Estado (ligada/desligada)
    - Cor atual (RGB)
    - Brilho

    Returns:
        Status detalhado de todas as lâmpadas
    """
    controller = _get_controller()
    status_list = controller.get_lights_status()

    result_parts = ["Status das lâmpadas:"]
    for light in status_list:
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


@tool
def set_light_color_tool(
    light_name: Annotated[str, "Nome da lâmpada (ex: 'Lâmpada 1', 'Hue Iris')"],
    red: Annotated[int, "Valor do vermelho (0-255)"],
    green: Annotated[int, "Valor do verde (0-255)"],
    blue: Annotated[int, "Valor do azul (0-255)"],
    brightness: Annotated[int, "Brilho (0-254, padrão 200)"] = 200,
) -> str:
    """Define a cor de uma lâmpada específica.

    Permite ajustar a cor de uma lâmpada individual usando valores RGB
    e definir o brilho.

    Args:
        light_name: Nome exato da lâmpada
        red: Componente vermelho (0-255)
        green: Componente verde (0-255)
        blue: Componente azul (0-255)
        brightness: Nível de brilho (0-254)

    Returns:
        Confirmação da mudança de cor
    """
    controller = _get_controller()

    # Valida os valores
    red = max(0, min(255, red))
    green = max(0, min(255, green))
    blue = max(0, min(255, blue))
    brightness = max(0, min(254, brightness))

    color = Color(red, green, blue, brightness)

    try:
        controller.set_light_color(light_name, color)
        return (
            f"Cor da lâmpada '{light_name}' alterada para "
            f"RGB({red}, {green}, {blue}) com brilho {brightness}."
        )
    except Exception as e:
        return f"Erro ao alterar cor da lâmpada '{light_name}': {str(e)}"


@tool
def apply_config_tool(
    config_name: Annotated[str, "Nome da configuração de iluminação"],
    transition_time: Annotated[float, "Tempo de transição em segundos (padrão 0)"] = 0,
) -> str:
    """Aplica uma configuração de iluminação predefinida.

    Aplica um tema/preset de iluminação que define cores para
    múltiplas lâmpadas simultaneamente.

    Args:
        config_name: Nome da configuração (ex: 'cyberpunk_night', 'relaxing')
        transition_time: Tempo em segundos para a transição

    Returns:
        Confirmação da aplicação ou mensagem de erro
    """
    controller = _get_controller()
    manager = _get_manager()

    config = manager.get_config(config_name)
    if not config:
        available = [c.name for c in manager.configs[:10]]
        return (
            f"Configuração '{config_name}' não encontrada. "
            f"Algumas configurações disponíveis: {', '.join(available)}..."
        )

    try:
        controller.apply_light_config(config, transition_time)
        return (
            f"Configuração '{config_name}' aplicada com sucesso! "
            f"Descrição: {config.description}"
        )
    except Exception as e:
        return f"Erro ao aplicar configuração '{config_name}': {str(e)}"


@tool
def list_configs_tool(
    search: Annotated[str, "Termo de busca opcional para filtrar configurações"] = "",
) -> str:
    """Lista as configurações de iluminação disponíveis.

    Retorna uma lista de temas/presets de iluminação que podem
    ser aplicados com apply_config_tool.

    Args:
        search: Termo opcional para filtrar configurações pelo nome

    Returns:
        Lista de configurações disponíveis com descrições
    """
    manager = _get_manager()

    configs = manager.configs
    if search:
        search_lower = search.lower()
        configs = [c for c in configs if search_lower in c.name.lower()]

    if not configs:
        return f"Nenhuma configuração encontrada com o termo '{search}'."

    # Limita a 15 resultados para não sobrecarregar
    configs = sorted(configs, key=lambda c: c.name)[:15]

    result_parts = ["Configurações disponíveis:"]
    for config in configs:
        desc = (
            config.description[:60] + "..."
            if len(config.description) > 60
            else config.description
        )
        result_parts.append(f"- {config.name}: {desc}")

    if len(manager.configs) > 15:
        result_parts.append(f"\n(Mostrando 15 de {len(manager.configs)} configurações)")

    return "\n".join(result_parts)


@tool
def turn_off_lights_tool(
    light_name: Annotated[str, "Nome da lâmpada ou 'all' para todas"] = "all",
) -> str:
    """Desliga lâmpadas.

    Pode desligar uma lâmpada específica ou todas as lâmpadas.

    Args:
        light_name: Nome da lâmpada ou 'all' para desligar todas

    Returns:
        Confirmação do desligamento
    """
    controller = _get_controller()
    manager = _get_manager()

    if light_name.lower() == "all":
        # Aplica configuração 'all_off' se existir, senão desliga manualmente
        config = manager.get_config("all_off")
        if config:
            controller.apply_light_config(config, 1)
            return "Todas as lâmpadas foram desligadas."
        else:
            # Desliga cada lâmpada individualmente
            for light in controller.lights:
                light.on = False
            return "Todas as lâmpadas foram desligadas."
    else:
        # Desliga lâmpada específica
        try:
            light = controller._get_light_by_name(light_name)
            if light:
                light.on = False
                return f"Lâmpada '{light_name}' foi desligada."
            else:
                return f"Lâmpada '{light_name}' não encontrada."
        except Exception as e:
            return f"Erro ao desligar lâmpada '{light_name}': {str(e)}"


@tool
def turn_on_lights_tool(
    light_name: Annotated[str, "Nome da lâmpada ou 'all' para todas"] = "all",
) -> str:
    """Liga lâmpadas.

    Pode ligar uma lâmpada específica ou todas as lâmpadas.

    Args:
        light_name: Nome da lâmpada ou 'all' para ligar todas

    Returns:
        Confirmação
    """
    controller = _get_controller()

    if light_name.lower() == "all":
        for light in controller.lights:
            light.on = True
        return "Todas as lâmpadas foram ligadas."
    else:
        try:
            light = controller._get_light_by_name(light_name)
            if light:
                light.on = True
                return f"Lâmpada '{light_name}' foi ligada."
            else:
                return f"Lâmpada '{light_name}' não encontrada."
        except Exception as e:
            return f"Erro ao ligar lâmpada '{light_name}': {str(e)}"


@tool
def set_brightness_tool(
    light_name: Annotated[str, "Nome da lâmpada ou 'all' para todas"],
    brightness: Annotated[int, "Nível de brilho (0-100 em porcentagem)"],
) -> str:
    """Ajusta o brilho de lâmpadas.

    Args:
        light_name: Nome da lâmpada ou 'all' para todas
        brightness: Brilho em porcentagem (0-100)

    Returns:
        Confirmação do ajuste
    """
    controller = _get_controller()

    # Converte porcentagem para valor Hue (0-254)
    brightness = max(0, min(100, brightness))
    hue_brightness = int((brightness / 100) * 254)

    if light_name.lower() == "all":
        for light in controller.lights:
            if light.on:
                light.brightness = hue_brightness
        return f"Brilho de todas as lâmpadas ajustado para {brightness}%."
    else:
        try:
            light = controller._get_light_by_name(light_name)
            if light:
                light.brightness = hue_brightness
                return f"Brilho da lâmpada '{light_name}' ajustado para {brightness}%."
            else:
                return f"Lâmpada '{light_name}' não encontrada."
        except Exception as e:
            return f"Erro ao ajustar brilho: {str(e)}"


@tool
def save_current_config_tool(
    config_name: Annotated[
        str,
        "Nome para a nova configuração (use underscores, sem espaços). SEMPRE crie um nome criativo baseado nas cores atuais (ex: 'sunset_warm', 'ocean_blue', 'natal_festivo')",
    ],
    description: Annotated[
        str,
        "Descrição de uma linha da configuração. SEMPRE crie uma descrição criativa baseada no ambiente/mood das cores",
    ],
) -> str:
    """Salva o estado atual das lâmpadas como uma nova configuração.

    Captura as cores e brilhos atuais de todas as lâmpadas ligadas
    e salva como uma nova configuração reutilizável.

    IMPORTANTE: Você DEVE SEMPRE fornecer nome E descrição ao chamar esta ferramenta.
    Mesmo que o usuário não informe, crie automaticamente baseado nas cores e contexto:
    - Cores vermelhas/verdes → nome='natal_festivo', descrição='Tema natalino com cores tradicionais'
    - Cores azuis/roxas → nome='noite_relaxante', descrição='Ambiente calmo para relaxar'
    - Cores laranjas/amarelas → nome='por_do_sol', descrição='Cores quentes inspiradas no pôr do sol'
    - Cores RGB variadas → nome='festa_multicolor', descrição='Iluminação vibrante para festas'

    Args:
        config_name: Nome único para a configuração (obrigatório, sem espaços)
        description: Descrição de uma linha do tema/ambiente (obrigatório)

    Returns:
        Confirmação do salvamento ou mensagem de erro
    """
    controller = _get_controller()
    manager = _get_manager()

    # Verifica se já existe uma configuração com esse nome
    existing = manager.get_config(config_name)
    if existing:
        return (
            f"Já existe uma configuração com o nome '{config_name}'. "
            "Escolha outro nome ou delete a existente primeiro."
        )

    # Captura o estado atual das lâmpadas
    from marvin_hue.basics import LightSetting, LightConfig
    from marvin_hue.colors import Color

    settings = []
    lights_status = controller.get_lights_status()

    for light in lights_status:
        if light["on"] and light["reachable"]:
            color = light["color"]
            brightness = light["brightness"]
            light_color = Color(color["r"], color["g"], color["b"], brightness)
            settings.append(LightSetting(light["name"], light_color))

    if not settings:
        return "Nenhuma lâmpada ligada encontrada. Ligue algumas lâmpadas primeiro."

    # Cria a nova configuração
    new_config = LightConfig(
        name=config_name,
        settings=settings,
        description=description or "Configuração salva pelo chat",
    )

    # Adiciona ao manager e salva
    manager.configs.append(new_config)
    manager.save()

    light_names = [s.light_name for s in settings]
    return (
        f"Configuração '{config_name}' salva com sucesso!\n"
        f"Descrição: {new_config.description}\n"
        f"Lâmpadas incluídas: {', '.join(light_names)}"
    )


@tool
def get_light_locations_tool(
    light_name: Annotated[str, "Nome da lâmpada ou 'all' para todas"] = "all",
) -> str:
    """Obtém informações sobre a localização física das lâmpadas.

    Retorna detalhes sobre onde cada lâmpada está posicionada no ambiente,
    incluindo restrições de intensidade e recomendações de uso.

    IMPORTANTE: Fita Led e Led cima têm limite de 25% de intensidade para não forçar a vista.

    Args:
        light_name: Nome da lâmpada específica ou 'all' para todas

    Returns:
        Informações de localização das lâmpadas
    """
    import json
    from pathlib import Path

    locations_file = Path(".res/light_physical_locations.json")

    if not locations_file.exists():
        return "Arquivo de localizações físicas não encontrado."

    try:
        with open(locations_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"Erro ao ler arquivo de localizações: {str(e)}"

    lights = data.get("lights", [])

    if light_name.lower() == "all":
        result_parts = ["Localizações físicas das lâmpadas:"]

        for light in lights:
            name = light["name"]
            location = light["location"]
            notes = light.get("notes", "")

            info = f"\n• {name}: {location}"

            if "max_brightness_percent" in light:
                max_bright = light["max_brightness_percent"]
                info += f"\n  ⚠️ ATENÇÃO: Intensidade máxima recomendada: {max_bright}%"

            if notes:
                info += f"\n  📝 {notes}"

            if "recommendations" in light:
                info += "\n  💡 Recomendações:"
                for rec in light["recommendations"]:
                    info += f"\n     - {rec}"

            result_parts.append(info)

        # Adiciona informações do ambiente
        env_info = data.get("environment_info", {})
        if "considerations" in env_info:
            result_parts.append("\n⚙️ Considerações importantes:")
            for consideration in env_info["considerations"]:
                result_parts.append(f"  • {consideration}")

        return "\n".join(result_parts)
    else:
        # Busca lâmpada específica
        for light in lights:
            if light["name"].lower() == light_name.lower():
                location = light["location"]
                notes = light.get("notes", "")

                info = f"Lâmpada '{light['name']}':\n• Localização: {location}"

                if "max_brightness_percent" in light:
                    max_bright = light["max_brightness_percent"]
                    info += f"\n• ⚠️ Intensidade máxima recomendada: {max_bright}%"

                if notes:
                    info += f"\n• Observação: {notes}"

                if "recommendations" in light:
                    info += "\n• Recomendações:"
                    for rec in light["recommendations"]:
                        info += f"\n  - {rec}"

                return info

        return f"Lâmpada '{light_name}' não encontrada no arquivo de localizações."


def get_all_tools() -> list:
    """Retorna todas as ferramentas disponíveis para o agente.

    Returns:
        Lista de ferramentas configuradas
    """
    return [
        list_lights_tool,
        get_light_status_tool,
        set_light_color_tool,
        apply_config_tool,
        list_configs_tool,
        turn_off_lights_tool,
        turn_on_lights_tool,
        set_brightness_tool,
        save_current_config_tool,
        get_light_locations_tool,
    ]


# ---------------------------------------------------------------------------
# Factory por closure (sem estado global) — substitui configure_tools/get_all_tools.
# Cada tool captura `controller`/`manager` por closure e usa SOMENTE a API
# pública do controller (nada de _get_light_by_name / light.on= direto).
# ---------------------------------------------------------------------------

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
        Lista de 10 BaseTool prontas para create_agent/create_react_agent.
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
        config_name: str = Field(
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
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return f"Erro ao ler arquivo de localizações: {e}"
        lights = data.get("lights", [])
        if light_name.lower() == "all":
            parts = ["Localizações físicas das lâmpadas:"]
            for light in lights:
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
            if light["name"].lower() == light_name.lower():
                info = f"Lâmpada '{light['name']}':\n• Localização: {light['location']}"
                if "max_brightness_percent" in light:
                    info += f"\n• ⚠️ Intensidade máxima recomendada: {light['max_brightness_percent']}%"
                if light.get("notes"):
                    info += f"\n• Observação: {light['notes']}"
                if "recommendations" in light:
                    info += "\n• Recomendações:" + "".join(f"\n  - {r}" for r in light["recommendations"])
                return info
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
