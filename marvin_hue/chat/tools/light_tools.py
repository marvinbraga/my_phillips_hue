"""
Light Tools - Ferramentas para controle de lâmpadas Philips Hue.

Define ferramentas que podem ser usadas pelo agente ReAct para
interagir com as lâmpadas através do HueController.
"""

from typing import Optional, Annotated
from langchain_core.tools import tool

from marvin_hue.controllers import HueController
from marvin_hue.basics import LightSetupsManager
from marvin_hue.colors import Color


# Referências globais para controller e manager
# Serão configuradas pelo agente na inicialização
_hue_controller: Optional[HueController] = None
_setups_manager: Optional[LightSetupsManager] = None


def configure_tools(
    controller: HueController,
    manager: LightSetupsManager
) -> None:
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
    brightness: Annotated[int, "Brilho (0-254, padrão 200)"] = 200
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
    transition_time: Annotated[float, "Tempo de transição em segundos (padrão 0)"] = 0
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
    search: Annotated[str, "Termo de busca opcional para filtrar configurações"] = ""
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
        desc = config.description[:60] + "..." if len(config.description) > 60 else config.description
        result_parts.append(f"- {config.name}: {desc}")

    if len(manager.configs) > 15:
        result_parts.append(f"\n(Mostrando 15 de {len(manager.configs)} configurações)")

    return "\n".join(result_parts)


@tool
def turn_off_lights_tool(
    light_name: Annotated[str, "Nome da lâmpada ou 'all' para todas"] = "all"
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
    light_name: Annotated[str, "Nome da lâmpada ou 'all' para todas"] = "all"
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
    brightness: Annotated[int, "Nível de brilho (0-100 em porcentagem)"]
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
    config_name: Annotated[str, "Nome para a nova configuração. Se o usuário não informar, crie um nome criativo baseado nas cores atuais (ex: 'sunset_warm', 'ocean_blue', 'natal_festivo')"],
    description: Annotated[str, "Descrição da configuração. Se o usuário não informar, crie uma descrição criativa baseada no ambiente/mood das cores"]
) -> str:
    """Salva o estado atual das lâmpadas como uma nova configuração.

    Captura as cores e brilhos atuais de todas as lâmpadas ligadas
    e salva como uma nova configuração reutilizável.

    IMPORTANTE: Se o usuário não fornecer nome ou descrição, você DEVE criar
    automaticamente baseado nas cores e no contexto da conversa. Por exemplo:
    - Se as cores são vermelhas e verdes: nome='natal_festivo', descrição='Tema natalino com cores tradicionais'
    - Se as cores são azuis e roxas: nome='noite_relaxante', descrição='Ambiente calmo para relaxar'
    - Se as cores são laranjas e amarelas: nome='por_do_sol', descrição='Cores quentes inspiradas no pôr do sol'

    Args:
        config_name: Nome único para a configuração
        description: Descrição do tema/ambiente

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
            light_color = Color(
                color["r"],
                color["g"],
                color["b"],
                brightness
            )
            settings.append(LightSetting(light["name"], light_color))

    if not settings:
        return "Nenhuma lâmpada ligada encontrada. Ligue algumas lâmpadas primeiro."

    # Cria a nova configuração
    new_config = LightConfig(
        name=config_name,
        settings=settings,
        description=description or f"Configuração salva pelo chat"
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
    ]
