# Contribuindo para o Marvin Hue

Obrigado por ajudar a melhorar o Marvin Hue. Este guia basta para deixar uma mudança pronta para revisão.

## Como contribuir

1. Faça fork do repositório e clone o seu fork:

    ```bash
    git clone https://github.com/marvinbraga/my_phillips_hue.git
    cd my_phillips_hue
    ```

2. Instale com **uv** (não Poetry):

    ```bash
    uv sync --extra dev
    ```

3. Copie `.env.example` para `.env` e defina `BRIDGE_IP`. Os testes definem isso sozinhos; o app em execução precisa do IP real da bridge.

4. Crie uma branch para a sua alteração:

    ```bash
    git checkout -b minha-nova-funcionalidade
    ```

5. Faça a mudança. Siga o estilo do código ao redor. Temas de iluminação entram em `.res/setups.json`, não como classes Python.

6. Rode os testes:

    ```bash
    uv run pytest
    ```

    Abra `htmlcov/index.html` se quiser o relatório de cobertura **dessa** execução. Não use um percentual de um README antigo como gate.

    Lint (o mesmo check do CI):

    ```bash
    uv run --with ruff ruff check marvin_hue tests
    ```

7. Faça commit, push da branch e abra um pull request. O GitHub Actions roda pytest e ruff no PR.

    Atualizar o [CHANGELOG.md](CHANGELOG.md) é **opcional**. Use-o quando a mudança for visível (comportamento da API, formato dos setups, variáveis de ambiente). Pule para typos, testes ou refactors sem efeito externo.

## Revisão

Os mantenedores revisam o PR e podem pedir alterações. Isso é normal. Mantenha a discussão no diff.

## Próximos passos

- Setup do app: [readme.md](readme.md)
- Variáveis e JSON: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- Camadas do sistema: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
