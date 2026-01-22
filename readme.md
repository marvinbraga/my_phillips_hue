# Marvin Hue - Controle Inteligente de Iluminação Philips Hue

[![Author](https://img.shields.io/badge/author-Marcus%20Vinicius%20Braga-green.svg)](https://www.linkedin.com/in/marvinbraga/)
![Language](https://img.shields.io/badge/language-python%20%7C%20%5E3.10-blue.svg)
![Framework](https://img.shields.io/badge/framework-FastAPI-009688.svg)
![License](https://img.shields.io/badge/license-GNU%20AGPL%20v3-blue.svg)

Marvin Hue é uma aplicação Python avançada para controlar luzes Philips Hue com recursos únicos:

- **50+ Configurações Temáticas**: Ambientes pré-definidos (concentração, relax, cyberpunk, etc)
- **Espelhamento de Tela em Tempo Real**: Luzes que refletem as cores da tela (ambient lighting)
- **Chat com IA**: Controle por linguagem natural usando OpenAI, Anthropic ou Ollama
- **API REST + WebSocket**: Interface programática completa
- **Interface Web Moderna**: Controle visual intuitivo

---

## Índice

- [Funcionalidades](#funcionalidades)
- [Demo Visual](#demo-visual)
- [Instalação](#instalação)
- [Quick Start](#quick-start)
- [Uso](#uso)
- [Configuração](#configuração)
- [API](#api)
- [Arquitetura](#arquitetura)
- [Contribuindo](#contribuindo)
- [Troubleshooting](#troubleshooting)
- [Licença](#licença)

---

## Funcionalidades

### 1. Configurações de Iluminação

Mais de 50 ambientes temáticos pré-configurados:

- **Produtividade**: `concentration`, `focus`, `energize`
- **Relaxamento**: `relax`, `meditation`, `warm_sunset`
- **Entretenimento**: `movie_night`, `party_mode`, `gaming`
- **Estética**: `cyberpunk_night`, `northern_lights`, `ocean_breeze`
- **Especiais**: `romantic`, `reading`, `natural_light`

Todas as configurações são editáveis via JSON - sem necessidade de código Python!

### 2. Espelhamento de Tela (Screen Mirroring)

Transforme suas luzes em extensão da tela:

- **Mapeamento Flexível**: Configure qual luz espelha qual região da tela
- **Alta Performance**: 25-30 FPS com otimizações inteligentes
- **Ajustes em Tempo Real**: FPS, brilho, saturação, suavização
- **Posições Predefinidas**: Esquerda, direita, topo, base, cantos, centro, ambiente

Ideal para:
- Gaming imersivo
- Assistir filmes/séries
- Edição de vídeo/foto
- Ambient lighting geral

### 3. Chat com IA

Controle suas luzes conversando em linguagem natural:

```
Você: "Ative um ambiente relaxante"
Marvin: "Configuração 'relax' aplicada com sucesso!"

Você: "Quais configurações estão disponíveis?"
Marvin: "Tenho 50+ configurações, incluindo: concentration, relax, cyberpunk_night..."

Você: "Inicie o espelhamento de tela com 30 FPS"
Marvin: "Espelhamento iniciado com 30 FPS e brilho 200."
```

Suporta:
- **OpenAI**: GPT-4, GPT-4o, GPT-3.5
- **Anthropic**: Claude 3 Sonnet, Haiku
- **Ollama**: Modelos locais (llama2, mistral)

### 4. API REST + WebSocket

Interface programática completa com:

- **16 endpoints REST**: Configurações, espelhamento, chat, status
- **2 WebSockets**: Updates em tempo real (mirror, chat)
- **Validação automática**: Pydantic models
- **Documentação interativa**: OpenAPI/Swagger em `/docs`

### 5. Interface Web

Páginas web modernas para:

- **Controle de Configurações**: Aplicar temas com um clique
- **Config de Posicionamento**: Arrastar e soltar lâmpadas em posições
- **Controle de Espelhamento**: Iniciar/parar, ajustar em tempo real
- **Chat**: Interface de conversação com o agente IA

---

## Demo Visual

### Interface Principal
```
┌─────────────────────────────────────────┐
│  Marvin Hue Controller                  │
├─────────────────────────────────────────┤
│                                         │
│  [Concentration] [Relax] [Gaming]       │
│  [Cyberpunk] [Movie] [Romantic]         │
│                                         │
│  Estado das Lâmpadas:                   │
│  ● Lâmpada 1    [████████] 254         │
│  ● Hue Play 1   [██████░░] 180         │
│  ○ Lâmpada 2    [░░░░░░░░]   0         │
│                                         │
└─────────────────────────────────────────┘
```

### Espelhamento de Tela
```
Monitor:
┌─────────────────────────────┐
│ [Fita Led - TOP]            │
│                             │
│ [Play 1]      [Play 2]      │
│  LEFT         RIGHT         │
│                             │
└─────────────────────────────┘

As luzes refletem as cores das respectivas regiões em tempo real!
```

---

## Instalação

### Pré-requisitos

- **Python 3.10+**
- **Philips Hue Bridge** na mesma rede local
- **Lâmpadas Philips Hue** conectadas à bridge
- (Opcional) Chave de API OpenAI/Anthropic para chat

### Passo 1: Clonar Repositório

```bash
git clone https://github.com/marvinbraga/my_phillips_hue.git
cd my_phillips_hue
```

### Passo 2: Instalar Dependências

#### Com uv (Recomendado)

```bash
# Instalar uv (se não tiver)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Instalar dependências
uv sync
```

#### Com pip

```bash
# Criar virtual environment
python -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt
```

### Passo 3: Configurar Variáveis de Ambiente

```bash
# Copiar template
cp .env.example .env

# Editar com seu IP da bridge
nano .env
```

Configuração mínima necessária:

```bash
BRIDGE_IP="192.168.1.100"  # ← Substituir pelo IP da sua bridge
```

**Como encontrar o IP da bridge:**

1. App Philips Hue → Configurações → Informações da bridge
2. Ou acessar: https://discovery.meethue.com/

### Passo 4: Primeira Conexão

Na primeira execução, você precisará pressionar o botão físico da bridge Hue:

```bash
# Pressione o botão da bridge
# Dentro de 30 segundos, execute:
uv run python main.py
```

---

## Quick Start

### Iniciar Web Server

```bash
# Modo desenvolvimento (com auto-reload)
uv run uvicorn app:app --reload --port 5000

# Ou com script direto
uv run python app.py
```

Acesse: http://localhost:5000

### Aplicar Configuração (CLI)

```bash
uv run python main.py
# Selecione uma configuração pelo número
```

### Aplicar Configuração (API)

```bash
# Listar configurações disponíveis
curl http://localhost:5000/configurations

# Aplicar configuração
curl -X POST http://localhost:5000/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "concentration", "transition_time_secs": 2.0}'
```

### Iniciar Espelhamento de Tela

```bash
# Via API
curl -X POST http://localhost:5000/mirror/start \
  -H "Content-Type: application/json" \
  -d '{"fps": 25, "brightness": 200}'

# Ou acesse a interface web
# http://localhost:5000/mirror
```

### Chat com IA

```bash
# Configurar chave de API (se ainda não fez)
echo 'OPENAI_API_KEY="sk-proj-..."' >> .env

# Enviar mensagem
curl -X POST http://localhost:5000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Ative a configuração de concentração"}'

# Ou acesse a interface web
# http://localhost:5000/chat
```

---

## Uso

### Aplicar Configurações de Iluminação

#### Via Interface Web

1. Acesse http://localhost:5000
2. Clique em uma configuração
3. Pronto! Luzes aplicadas com transição suave

#### Via CLI

```bash
uv run python main.py
# Menu interativo aparecerá
```

#### Via API REST

```bash
# Aplicar com transição de 3 segundos
curl -X POST http://localhost:5000/apply \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "relax",
    "transition_time_secs": 3.0
  }'
```

#### Via Python

```python
import requests

response = requests.post(
    "http://localhost:5000/apply",
    json={
        "config_name": "cyberpunk_night",
        "transition_time_secs": 2.0
    }
)

print(response.json())
```

---

### Espelhamento de Tela

#### 1. Configurar Posicionamento

**Via Interface Web:**

1. Acesse http://localhost:5000/positions-config
2. Arraste lâmpadas para as posições desejadas:
   - **Esquerda/Direita**: Ideal para Hue Play
   - **Topo/Base**: Ideal para fitas LED
   - **Centro**: Para lâmpada principal
   - **Ambiente**: Cor média de toda a tela
3. Clique em "Salvar"

**Via JSON (manual):**

Edite `.res/light_positions.json`:

```json
{
  "lights": [
    {"name": "Hue Play 1", "position": "left", "enabled": true},
    {"name": "Hue Play 2", "position": "right", "enabled": true},
    {"name": "Fita Led", "position": "top", "enabled": true}
  ]
}
```

#### 2. Iniciar Espelhamento

**Via Interface Web:**

1. Acesse http://localhost:5000/mirror
2. Ajuste FPS e brilho (opcional)
3. Clique em "Iniciar Espelhamento"

**Via API:**

```bash
curl -X POST http://localhost:5000/mirror/start \
  -H "Content-Type: application/json" \
  -d '{"fps": 25, "brightness": 200}'
```

**Via Python:**

```python
import requests

# Iniciar
response = requests.post(
    "http://localhost:5000/mirror/start",
    json={"fps": 25, "brightness": 200}
)

# Parar (após usar)
requests.post("http://localhost:5000/mirror/stop")
```

#### 3. Ajustar em Tempo Real

```bash
# Aumentar saturação para cores mais vibrantes
curl -X POST http://localhost:5000/mirror/settings \
  -H "Content-Type: application/json" \
  -d '{"saturation_boost": 1.5}'

# Ajustar FPS
curl -X POST http://localhost:5000/mirror/settings \
  -H "Content-Type: application/json" \
  -d '{"fps": 30}'

# Ajustar suavização (menor = mais suave)
curl -X POST http://localhost:5000/mirror/settings \
  -H "Content-Type: application/json" \
  -d '{"smoothing_factor": 0.3}'
```

---

### Chat com Agente IA

#### Configuração Inicial

```bash
# Editar .env
nano .env

# Adicionar:
CHAT_PROVIDER="openai"
CHAT_MODEL="gpt-4o-mini"
OPENAI_API_KEY="sk-proj-..."

# Reiniciar aplicação
```

#### Usar Chat

**Via Interface Web:**

1. Acesse http://localhost:5000/chat
2. Digite sua mensagem
3. Aguarde resposta do agente

**Via API REST:**

```bash
curl -X POST http://localhost:5000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Ative um ambiente relaxante"}'
```

**Via WebSocket (JavaScript):**

```javascript
const ws = new WebSocket('ws://localhost:5000/ws/chat');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'response') {
    console.log('Agente:', data.content);
  }
};

ws.send(JSON.stringify({
  action: 'message',
  message: 'Quais configurações estão disponíveis?'
}));
```

**Exemplos de Comandos:**

```
"Ative a configuração de concentração"
"Inicie o espelhamento de tela"
"Quais configurações estão disponíveis?"
"Mostre o status das lâmpadas"
"Desligue todas as luzes"
"Ative modo gaming com transição de 2 segundos"
```

---

## Configuração

### Variáveis de Ambiente

Todas as configurações são gerenciadas via arquivo `.env`:

```bash
# ===== OBRIGATÓRIO =====
BRIDGE_IP="192.168.1.100"

# ===== CHAT (OPCIONAL) =====
CHAT_PROVIDER="openai"              # openai | anthropic | ollama
CHAT_MODEL="gpt-4o-mini"
OPENAI_API_KEY="sk-proj-..."
# ANTHROPIC_API_KEY="sk-ant-..."

# ===== LOGGING (OPCIONAL) =====
LOG_LEVEL="INFO"                    # DEBUG | INFO | WARNING | ERROR
LOG_FILE="logs/marvin_hue.log"

# ===== SEGURANÇA (OPCIONAL) =====
CORS_ORIGINS="*"                    # Em produção: "https://seudominio.com"
```

Ver documentação completa em: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

---

### Adicionar Nova Configuração de Iluminação

1. Editar `.res/setups.json`

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

2. Reiniciar aplicação

```bash
# Ctrl+C para parar
uv run uvicorn app:app --reload --port 5000
```

3. Aplicar nova configuração

```bash
curl -X POST http://localhost:5000/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "minha_config"}'
```

Sem necessidade de código Python! Apenas edite o JSON.

---

## API

### Documentação Completa

Acesse a documentação interativa: http://localhost:5000/docs (Swagger UI)

Ou leia: [docs/API.md](docs/API.md)

### Principais Endpoints

#### Status e Informações

```bash
# Status da bridge
GET /api/bridge/status

# Status de todas as lâmpadas
GET /api/lights/status
```

#### Configurações

```bash
# Listar configurações
GET /configurations

# Aplicar configuração
POST /apply
{
  "config_name": "concentration",
  "transition_time_secs": 2.0
}
```

#### Espelhamento

```bash
# Iniciar
POST /mirror/start
{"fps": 25, "brightness": 200}

# Parar
POST /mirror/stop

# Status
GET /mirror/status

# Ajustar configurações
POST /mirror/settings
{"saturation_boost": 1.5}
```

#### Chat

```bash
# Enviar mensagem
POST /api/chat/message
{"message": "Ative concentração"}

# Status do agente
GET /api/chat/status

# Limpar histórico
POST /api/chat/clear
```

#### WebSockets

```bash
# Espelhamento em tempo real
WS /ws/mirror

# Chat em tempo real
WS /ws/chat
```

---

## Arquitetura

### Visão Geral

```
┌──────────────┐
│ Web Browser  │ ← Interface visual
└──────┬───────┘
       │ HTTP/WebSocket
       ▼
┌──────────────────────┐
│   FastAPI Server     │ ← API REST + WebSocket
│     (app.py)         │
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│  Core Modules        │
│  - HueController     │ ← Controle da bridge
│  - ScreenMirror      │ ← Captura de tela
│  - ChatAgent         │ ← IA conversacional
│  - LightSetupsManager│ ← Gerenciador de configs
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ External Services    │
│ - Philips Hue Bridge │ ← Hardware
│ - OpenAI/Anthropic   │ ← LLMs
│ - Screen Capture     │ ← Sistema operacional
└──────────────────────┘
```

### Principais Componentes

- **`marvin_hue/colors.py`**: Representação de cores RGBA
- **`marvin_hue/utils.py`**: Conversão RGB ↔ XY (espaço de cor Hue)
- **`marvin_hue/basics.py`**: Estruturas de dados (LightConfig, etc)
- **`marvin_hue/controllers.py`**: Comunicação com bridge Hue
- **`marvin_hue/screen_mirror.py`**: Captura e processamento de tela
- **`marvin_hue/setup_builder.py`**: Builder pattern para configurações
- **`app.py`**: Aplicação FastAPI (API + WebSocket)

Ver documentação completa em: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Contribuindo

Contribuições são bem-vindas! Veja [CONTRIBUTING.md](CONTRIBUTING.md) para diretrizes.

### Áreas para Contribuição

- **Novas configurações de iluminação** (edite `.res/setups.json`)
- **Melhorias no algoritmo de captura de tela**
- **Novos prompts para o agente de chat**
- **Testes automatizados**
- **Documentação**
- **Traduções**

### Como Contribuir

1. Fork o repositório
2. Crie uma branch (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -m 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Abra um Pull Request

### Executar Testes

```bash
# Todos os testes
uv run pytest

# Com cobertura
uv run pytest --cov=marvin_hue --cov-report=html

# Abrir relatório de cobertura
open htmlcov/index.html
```

Cobertura atual: **70%+**

---

## Troubleshooting

### Problema: "Bridge not found"

**Solução:**

1. Verificar IP da bridge no `.env`
2. Testar conectividade: `ping 192.168.1.100`
3. Pressionar botão da bridge e reiniciar app

### Problema: "Light not found"

**Solução:**

1. Listar lâmpadas disponíveis:
   ```bash
   curl http://localhost:5000/api/lights/status
   ```
2. Copiar nome EXATO para o JSON (case-sensitive)
3. Verificar se lâmpada está online no app Hue

### Problema: Espelhamento não inicia

**Solução:**

1. **macOS**: Conceder permissão de captura de tela
   - System Preferences → Security & Privacy → Screen Recording
2. **Linux**: Verificar biblioteca mss
   ```bash
   python -c "import mss; print('OK')"
   ```
3. Verificar que há lâmpadas ativas em `light_positions.json`

### Problema: Chat não funciona

**Solução:**

1. Verificar chave de API no `.env`
2. Testar chave:
   ```bash
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```
3. Verificar créditos em https://platform.openai.com/usage

### Problema: Alta latência

**Solução:**

1. Reduzir FPS do espelhamento (padrão 25 → 15)
2. Aumentar smoothing_factor (0.5 → 0.7)
3. Usar menos lâmpadas ativas simultaneamente

Ver guia completo em: [docs/CONFIGURATION.md#troubleshooting](docs/CONFIGURATION.md#troubleshooting)

---

## Documentação Adicional

- **[API.md](docs/API.md)**: Documentação completa da API REST e WebSocket
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**: Design do sistema e fluxo de dados
- **[CONFIGURATION.md](docs/CONFIGURATION.md)**: Variáveis de ambiente e schemas JSON
- **[IMPROVEMENT_PLAN.md](docs/IMPROVEMENT_PLAN.md)**: Plano de melhorias e roadmap

---

## Roadmap

### Versão 2.0 (Atual) ✅

- ✅ Configurações baseadas em JSON
- ✅ API REST + WebSocket
- ✅ Espelhamento de tela
- ✅ Chat com IA
- ✅ Interface web
- ✅ Testes automatizados (70%+ coverage)
- ✅ Logging estruturado
- ✅ Validação de inputs

### Versão 3.0 (Planejado)

- ⏳ Autenticação e autorização
- ⏳ Rate limiting
- ⏳ Suporte para múltiplas bridges
- ⏳ Scheduler (automações temporais)
- ⏳ Integração com Home Assistant
- ⏳ Mobile app (React Native)
- ⏳ Presets de espelhamento por aplicação

---

## Tecnologias

- **Python 3.10+**: Linguagem principal
- **FastAPI**: Framework web async
- **phue**: Biblioteca para Philips Hue
- **mss**: Captura de tela eficiente
- **LangChain**: Orquestração de LLMs
- **Pydantic**: Validação de dados
- **pytest**: Framework de testes

---

## Performance

| Operação | Tempo Médio |
|----------|-------------|
| Aplicar configuração | ~200ms |
| Screen capture | ~10-40ms/frame |
| API response | <100ms |
| Light lookup | O(1) - cached |

---

## Segurança

**Implementado:**
- ✅ Validação de inputs com Pydantic
- ✅ Sanitização de strings
- ✅ Range checks (RGB, brightness, etc)
- ✅ `.env` no `.gitignore`

**Recomendado para Produção:**
- ⚠️ Autenticação (API keys)
- ⚠️ CORS restrito
- ⚠️ Rate limiting
- ⚠️ HTTPS/WSS

---

## Créditos

- **Autor**: Marcus Vinicius Braga
- **LinkedIn**: [marvinbraga](https://www.linkedin.com/in/marvinbraga/)
- **Email**: mvbraga@gmail.com

### Agradecimentos

- [Philips Hue](https://www.philips-hue.com/) - API e hardware
- [phue](https://github.com/studioimaginaire/phue) - Biblioteca Python
- [FastAPI](https://fastapi.tiangolo.com/) - Framework web
- [LangChain](https://python.langchain.com/) - Framework para LLMs

---

## Licença

Este projeto está licenciado sob a **GNU Affero General Public License v3.0**.

Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

**Em resumo:**
- ✅ Uso comercial permitido
- ✅ Modificação permitida
- ✅ Distribuição permitida
- ⚠️ Código-fonte modificado deve ser compartilhado
- ⚠️ Mudanças devem ser documentadas
- ⚠️ Mesma licença deve ser mantida

---

## Suporte

- **Issues**: https://github.com/marvinbraga/my_phillips_hue/issues
- **Discussões**: https://github.com/marvinbraga/my_phillips_hue/discussions
- **Email**: mvbraga@gmail.com

---

## Changelog

### v2.0.0 (2026-01-22)

- ➕ Adicionado espelhamento de tela em tempo real
- ➕ Adicionado chat com IA (OpenAI, Anthropic, Ollama)
- ➕ API REST completa com FastAPI
- ➕ WebSockets para updates em tempo real
- ➕ Interface web moderna
- ➕ Configurações baseadas em JSON (eliminou 87% de código duplicado)
- ➕ Testes automatizados com 70%+ coverage
- ➕ Logging estruturado
- ➕ Validação de inputs com Pydantic
- ➕ Documentação completa (API, Arquitetura, Configuração)

### v1.0.0 (2023-XX-XX)

- Versão inicial
- Controle básico de lâmpadas
- Configurações hardcoded
- CLI simples

---

**Desenvolvido com ❤️ por Marcus Vinicius Braga**

Se este projeto foi útil, considere dar uma ⭐ no GitHub!
