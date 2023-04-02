# Marvin Hue - Controle de Iluminação Inteligente

[![Author](https://img.shields.io/badge/author-Marcus%20Vinicius%20Braga-green.svg)](https://www.linkedin.com/in/marvinbraga/)
![language](https://img.shields.io/badge/language-python|^3.10-blue.svg)
[![package](https://img.shields.io/badge/package-phue-yellow.svg)](https://github.com/studioimaginaire/phue)
![venv](https://img.shields.io/badge/venv-poetry-orange.svg)

Marvin Hue é um projeto que permite controlar facilmente suas lâmpadas Philips Hue, criando ambientes personalizados e
adaptados às suas necessidades e preferências. Com uma ampla variedade de configurações de iluminação pré-definidas,
você pode facilmente mudar o clima e a atmosfera de sua casa ou escritório.

## Funcionalidades

- Controle de lâmpadas Philips Hue através de configurações pré-definidas.
- Conversão de cores RGB para coordenadas XY, compatíveis com as lâmpadas Philips Hue.
- Personalização das configurações de iluminação de acordo com suas preferências.
- Facilidade para adicionar novas configurações de iluminação.

## Requisitos

- Python 3.7 ou superior
- Biblioteca `phue`
- Biblioteca `python-decouple`

## Instalação

1. Clone este repositório em sua máquina local:

    ```bash
    git clone https://github.com/marvinbraga/my_phillips_hue.git
    ```

2. Navegue até o diretório do projeto e instale as dependências:

    ```shell
    cd my_phillips_hue
    poetry install
    ```

3. Copie o arquivo `.env.example` para `.env` e atualize o valor da variável `bridge_ip` com o **endereço IP da sua
   ponte Philips Hue**.

## Utilização

Execute o script `main.py` para testar as configurações de iluminação pré-definidas:

```bash
python main.py
```

Sinta-se à vontade para personalizar ou adicionar suas próprias configurações de iluminação no
arquivo `marvin_hue/setups.py`.

## Contribuindo

Se você deseja contribuir com este projeto, por favor, siga as diretrizes de contribuição disponíveis no
arquivo [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licença

Este projeto está licenciado sob a Licença `GNU Affero General Public License v3.0` - consulte o arquivo 
[`LICENSE`](LICENSE) para obter mais informações.
