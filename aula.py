from enum import Enum

from decouple import config

from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.setups import LightConfig, LightSetting


def list_lights(bridge):
    lights = bridge.list_lights()
    print(lights)


def alterando_configuracao_lampada(bridge, lampada_nome):
    brilho = 255 // 2
    # Definimos verde com o brilho na metade da intensidade
    cor = Color(0, 255, 0, brilho)
    # Aplicamos a configuração
    bridge.set_light_color(lampada_nome, cor)


class OlaMundoSetup(LightConfig):
    def __init__(self):
        super().__init__(
            # Informe o nome para sua configuração
            name="ola_mundo",
            # Aqui já podemos incluir as cofigurações de outras lâmpadas.
            settings=[
                LightSetting('Lâmpada 1', Color(0, 255, 0, 255 // 2)),
                LightSetting('Lâmpada 2', Color(0, 255, 0, 255 // 2)),
                LightSetting('Hue Iris', Color(0, 255, 0, 255 // 2)),
            ]
        )


class CoolBlueEnergy(LightConfig):
    def __init__(self):
        super().__init__(
            "cool_blue_energy",
            settings=[
                LightSetting('Lâmpada 1', Color(220, 255, 230, 170)),
                LightSetting('Lâmpada 2', Color(220, 255, 230, 170)),
                LightSetting('Lâmpada 4', Color(220, 255, 230, 170)),
                LightSetting('Hue Iris', Color(255, 180, 100, 130)),
                LightSetting('Hue Play 1', Color(100, 200, 255, 100)),
                LightSetting('Hue Play 2', Color(100, 200, 255, 100)),
                LightSetting('Fita Led', Color(255, 150, 200, 80)),
                LightSetting('Led cima', Color(255, 200, 200, 40)),
            ]
        )


class ConfiguracaoEnum(Enum):
    OLA_MUNDO_SETUP = (OlaMundoSetup, 'Ambiente verde utilizado no exemplo.')
    COOL_BLUE_ENERGY = (CoolBlueEnergy, 'Energia e foco com luz azul fria')

    def __init__(self, light_config_class, description):
        self.light_config_class = light_config_class
        self.description = description

    def get_instance(self):
        return self.light_config_class()


def aplicar_minha_configuracao(bridge, classe_configuracao):
    # Aplica a configuração informada.
    bridge.apply_light_config(light_config=classe_configuracao())


# Conectando com a Hue bridge
hue_bridge = HueController(ip_address=config("bridge_ip"))
# Listando luzes
list_lights(hue_bridge)
# Alterando a cor de uma lâmpada
alterando_configuracao_lampada(hue_bridge, 'Hue Iris')

# Aplicando configuração em várias lâmpadas.
aplicar_minha_configuracao(bridge=hue_bridge, classe_configuracao=OlaMundoSetup)

# Utilizando a fábrica para aplicar todas as configurações.
hue_bridge.apply_light_config(
    light_config=ConfiguracaoEnum.COOL_BLUE_ENERGY.get_instance()
)
