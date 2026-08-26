# Marvin Hue — controle de iluminação Philips Hue

[![Author](https://img.shields.io/badge/author-Marcus%20Vinicius%20Braga-green.svg)](https://www.linkedin.com/in/marvinbraga/)
![Language](https://img.shields.io/badge/language-python%20%7C%20%3E%3D3.11-blue.svg)
![Framework](https://img.shields.io/badge/framework-FastAPI-009688.svg)
![License](https://img.shields.io/badge/license-GNU%20AGPL%20v3-blue.svg)

Marvin Hue é um console Python para a sua bridge Philips Hue: cenas JSON, catálogo local, espelhamento de tela e áudio, e chat em linguagem natural.

- **~69 temas em JSON** — `.res/setups.json` via `LightSetupsManager` (sem classes Python)
- **Nove lâmpadas** — incluindo `Lâmpada 3`
- **Espelhamento** — tela e música, com Entertainment DTLS opcional
- **Chat** — OpenAI, Anthropic, xAI ou Groq (não há Ollama)
- **Web + API** — FastAPI na porta **5081** (o app ainda declara versão **2.0.0**; o pacote é **0.1.0**)

Ferramenta de instalação: **uv**, não Poetry.

---

## Índice

- [O que você consegue fazer](#o-que-você-consegue-fazer)
- [Pré-requisitos](#pré-requisitos)
- [Instalação](#instalação)
- [Quick start](#quick-start)
- [Uso](#uso)
- [Configuração](#configuração)
- [API](#api)
- [Arquitetura](#arquitetura)
- [Contribuindo](#contribuindo)
- [Troubleshooting](#troubleshooting)
- [Licença](#licença)

---

## O que você consegue fazer

### Cenas

Temas em `.res/setups.json` (concentração, relax, cyberpunk, cinema, …). Edite o JSON e aplique de novo — sem recompilar.

### Espelhamento

Mapeie cada lâmpada a uma região da tela em **Posicionamento** e inicie em **Espelhamento**. O padrão nas luzes é **25 FPS** (perfis `cinema` / `fps` / `ambient` mudam isso). Há modo áudio e transporte Entertainment opcional.

### Chat

Fale com o agente em português:

```
Você: "Ative um ambiente relaxante"
Marvin: aplica o setup `relax` nas lâmpadas
```

Providers: `openai` | `anthropic` | `xai` | `groq`. Detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#harness-de-chat-middleware--subagents--tools).

### Interface

Oito telas: **Controle**, **Lâmpadas**, **Grupos**, **Agendamentos**, **Posicionamento**, **Espelhamento**, **Saúde**, **Chat**.

---

## Pré-requisitos

- Python **3.11+**
- Philips Hue Bridge na LAN
- Lâmpadas Hue com os nomes abaixo (exatos, case-sensitive)
- (Opcional) chave de API do provider de chat

Nove lâmpadas esperadas: `Lâmpada 1`, `Lâmpada 2`, `Lâmpada 3`, `Lâmpada 4`, `Hue Iris`, `Hue Play 1`, `Hue Play 2`, `Fita Led`, `Led cima`.

---

## Instalação

### Passo 1: Clonar

```bash
git clone https://github.com/marvinbraga/my_phillips_hue.git
cd my_phillips_hue
```

### Passo 2: Instalar com uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

### Passo 3: `.env`

```bash
cp .env.example .env
```

Mínimo:

```bash
BRIDGE_IP="192.168.1.100"
```

IP da bridge: app Hue → informações da bridge, ou https://discovery.meethue.com/

### Passo 4: Primeira conexão

Pressione o botão da bridge e, em até 30 segundos:

```bash
uv run python main.py
```

O CLI aplica setups JSON via `LightSetupsManager`.

---

## Quick start

### Servidor web

```bash
uv run uvicorn app:app --reload --port 5081
# ou
uv run python app.py
```

Abra http://localhost:5081

### Cena pela API

```bash
curl http://localhost:5081/configurations

curl -X POST http://localhost:5081/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "concentration", "transition_time_secs": 2.0}'
```

`POST /apply` responde **200** (todas as lâmpadas), **207** (parcial) ou **500** (nenhuma aplicada). `duration_minutes` é aceito e **ignorado** — não é um timer de restauração.

### Espelhamento

```bash
curl -X POST http://localhost:5081/mirror/start \
  -H "Content-Type: application/json" \
  -d '{"fps": 25, "brightness": 200}'
```

Ou http://localhost:5081/mirror

### Chat

```bash
echo 'OPENAI_API_KEY="sk-proj-..."' >> .env
```

```bash
curl -X POST http://localhost:5081/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Ative a configuração de concentração"}'
```

Se `API_KEY` estiver definido, rotas `/api/*` exigem `X-API-Key` ou `Authorization: Bearer`. `/apply`, `/mirror/*` e os WebSockets continuam abertos na LAN.

---

## Uso

### Aplicar uma cena

**Web:** http://localhost:5081 → clique no tema.

**CLI:**

```bash
uv run python main.py
```

**HTTP:**

```bash
curl -X POST http://localhost:5081/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "relax", "transition_time_secs": 3.0}'
```

### Espelhamento de tela

1. Em http://localhost:5081/positions-config, arraste cada lâmpada para a região (`left` / `right` / `top` / cantos / `center` / `ambient` / `none`).
2. Em http://localhost:5081/mirror, inicie o espelhamento.

JSON manual em `.res/light_positions.json`:

```json
{
  "lights": [
    {"name": "Hue Play 1", "position": "left", "enabled": true},
    {"name": "Hue Play 2", "position": "right", "enabled": true},
    {"name": "Fita Led", "position": "top", "enabled": true}
  ]
}
```

Ajustes em tempo real:

```bash
curl -X POST http://localhost:5081/mirror/settings \
  -H "Content-Type: application/json" \
  -d '{"saturation_boost": 1.5}'
```

### Chat

```bash
CHAT_PROVIDER="openai"
CHAT_MODEL="gpt-4o-mini"
OPENAI_API_KEY="sk-proj-..."
```

Outros providers: `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `GROQ_API_KEY`. Interface: http://localhost:5081/chat — WebSocket em `/ws/chat`.

---

## Configuração

```bash
BRIDGE_IP="192.168.1.100"

CHAT_PROVIDER="openai"   # openai | anthropic | xai | groq
CHAT_MODEL="gpt-4o-mini"
OPENAI_API_KEY="sk-proj-..."

LOG_LEVEL="INFO"
CORS_ORIGINS="*"
# API_KEY="troque-por-um-segredo-longo"   # só /api/*
```

Guia completo: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

### Nova cena

Edite `.res/setups.json`:

```json
{
  "setups": [
    {
      "name": "minha_config",
      "description": "Minha configuração personalizada",
      "settings": [
        {
          "light_name": "Lâmpada 1",
          "color": {
            "red": 255,
            "green": 100,
            "blue": 50,
            "brightness": 220
          }
        }
      ]
    }
  ]
}
```

Reinicie (ou use `--reload`) e aplique `minha_config`. Não crie classes em `setups.py`.

---

## API

Documentação interativa: http://localhost:5081/docs

Referência: [docs/API.md](docs/API.md)

| Área | Exemplos |
|------|----------|
| Saúde / bridge | `GET /api/health`, `GET /api/bridge/status`, `GET /api/lights/status` |
| Cenas | `GET /configurations`, `POST /apply` |
| Catálogo | `/api/lights`, `/api/groups`, `/api/schedules`, `/api/history` |
| Espelhamento | `POST /mirror/start`, `POST /mirror/stop`, `GET /mirror/status` |
| Chat | `POST /api/chat/message`, `GET /api/chat/status` |
| WebSockets | `WS /ws/mirror`, `WS /ws/chat` |

`API_KEY` vale só em `/api/*`.

---

## Arquitetura

FastAPI em `app.py` monta o locator em `marvin_hue/api/dependencies.py`. Cenas passam por `LightSetupsManager` → `HueController`. Espelhamento de tela/áudio passa por `MirrorControlService` e, se habilitado, `LightOutputPort` (REST ou Entertainment).

Detalhe: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md). Resumo:

```bash
uv sync --extra dev
uv run pytest
```

Depois do pytest, abra `htmlcov/index.html` para a cobertura **desta** execução. CI (GitHub Actions) roda pytest e ruff em pull requests e em push para `master`/`main`.

Áreas úteis: novos temas em `.res/setups.json`, testes, docs, captura de tela.

---

## Troubleshooting

### Bridge not found

1. Confira `BRIDGE_IP` no `.env`.
2. `ping` o IP.
3. Pressione o botão da bridge e suba o app de novo.

### Light not found

```bash
curl http://localhost:5081/api/lights/status
```

Use o nome **exato** no JSON (`Lâmpada 3` ≠ `Lampada 3`).

### Espelhamento não inicia

- **macOS:** permissão de Screen Recording
- **Linux:** `uv run python -c "import mss; print('OK')"`
- Confira lâmpadas `enabled` em `light_positions.json`

### Chat indisponível

Confira `CHAT_PROVIDER` e a chave correspondente. O chat degrada na subida se a chave faltar; a bridge e o `setups.json` não.

### Alta latência no espelhamento

Baixe o FPS (por exemplo 15) ou use o perfil `cinema`.

Mais: [docs/CONFIGURATION.md](docs/CONFIGURATION.md#troubleshooting)

---

## Documentação adicional

- [docs/API.md](docs/API.md) — REST e WebSocket
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — camadas e fluxo
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env e JSON
- [CHANGELOG.md](CHANGELOG.md) — ondas recentes (0–3)

---

## Tecnologias

- Python ≥3.11, FastAPI, uvicorn
- phue, mss, Pillow, hue-entertainment
- aiosqlite, loguru, Pydantic
- LangChain / LangGraph
- pytest (dev extra)

---

## Segurança

- Validação Pydantic e faixas RGB/brilho
- `.env` no `.gitignore`
- `API_KEY` opcional **somente** em `/api/*`
- CORS padrão `*` — restrinja em rede que não seja LAN confiável
- `API_HOST=0.0.0.0` expõe a LAN; use `127.0.0.1` se só o host precisa acessar

---

## Créditos

- **Autor:** Marcus Vinicius Braga — [LinkedIn](https://www.linkedin.com/in/marvinbraga/)
- Philips Hue, [phue](https://github.com/studioimaginaire/phue), [FastAPI](https://fastapi.tiangolo.com/), [LangChain](https://python.langchain.com/)

## Licença

GNU Affero General Public License v3.0 — ver [LICENSE](LICENSE).

## Suporte

- Issues: https://github.com/marvinbraga/my_phillips_hue/issues
- Email: mvbraga@gmail.com
