# Guia de Configuração - Marvin Hue

Este documento descreve todas as configurações, variáveis de ambiente e schemas JSON necessários para executar o Marvin Hue Controller.

---

## Índice

1. [Variáveis de Ambiente](#variáveis-de-ambiente)
2. [Arquivos de Configuração JSON](#arquivos-de-configuração-json)
3. [Configuração Personalizada](#configuração-personalizada)
4. [Troubleshooting](#troubleshooting)

---

## Variáveis de Ambiente

Todas as variáveis de ambiente devem ser definidas no arquivo `.env` na raiz do projeto.

### Configuração Básica

#### `BRIDGE_IP` (Obrigatório)

Endereço IP da Philips Hue Bridge na sua rede local.

```bash
BRIDGE_IP="192.168.1.100"
```

**Como encontrar o IP da bridge:**

1. **Método 1: Aplicativo Hue**
   - Abra o app Philips Hue no celular
   - Configurações → Bridge → Informações de rede
   - Anote o IP exibido

2. **Método 2: Discovery API**
   ```bash
   curl https://discovery.meethue.com/
   ```
   Retorna: `[{"id":"...", "internalipaddress":"192.168.1.100"}]`

3. **Método 3: Router**
   - Acesse o painel do router
   - Procure por dispositivo "Philips-hue"
   - Anote o IP e configure IP estático (recomendado)

**Validação:**
```bash
# Testar conectividade
ping 192.168.1.100

# Testar API Hue
curl http://192.168.1.100/api/
```

---

### Configuração de Chat (Opcional)

#### `CHAT_PROVIDER`

Provedor de LLM para o agente de chat.

```bash
CHAT_PROVIDER="openai"  # Opções: openai, anthropic, ollama
```

**Opções:**
- `openai`: OpenAI (GPT-4, GPT-3.5, etc)
- `anthropic`: Anthropic (Claude)
- `ollama`: Ollama (modelos locais)

**Padrão:** `openai`

---

#### `CHAT_MODEL`

Modelo específico a ser usado.

```bash
# OpenAI
CHAT_MODEL="gpt-4o-mini"     # Recomendado (rápido e barato)
CHAT_MODEL="gpt-4o"          # Mais capaz, mais caro
CHAT_MODEL="gpt-3.5-turbo"   # Legado

# Anthropic
CHAT_MODEL="claude-3-sonnet-20240229"
CHAT_MODEL="claude-3-haiku-20240307"

# Ollama (local)
CHAT_MODEL="llama2"
CHAT_MODEL="mistral"
```

**Padrão:** `gpt-4o-mini`

---

#### `OPENAI_API_KEY`

Chave de API da OpenAI (necessária se `CHAT_PROVIDER=openai`).

```bash
OPENAI_API_KEY="sk-proj-..."
```

**Como obter:**
1. Criar conta em https://platform.openai.com/
2. Acessar API Keys
3. Criar nova chave
4. Copiar e colar no `.env`

**Segurança:**
- ⚠️ NUNCA commitar `.env` no git
- ✅ Adicionar `.env` ao `.gitignore`
- ✅ Rotacionar keys periodicamente
- ✅ Limitar uso com quotas

---

#### `ANTHROPIC_API_KEY`

Chave de API da Anthropic (necessária se `CHAT_PROVIDER=anthropic`).

```bash
ANTHROPIC_API_KEY="sk-ant-..."
```

**Como obter:**
1. Criar conta em https://console.anthropic.com/
2. Acessar API Keys
3. Criar nova chave

---

### Configuração de Logging (Opcional)

#### `LOG_LEVEL`

Nível de verbosidade dos logs.

```bash
LOG_LEVEL="INFO"  # Opções: DEBUG, INFO, WARNING, ERROR
```

**Níveis:**
- `DEBUG`: Tudo (coordenadas XY, cache hits, etc)
- `INFO`: Operações normais (padrão)
- `WARNING`: Avisos e erros
- `ERROR`: Apenas erros

**Padrão:** `INFO`

---

#### `LOG_FILE`

Caminho do arquivo de log.

```bash
LOG_FILE="logs/marvin_hue.log"
```

**Padrão:** `logs/marvin_hue.log`

**Configuração de Rotação:**
- Tamanho máximo: 10 MB
- Backups mantidos: 5
- Total máximo: ~50 MB

---

### Configuração de CORS (Opcional)

#### `CORS_ORIGINS`

Origens permitidas para requisições CORS (separadas por vírgula).

```bash
# Desenvolvimento (permite tudo)
CORS_ORIGINS="*"

# Produção (específico)
CORS_ORIGINS="https://meusite.com,https://app.meusite.com"
```

**Padrão:** `*` (aceita todas as origens)

**Recomendação para Produção:**
```bash
CORS_ORIGINS="https://seudominio.com"
```

---

### Exemplo Completo de `.env`

```bash
# ===== CONFIGURAÇÃO OBRIGATÓRIA =====

# IP da Philips Hue Bridge
BRIDGE_IP="192.168.1.100"


# ===== CONFIGURAÇÃO DE CHAT (OPCIONAL) =====

# Provedor de LLM
CHAT_PROVIDER="openai"

# Modelo a ser usado
CHAT_MODEL="gpt-4o-mini"

# Chaves de API (escolher de acordo com o provider)
OPENAI_API_KEY="sk-proj-..."
# ANTHROPIC_API_KEY="sk-ant-..."


# ===== CONFIGURAÇÃO DE LOGGING (OPCIONAL) =====

# Nível de log
LOG_LEVEL="INFO"

# Arquivo de log
LOG_FILE="logs/marvin_hue.log"


# ===== CONFIGURAÇÃO DE SEGURANÇA (OPCIONAL) =====

# CORS
CORS_ORIGINS="*"
```

---

## Arquivos de Configuração JSON

### 1. `setups.json` - Configurações de Iluminação

**Localização:** `.res/setups.json`

**Estrutura:**

```json
{
  "setups": [
    {
      "name": "string",
      "description": "string",
      "settings": [
        {
          "light_name": "string",
          "color": {
            "red": 0-255,
            "green": 0-255,
            "blue": 0-255,
            "brightness": 0-254
          }
        }
      ]
    }
  ]
}
```

**Campos:**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `name` | string | Sim | Identificador único da configuração (sem espaços) |
| `description` | string | Não | Descrição legível da configuração |
| `settings` | array | Sim | Lista de configurações de lâmpadas (1+ itens) |
| `light_name` | string | Sim | Nome exato da lâmpada (case-sensitive) |
| `color.red` | int | Sim | Componente vermelho (0-255) |
| `color.green` | int | Sim | Componente verde (0-255) |
| `color.blue` | int | Sim | Componente azul (0-255) |
| `color.brightness` | int | Sim | Brilho (0-254, não 255!) |

**Exemplo Completo:**

```json
{
  "setups": [
    {
      "name": "concentration",
      "description": "Ambiente que estimula a concentração com luz branca fria",
      "settings": [
        {
          "light_name": "Lâmpada 1",
          "color": {
            "red": 255,
            "green": 244,
            "blue": 229,
            "brightness": 255
          }
        },
        {
          "light_name": "Lâmpada 2",
          "color": {
            "red": 255,
            "green": 244,
            "blue": 229,
            "brightness": 255
          }
        },
        {
          "light_name": "Hue Iris",
          "color": {
            "red": 173,
            "green": 216,
            "blue": 230,
            "brightness": 200
          }
        }
      ]
    },
    {
      "name": "relax",
      "description": "Ambiente relaxante com tons quentes",
      "settings": [
        {
          "light_name": "Lâmpada 1",
          "color": {
            "red": 255,
            "green": 147,
            "blue": 41,
            "brightness": 180
          }
        },
        {
          "light_name": "Lâmpada 2",
          "color": {
            "red": 255,
            "green": 147,
            "blue": 41,
            "brightness": 180
          }
        }
      ]
    }
  ]
}
```

**Validação:**

```bash
# Validar JSON
cat .res/setups.json | python -m json.tool

# Testar no app
curl http://localhost:5000/configurations
```

**Dicas:**

1. **Nomes de Configuração:**
   - Use snake_case: `cyberpunk_night`, não `Cyberpunk Night`
   - Sem caracteres especiais: apenas letras, números, underscore
   - Únicos: não repetir nomes

2. **Nomes de Lâmpadas:**
   - Devem corresponder EXATAMENTE aos nomes na bridge Hue
   - Case-sensitive: `Lâmpada 1` ≠ `lâmpada 1`
   - Para listar lâmpadas disponíveis:
     ```bash
     curl http://localhost:5000/api/lights/status
     ```

3. **Brightness:**
   - API Hue limita a 254, não 255
   - 0 = apagado (mas `on: true` ainda precisa estar setado)
   - 254 = brilho máximo

4. **Cores Comuns:**
   ```json
   // Branco frio (concentração)
   {"red": 255, "green": 244, "blue": 229, "brightness": 254}

   // Branco quente (relax)
   {"red": 255, "green": 147, "blue": 41, "brightness": 180}

   // Azul (calmo)
   {"red": 0, "green": 100, "blue": 255, "brightness": 200}

   // Verde (natureza)
   {"red": 50, "green": 200, "blue": 50, "brightness": 200}

   // Vermelho (energia)
   {"red": 255, "green": 0, "blue": 0, "brightness": 200}

   // Rosa (romance)
   {"red": 255, "green": 105, "blue": 180, "brightness": 150}
   ```

---

### 2. `light_positions.json` - Posicionamento para Espelhamento

**Localização:** `.res/light_positions.json`

**Estrutura:**

```json
{
  "lights": [
    {
      "name": "string",
      "position": "none|left|right|top|bottom|top-left|top-right|bottom-left|bottom-right|center|ambient",
      "enabled": true|false
    }
  ],
  "positions": [
    {
      "id": "string",
      "label": "string",
      "description": "string"
    }
  ]
}
```

**Campos (lights):**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `name` | string | Sim | Nome da lâmpada (deve corresponder à bridge) |
| `position` | string | Sim | Região da tela a espelhar (ver abaixo) |
| `enabled` | boolean | Sim | Se a lâmpada participa do espelhamento |

**Posições Disponíveis:**

```
┌─────────────────────────────────────┐
│ top-left       top       top-right  │
│                                     │
│                                     │
│   left       center        right   │
│                                     │
│                                     │
│bottom-left   bottom   bottom-right │
└─────────────────────────────────────┘

ambient = cor média de toda a tela
none = não participa do espelhamento
```

**Mapeamento de Regiões (% da tela):**

| Posição | X Start | Y Start | Width | Height |
|---------|---------|---------|-------|--------|
| left | 0% | 20% | 15% | 60% |
| right | 85% | 20% | 15% | 60% |
| top | 20% | 0% | 60% | 15% |
| bottom | 20% | 85% | 60% | 15% |
| top-left | 0% | 0% | 25% | 25% |
| top-right | 75% | 0% | 25% | 25% |
| bottom-left | 0% | 75% | 25% | 25% |
| bottom-right | 75% | 75% | 25% | 25% |
| center | 25% | 25% | 50% | 50% |
| ambient | 0% | 0% | 100% | 100% |
| none | - | - | - | - |

**Exemplo Completo:**

```json
{
  "lights": [
    {
      "name": "Hue Play 1",
      "position": "left",
      "enabled": true
    },
    {
      "name": "Hue Play 2",
      "position": "right",
      "enabled": true
    },
    {
      "name": "Fita Led",
      "position": "top",
      "enabled": true
    },
    {
      "name": "Led cima",
      "position": "top",
      "enabled": true
    },
    {
      "name": "Lâmpada 1",
      "position": "none",
      "enabled": true
    },
    {
      "name": "Lâmpada 2",
      "position": "ambient",
      "enabled": false
    }
  ],
  "positions": [
    {
      "id": "none",
      "label": "Não usar",
      "description": "Lâmpada não participa do espelhamento"
    },
    {
      "id": "left",
      "label": "Esquerda",
      "description": "Lado esquerdo do monitor"
    },
    {
      "id": "right",
      "label": "Direita",
      "description": "Lado direito do monitor"
    },
    {
      "id": "top",
      "label": "Topo",
      "description": "Parte superior do monitor"
    },
    {
      "id": "bottom",
      "label": "Base",
      "description": "Parte inferior do monitor"
    },
    {
      "id": "top-left",
      "label": "Topo Esquerdo",
      "description": "Canto superior esquerdo"
    },
    {
      "id": "top-right",
      "label": "Topo Direito",
      "description": "Canto superior direito"
    },
    {
      "id": "bottom-left",
      "label": "Base Esquerda",
      "description": "Canto inferior esquerdo"
    },
    {
      "id": "bottom-right",
      "label": "Base Direita",
      "description": "Canto inferior direito"
    },
    {
      "id": "center",
      "label": "Centro",
      "description": "Região central da tela"
    },
    {
      "id": "ambient",
      "label": "Ambiente",
      "description": "Cor média de toda a tela"
    }
  ]
}
```

**Validação:**

```bash
# Validar JSON
cat .res/light_positions.json | python -m json.tool

# Testar no app
curl http://localhost:5000/positions
```

**Dicas:**

1. **Setup Típico para Monitor Único:**
   ```json
   {
     "lights": [
       {"name": "Hue Play 1", "position": "left", "enabled": true},
       {"name": "Hue Play 2", "position": "right", "enabled": true},
       {"name": "Fita Led", "position": "top", "enabled": true}
     ]
   }
   ```

2. **Setup para TV/Tela Grande:**
   ```json
   {
     "lights": [
       {"name": "Play 1", "position": "top-left", "enabled": true},
       {"name": "Play 2", "position": "top-right", "enabled": true},
       {"name": "Play 3", "position": "bottom-left", "enabled": true},
       {"name": "Play 4", "position": "bottom-right", "enabled": true}
     ]
   }
   ```

3. **Ambient Light (Uma Cor para Ambiente Todo):**
   ```json
   {
     "lights": [
       {"name": "Lâmpada Sala", "position": "ambient", "enabled": true}
     ]
   }
   ```

4. **Resetar para Padrão:**
   ```bash
   curl -X POST http://localhost:5000/positions/reset
   ```

---

## Configuração Personalizada

### Adicionar Nova Configuração de Iluminação

1. **Editar `.res/setups.json`:**

```json
{
  "setups": [
    // ... configurações existentes ...
    {
      "name": "minha_config",
      "description": "Minha configuração personalizada",
      "settings": [
        {
          "light_name": "Lâmpada 1",
          "color": {
            "red": 100,
            "green": 150,
            "blue": 200,
            "brightness": 220
          }
        }
        // ... adicionar mais lâmpadas ...
      ]
    }
  ]
}
```

2. **Validar:**

```bash
# Verificar JSON válido
python -m json.tool .res/setups.json > /dev/null && echo "✓ JSON válido" || echo "✗ JSON inválido"

# Reiniciar aplicação
uv run uvicorn app:app --reload --port 5000
```

3. **Testar:**

```bash
# Listar configurações (deve aparecer "minha_config")
curl http://localhost:5000/configurations

# Aplicar
curl -X POST http://localhost:5000/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "minha_config"}'
```

---

### Configurar Posicionamento Customizado

1. **Via Web UI:**
   - Acesse http://localhost:5000/positions-config
   - Arraste lâmpadas para posições
   - Clique em "Salvar"

2. **Via API:**

```bash
curl -X POST http://localhost:5000/positions \
  -H "Content-Type: application/json" \
  -d '{
    "lights": [
      {"name": "Hue Play 1", "position": "left", "enabled": true},
      {"name": "Hue Play 2", "position": "right", "enabled": true}
    ]
  }'
```

3. **Manualmente (editar JSON):**

```bash
nano .res/light_positions.json
# Editar e salvar
# Reiniciar app ou recarregar posições
```

---

### Obter Nomes das Lâmpadas

```bash
# Via API
curl http://localhost:5000/api/lights/status | python -m json.tool

# Saída:
{
  "lights": [
    {
      "name": "Lâmpada 1",  # ← Use este nome exato
      "on": true,
      "brightness": 254,
      ...
    }
  ]
}
```

---

## Troubleshooting

### Problema: "Bridge not found"

**Sintomas:**
```
ConnectionError: Não foi possível conectar à bridge Hue
```

**Soluções:**

1. **Verificar IP:**
   ```bash
   ping 192.168.1.100
   ```
   Se não responder, IP está errado.

2. **Verificar `.env`:**
   ```bash
   cat .env | grep BRIDGE_IP
   # Deve mostrar: BRIDGE_IP="192.168.1.100"
   ```

3. **Primeira Conexão (Press Link Button):**
   - Pressione o botão físico na bridge Hue
   - Dentro de 30 segundos, inicie a aplicação
   ```bash
   uv run python main.py
   ```

4. **Firewall:**
   ```bash
   # Testar conectividade HTTP
   curl http://192.168.1.100/api/
   ```

---

### Problema: "Light not found"

**Sintomas:**
```
ValueError: Lâmpada 'lampada 1' não encontrada
```

**Causas:**
- Nome da lâmpada não corresponde exatamente
- Lâmpada está offline/inacessível
- Bridge não conhece a lâmpada

**Soluções:**

1. **Listar lâmpadas disponíveis:**
   ```bash
   curl http://localhost:5000/api/lights/status
   ```

2. **Copiar nome EXATO:**
   ```json
   // Se o nome na bridge é "Lâmpada 1"
   "light_name": "Lâmpada 1"  // ✓ Correto
   "light_name": "lâmpada 1"  // ✗ Errado (case-sensitive)
   "light_name": "Lampada 1"  // ✗ Errado (sem acento)
   ```

3. **Verificar se lâmpada está acessível:**
   - Abrir app Philips Hue
   - Verificar se lâmpada responde
   - Se offline, religar/reconectar

---

### Problema: "Chat agent not available"

**Sintomas:**
```json
{
  "available": false,
  "error": "Agente de chat não inicializado. Verifique as chaves de API."
}
```

**Soluções:**

1. **Verificar variáveis de ambiente:**
   ```bash
   cat .env | grep -E "(CHAT_PROVIDER|CHAT_MODEL|API_KEY)"
   ```

2. **Para OpenAI:**
   ```bash
   # Verificar se key está setada
   echo $OPENAI_API_KEY

   # Testar key
   curl https://api.openai.com/v1/models \
     -H "Authorization: Bearer $OPENAI_API_KEY"
   ```

3. **Verificar créditos:**
   - Acessar https://platform.openai.com/usage
   - Verificar se há créditos disponíveis

4. **Reiniciar aplicação:**
   ```bash
   # Para aplicação (Ctrl+C)
   # Atualizar .env
   # Reiniciar
   uv run uvicorn app:app --reload --port 5000
   ```

---

### Problema: Espelhamento não inicia

**Sintomas:**
```json
{
  "detail": "Erro ao iniciar espelhamento: Screen capture failed"
}
```

**Causas:**
- Permissões de captura de tela não concedidas
- Nenhuma lâmpada ativa em `light_positions.json`
- Biblioteca mss não instalada

**Soluções:**

1. **Permissões (macOS):**
   - System Preferences → Security & Privacy → Screen Recording
   - Adicionar Terminal ou aplicação Python

2. **Permissões (Linux):**
   ```bash
   # Testar captura de tela
   python -c "import mss; with mss.mss() as sct: sct.grab(sct.monitors[1])"
   ```

3. **Verificar `light_positions.json`:**
   ```bash
   cat .res/light_positions.json | grep -E '(enabled|position)'
   ```
   Deve haver pelo menos UMA lâmpada com:
   - `"enabled": true`
   - `"position": "left"` (ou qualquer exceto "none")

4. **Reinstalar dependências:**
   ```bash
   uv sync --reinstall-package mss
   ```

---

### Problema: Cores imprecisas no espelhamento

**Sintomas:**
- Cores na lâmpada não correspondem à tela
- Saturação muito baixa

**Soluções:**

1. **Ajustar `saturation_boost`:**
   ```bash
   curl -X POST http://localhost:5000/mirror/settings \
     -H "Content-Type: application/json" \
     -d '{"saturation_boost": 1.5}'  # Aumentar de 1.2 para 1.5
   ```

2. **Aumentar `brightness`:**
   ```bash
   curl -X POST http://localhost:5000/mirror/settings \
     -H "Content-Type: application/json" \
     -d '{"brightness": 254}'
   ```

3. **Reduzir `smoothing_factor`:**
   ```bash
   curl -X POST http://localhost:5000/mirror/settings \
     -H "Content-Type: application/json" \
     -d '{"smoothing_factor": 0.3}'  # Mais responsivo
   ```

---

### Problema: Alta latência

**Sintomas:**
- Espelhamento com atraso > 1 segundo
- API lenta

**Soluções:**

1. **Reduzir FPS:**
   ```bash
   curl -X POST http://localhost:5000/mirror/settings \
     -H "Content-Type: application/json" \
     -d '{"fps": 15}'  # De 25 para 15
   ```

2. **Verificar carga da bridge:**
   ```bash
   curl http://localhost:5000/api/bridge/status
   ```

3. **Reduzir número de lâmpadas ativas:**
   - Editar `.res/light_positions.json`
   - Setar `"enabled": false` para lâmpadas menos críticas

---

### Problema: JSON inválido

**Sintomas:**
```
JSONDecodeError: Expecting ',' delimiter
```

**Soluções:**

1. **Validar JSON:**
   ```bash
   python -m json.tool .res/setups.json
   # Mostrará linha do erro se inválido
   ```

2. **Ferramentas online:**
   - https://jsonlint.com/
   - Copiar JSON, validar, corrigir

3. **Erros comuns:**
   ```json
   // ✗ Vírgula no último item
   {
     "setups": [
       {"name": "config1"},  // ← OK
       {"name": "config2"},  // ← ERRO: vírgula extra
     ]
   }

   // ✓ Correto
   {
     "setups": [
       {"name": "config1"},
       {"name": "config2"}   // ← SEM vírgula
     ]
   }
   ```

---

## Backup e Restore

### Fazer Backup

```bash
# Backup de todas as configurações
mkdir -p backups
cp .env backups/.env.$(date +%Y%m%d)
cp .res/setups.json backups/setups.$(date +%Y%m%d).json
cp .res/light_positions.json backups/positions.$(date +%Y%m%d).json
```

### Restaurar Backup

```bash
# Restaurar de data específica
cp backups/.env.20260122 .env
cp backups/setups.20260122.json .res/setups.json
cp backups/positions.20260122.json .res/light_positions.json

# Reiniciar aplicação
uv run uvicorn app:app --reload --port 5000
```

---

## Referências

- [Philips Hue Developer Documentation](https://developers.meethue.com/)
- [FastAPI Environment Variables](https://fastapi.tiangolo.com/advanced/settings/)
- [JSON Schema Validator](https://www.jsonschemavalidator.net/)

---

Este documento foi gerado como parte da Fase 3.3 do plano de melhorias.
Última atualização: 2026-01-22
