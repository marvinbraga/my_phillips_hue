# aula_hue.py

from time import sleep
from decouple import config

from marvin_hue.controllers import HueController
from marvin_hue.factories import LightConfigEnum

# Crie uma instância do controlador Hue usando o endereço IP da ponte Hue
hue = HueController(ip_address=config("bridge_ip"))


def aplicar_configuracao(config_enum, tempo_de_transicao=0):
    # Instancie a configuração de luz
    configuracao = config_enum.get_instance()

    # Imprima o nome e a descrição da configuração
    print(f"Nome: {configuracao}, Descrição: {config_enum.description}")

    # Aplique a configuração de luz usando o controlador Hue
    hue.apply_light_config(configuracao, tempo_de_transicao)


def aplicar_todas_configuracoes(tempo_de_transicao=0, tempo_de_espera=7):
    for config_enum in LightConfigEnum:
        aplicar_configuracao(config_enum, tempo_de_transicao)
        sleep(tempo_de_espera)


if __name__ == "__main__":
    # Exemplo: aplique a configuração "SETUP_RELAXING"
    aplicar_configuracao(LightConfigEnum.SETUP_RELAXING)

    # Descomente a linha abaixo para aplicar todas as configurações
    # aplicar_todas_configuracoes()
