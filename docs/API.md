# Documentação da API - Marvin Hue

Esta documentação descreve todos os endpoints REST e protocolos WebSocket disponíveis na API do Marvin Hue Controller.

## Informações Gerais

- **Base URL**: `http://localhost:5081`
- **Formato de dados**: JSON
- **Autenticação**: opcional via `API_KEY` (só rotas `/api/*`) — ver [Autenticação opcional](#autenticação-opcional-api_key)
- **CORS**: Configurado para aceitar todas as origens (ajustar para produção)
- **Host padrão**: `API_HOST=0.0.0.0` (LAN). Para só localhost use `127.0.0.1` no `.env`.

---

## Autenticação opcional (`API_KEY`)

Quando a variável de ambiente `API_KEY` está **vazia ou ausente**, a API permanece aberta (rede LAN confiável).

Quando `API_KEY` está **definida**, requisições a caminhos que começam com **`/api/`** devem incluir a chave:

```http
X-API-Key: <sua-chave>
```

ou

```http
Authorization: Bearer <sua-chave>
```

**Resposta 401** se a chave faltar ou estiver errada:

```json
{"detail": "Invalid or missing API key"}
```

**Não exigem chave** (UI local e legado): páginas HTML, `/static/*`, WebSocket do mirror, e endpoints JSON fora de `/api` (`/apply`, `/configurations`, `/mirror/*`, `/positions`).

Exemplos:

```bash
# Sem API_KEY no servidor — aberto
curl http://localhost:5081/api/lights/status

# Com API_KEY configurada
curl -H "X-API-Key: $API_KEY" http://localhost:5081/api/lights/status
curl -H "Authorization: Bearer $API_KEY" http://localhost:5081/api/bridge/status
```

Detalhes de configuração: `docs/CONFIGURATION.md` (seção *Segurança da API*).

---

## Índice

1. [Autenticação opcional](#autenticação-opcional-api_key)
2. [Status e Informações](#status-e-informações)
3. [Catálogo de Lâmpadas (Registry)](#catálogo-de-lâmpadas-registry)
4. [Configurações de Iluminação](#configurações-de-iluminação)
5. [Posicionamento de Lâmpadas](#posicionamento-de-lâmpadas)
6. [Espelhamento de Tela](#espelhamento-de-tela)
7. [Chat com Agente IA](#chat-com-agente-ia)
8. [WebSockets](#websockets)

---

## Status e Informações

### GET /api/bridge/status

Retorna o status de conexão com a Philips Hue Bridge.

**Response 200 (Success):**
```json
{
  "connected": true,
  "bridge_ip": "192.168.1.100",
  "light_count": 8
}
```

**Response 200 (Error):**
```json
{
  "connected": false,
  "error": "Connection timeout"
}
```

**Exemplo com curl:**
```bash
curl http://localhost:5081/api/bridge/status
```

**Exemplo com Python:**
```python
import requests

response = requests.get("http://localhost:5081/api/bridge/status")
status = response.json()
print(f"Connected: {status['connected']}")
```

---

### GET /api/lights/status

Retorna o **estado ao vivo** de todas as lâmpadas na bridge (ligado/desligado, brilho, cor RGB, reachability).

> **Não confundir com o catálogo:** metadados app-side (apelido, sala, notes, soft-delete) ficam em [`GET /api/lights`](#get-apilights). Este endpoint não lê nem grava o SQLite do registry.

**Response 200:**
```json
{
  "lights": [
    {
      "name": "Lâmpada 1",
      "on": true,
      "brightness": 254,
      "reachable": true,
      "color": {
        "r": 255,
        "g": 200,
        "b": 100
      }
    },
    {
      "name": "Hue Play 1",
      "on": false,
      "brightness": 0,
      "reachable": true,
      "color": {
        "r": 50,
        "g": 50,
        "b": 50
      }
    }
  ]
}
```

**Exemplo com curl:**
```bash
curl http://localhost:5081/api/lights/status
```

**Exemplo com Python:**
```python
import requests

response = requests.get("http://localhost:5081/api/lights/status")
lights = response.json()["lights"]

for light in lights:
    print(f"{light['name']}: {'ON' if light['on'] else 'OFF'} - RGB({light['color']['r']}, {light['color']['g']}, {light['color']['b']})")
```

---

## Catálogo de Lâmpadas (Registry)

Catálogo app-side em SQLite (padrão: `.res/marvin_hue.sqlite`, configurável via `APP_DB_PATH`). Armazena metadados das lâmpadas (nickname, room, notes, limite de segurança ocular, vínculo com id da bridge). **Não altera o estado físico** das lâmpadas na Philips Hue Bridge.

| Aspecto | Catálogo (`/api/lights`) | Estado ao vivo (`/api/lights/status`) |
|---------|--------------------------|----------------------------------------|
| Fonte | SQLite da aplicação | Bridge Hue (via `HueController`) |
| Conteúdo | Metadados + soft-delete | on/off, brilho, cor RGB |
| DELETE | Soft-delete no catálogo | — (não existe nestes endpoints) |

**Identidade no sync:** prioriza `bridge_light_id` (preferência pelo Hue `uniqueid` estável; fallback para `light_id` da bridge), depois `name`. Linhas soft-deleted **não** são reativadas no sync por padrão; use `POST /api/lights/sync?reactivate_deleted=true` para reativar.

**Segurança v1:** igual ao restante da API (sem API key obrigatória; assume rede LAN confiável).

---

### GET /api/lights

Lista entradas do catálogo. Por padrão omite soft-deleted.

**Query parameters:**

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `include_deleted` | bool | `false` | Se `true`, inclui entradas com `deleted_at` preenchido |

**Response 200:**
```json
[
  {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Lâmpada 1",
    "nickname": "Mesa",
    "room": "Escritório",
    "notes": null,
    "bridge_light_id": "00:17:88:01:02:03:04:05-0b",
    "eye_safety_limit_pct": null,
    "enabled_for_app": true,
    "deleted_at": null,
    "created_at": "2026-08-08T12:00:00+00:00",
    "updated_at": "2026-08-08T12:00:00+00:00"
  }
]
```

**Exemplo com curl:**
```bash
curl "http://localhost:5081/api/lights"
curl "http://localhost:5081/api/lights?include_deleted=true"
```

**Exemplo com Python:**
```python
import requests

response = requests.get("http://localhost:5081/api/lights")
for light in response.json():
    print(f"{light['name']} ({light.get('nickname') or '—'}) room={light.get('room')}")
```

---

### GET /api/lights/{light_id}

Retorna uma entrada do catálogo pelo UUID da aplicação. Entradas soft-deleted não são retornadas por este endpoint (use listagem com `include_deleted=true`).

**Path parameters:**

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `light_id` | string (UUID) | ID estável da entrada no catálogo |

**Response 200:** mesmo schema de item de `GET /api/lights`.

**Response 404:**
```json
{
  "detail": "..."
}
```

**Exemplo com curl:**
```bash
curl "http://localhost:5081/api/lights/11111111-1111-1111-1111-111111111111"
```

---

### POST /api/lights

Cria uma entrada manual no catálogo (sem criar lâmpada na bridge).

**Request body (`LightCreateRequest`):**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `name` | string | sim | Nome de exibição / match com setups e bridge (1–100 chars; trim) |
| `nickname` | string \| null | não | Apelido amigável |
| `room` | string \| null | não | Rótulo de sala |
| `notes` | string \| null | não | Anotações livres (até 2000 chars) |
| `bridge_light_id` | string \| null | não | Id estável da bridge (preferir Hue `uniqueid`) |
| `eye_safety_limit_pct` | int \| null | não | Limite 0–100 armazenado para uso futuro da app |
| `enabled_for_app` | bool | não | Padrão `true`; se `false`, features da app podem ignorar a lâmpada |

**Request example:**
```json
{
  "name": "Lâmpada 1",
  "nickname": "Mesa",
  "room": "Escritório",
  "notes": null,
  "bridge_light_id": null,
  "eye_safety_limit_pct": null,
  "enabled_for_app": true
}
```

**Response 201:** corpo no schema `LightResponse` (inclui `id`, timestamps).

**Response 409 (nome ativo duplicado):**
```json
{
  "detail": "..."
}
```

**Response 400:** validação de domínio (ex.: nome vazio após trim).

**Exemplo com curl:**
```bash
curl -X POST "http://localhost:5081/api/lights" \
  -H "Content-Type: application/json" \
  -d '{"name":"Hue Iris","nickname":"Canto","room":"Sala"}'
```

**Exemplo com Python:**
```python
import requests

response = requests.post(
    "http://localhost:5081/api/lights",
    json={
        "name": "Hue Iris",
        "nickname": "Canto",
        "room": "Sala",
    },
)
print(response.status_code, response.json())
```

---

### PATCH /api/lights/{light_id}

Atualização parcial de metadados. Campo **omitido** permanece inalterado; JSON `null` **limpa** campos anuláveis (`nickname`, `room`, `notes`, `bridge_light_id`, `eye_safety_limit_pct`).

**Request body (`LightUpdateRequest` — todos opcionais):**

| Campo | Tipo | Notas |
|-------|------|-------|
| `name` | string \| null | Se enviado, não pode ser string em branco |
| `nickname` | string \| null | `null` limpa |
| `room` | string \| null | `null` limpa |
| `notes` | string \| null | `null` limpa |
| `bridge_light_id` | string \| null | `null` limpa |
| `eye_safety_limit_pct` | int \| null | 0–100; `null` limpa |
| `enabled_for_app` | bool \| null | |

**Request example (limpar nickname e desabilitar na app):**
```json
{
  "nickname": null,
  "enabled_for_app": false
}
```

**Response 200:** `LightResponse` atualizado.

**Response 404:** entrada inexistente ou soft-deleted.

**Response 409:** conflito de nome ativo.

**Exemplo com curl:**
```bash
curl -X PATCH "http://localhost:5081/api/lights/11111111-1111-1111-1111-111111111111" \
  -H "Content-Type: application/json" \
  -d '{"nickname":"Esquerda","enabled_for_app":false}'
```

---

### DELETE /api/lights/{light_id}

**Soft-delete** no catálogo: preenche `deleted_at` e remove a entrada das listagens padrão. **Não remove** a lâmpada na bridge Hue e não desliga o dispositivo.

**Response 200:** `LightResponse` com `deleted_at` preenchido.

**Response 404:** id inexistente ou já soft-deleted.

**Exemplo com curl:**
```bash
curl -X DELETE "http://localhost:5081/api/lights/11111111-1111-1111-1111-111111111111"
```

**Exemplo com Python:**
```python
import requests

light_id = "11111111-1111-1111-1111-111111111111"
response = requests.delete(f"http://localhost:5081/api/lights/{light_id}")
print(response.json()["deleted_at"])  # timestamp ISO, não null
```

---

### POST /api/lights/sync

Upsert do catálogo a partir do inventário atual da bridge (`HueController.list_bridge_lights` via `LightRegistryService.refresh_and_sync`). Atualiza `name` / `bridge_light_id` de matches ativos; cria entradas novas; por padrão **não** reativa soft-deleted.

**Query parameters:**

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `reactivate_deleted` | bool | `false` | Se `true`, reativa matches soft-deleted encontrados no inventário |

**Algoritmo (resumo):**
1. Match ativo por `bridge_light_id`, senão por `name` → atualiza se necessário
2. Sem match ativo: se houver soft-deleted com mesmo id/nome e `reactivate_deleted=false` → conta em `skipped_deleted` e **não** cria duplicata
3. Sem match: cria nova entrada ativa
4. Conflito de nome ativo único → **409** (não 500)

**Response 200 (`LightsSyncResponse`):**
```json
{
  "created": 2,
  "updated": 1,
  "unchanged": 5,
  "skipped_deleted": 0,
  "total_bridge": 8
}
```

| Campo | Descrição |
|-------|-----------|
| `created` | Novas linhas no catálogo |
| `updated` | Linhas ativas alteradas (ou reativadas com `reactivate_deleted=true`) |
| `unchanged` | Matches ativos sem mudança de campos |
| `skipped_deleted` | Itens da bridge que bateram só em soft-deleted e foram ignorados |
| `total_bridge` | Tamanho do inventário lido da bridge |

**Response 503:** sync indisponível (bridge não configurada / falha ao refresh). Detalhe genérico, sem vazar exceção interna:
```json
{
  "detail": "Light registry sync unavailable"
}
```

**Exemplo com curl:**
```bash
# Sync seguro (não reativa soft-deleted)
curl -X POST "http://localhost:5081/api/lights/sync"

# Sync reativando soft-deleted que ainda existem na bridge
curl -X POST "http://localhost:5081/api/lights/sync?reactivate_deleted=true"
```

**Exemplo com Python:**
```python
import requests

r = requests.post("http://localhost:5081/api/lights/sync")
print(r.json())
# {'created': 2, 'updated': 0, 'unchanged': 6, 'skipped_deleted': 0, 'total_bridge': 8}
```

---

## Configurações de Iluminação

### GET /configurations

Lista todas as configurações de iluminação disponíveis.

**Response 200:**
```json
[
  {
    "name": "concentration",
    "description": "Ambiente que estimula a concentração"
  },
  {
    "name": "relax",
    "description": "Ambiente relaxante para descanso"
  },
  {
    "name": "cyberpunk_night",
    "description": "Estilo cyberpunk com neon vibrante"
  }
]
```

**Exemplo com curl:**
```bash
curl http://localhost:5081/configurations
```

**Exemplo com Python:**
```python
import requests

response = requests.get("http://localhost:5081/configurations")
configs = response.json()

for config in configs:
    print(f"{config['name']}: {config['description']}")
```

---

### POST /apply

Aplica uma configuração de iluminação específica.

**Request Body:**
```json
{
  "config_name": "concentration",
  "transition_time_secs": 2.0,
  "duration_minutes": null
}
```

**Parâmetros:**
- `config_name` (string, required): Nome da configuração (1-100 caracteres)
- `transition_time_secs` (float, optional): Tempo de transição em segundos (0-60, padrão: 0)
- `duration_minutes` (float, optional): Duração da configuração em minutos (0-1440, padrão: null = indefinido)

**Response 200:**
```json
{
  "message": "Applying configuration concentration",
  "details": {
    "config_name": "concentration",
    "transition_time_secs": 2.0,
    "duration_minutes": null
  }
}
```

**Response 400 (Configuração inválida):**
```json
{
  "detail": "Nome da configuração é obrigatório"
}
```

**Response 404 (Configuração não encontrada):**
```json
{
  "detail": "Configuração 'xyz' não encontrada. Disponíveis: concentration, relax, cyberpunk_night, ..."
}
```

**Response 500 (Erro ao aplicar):**
```json
{
  "detail": "Erro ao aplicar configuração: Connection timeout"
}
```

**Exemplo com curl:**
```bash
# Aplicar configuração imediatamente
curl -X POST http://localhost:5081/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "concentration"}'

# Com transição suave de 3 segundos
curl -X POST http://localhost:5081/apply \
  -H "Content-Type: application/json" \
  -d '{"config_name": "relax", "transition_time_secs": 3.0}'
```

**Exemplo com Python:**
```python
import requests

# Aplicar configuração com transição
data = {
    "config_name": "cyberpunk_night",
    "transition_time_secs": 2.5
}

response = requests.post("http://localhost:5081/apply", json=data)
result = response.json()
print(result["message"])
```

---

## Posicionamento de Lâmpadas

### GET /positions

Retorna a configuração de posicionamento das lâmpadas para espelhamento de tela.

**Response 200:**
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
      "name": "Lâmpada 1",
      "position": "none",
      "enabled": true
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

**Exemplo com curl:**
```bash
curl http://localhost:5081/positions
```

---

### POST /positions

Salva a configuração de posicionamento das lâmpadas.

**Request Body:**
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
    }
  ]
}
```

**Parâmetros:**
- `lights` (array, required): Lista de configurações de lâmpadas (1-50 itens)
  - `name` (string, required): Nome da lâmpada (1-50 caracteres)
  - `position` (string, required): Posição (none|left|right|top|bottom|top-left|top-right|bottom-left|bottom-right|center|ambient)
  - `enabled` (boolean, required): Se a lâmpada está habilitada

**Response 200:**
```json
{
  "message": "Configuração salva com sucesso"
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/positions \
  -H "Content-Type: application/json" \
  -d '{
    "lights": [
      {"name": "Hue Play 1", "position": "left", "enabled": true},
      {"name": "Hue Play 2", "position": "right", "enabled": true}
    ]
  }'
```

**Exemplo com Python:**
```python
import requests

data = {
    "lights": [
        {"name": "Hue Play 1", "position": "left", "enabled": True},
        {"name": "Hue Play 2", "position": "right", "enabled": True},
        {"name": "Fita Led", "position": "top", "enabled": True}
    ]
}

response = requests.post("http://localhost:5081/positions", json=data)
print(response.json()["message"])
```

---

### POST /positions/reset

Restaura a configuração padrão de posicionamento.

**Response 200:**
```json
{
  "lights": [...],
  "positions": [...]
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/positions/reset
```

---

## Espelhamento de Tela e Música

Dois modos mutuamente exclusivos (iniciar um para o outro):

| `mode` | Fonte | Perfis |
|--------|--------|--------|
| `screen` (padrão) | Captura de regiões da tela | `cinema`, `fps`, `ambient` |
| `audio` | Áudio do sistema (sink monitor PulseAudio/PipeWire) | `party`, `chill`, `pulse` + intensidade `subtle`/`moderate`/`high`/`extreme` |

No modo **audio**, as posições de `light_positions.json` mapeiam bandas e estereo:
- **grave (bass):** `bottom`, `bottom-left`, `bottom-right` → vermelhos/laranjas
- **médio (mid):** `left`, `right`, `center`, `ambient` → verdes/roxos (L/R via `stereo_bias`)
- **agudo (treble):** `top`, `top-left`, `top-right` → azuis/cianos

**Transporte:** `rest` (phue) ou `entertainment` (DTLS HueStream). Com `ENTERTAINMENT_ENABLED=false` ou sem credenciais, o comportamento é idêntico ao REST.

### POST /mirror/start

Inicia o espelhamento de tela ou de música.

**Request Body:**
```json
{
  "mode": "screen",
  "fps": 25,
  "brightness": 200,
  "profile": "cinema"
}
```

**Áudio / música:**
```json
{
  "mode": "audio",
  "profile": "party",
  "fps": 30,
  "brightness": 220,
  "transport_preference": "auto",
  "area_id": null
}
```

**Parâmetros:**
- `mode` (string, optional): `screen` | `audio` (padrão `screen`)
- `fps` (int, optional): Taxa de atualização em FPS (1-60). Se omitido com profile, usa o do profile; sem profile, padrão 25 (screen) / 30 (audio); Entertainment sem profile → `ENTERTAINMENT_FPS`
- `brightness` (int, optional): Brilho das lâmpadas (0-254)
- `profile` (string, optional): screen=`cinema`|`fps`|`ambient`; audio=`party`|`chill`|`pulse`|`subtle`|`moderate`|`high`|`extreme`
- `transport_preference` (string, optional): `auto` | `rest` | `entertainment`
- `area_id` (string, optional): id da área Entertainment

**Perfis de tela:**
| Perfil | fps | brightness | sat | smoothing | transition |
|--------|-----|------------|-----|-----------|------------|
| cinema | 12 | 160 | 1.1 | 0.35 | 2 |
| fps | 30 | 200 | 1.4 | 0.7 | 0 |
| ambient | 8 | 120 | 1.0 | 0.25 | 3 |

**Perfis de áudio:**
| Perfil | fps | brightness | smoothing | transition | energy_gain |
|--------|-----|------------|-----------|------------|-------------|
| party | 30 | 220 | 0.55 | 0 | 1.4 |
| chill | 20 | 140 | 0.2 | 3 | 0.85 |
| pulse | 35 | 240 | 0.75 | 0 | 1.6 |

**Response 503 (sem dispositivo de áudio):**
```json
{
  "detail": "Nenhum dispositivo de áudio encontrado. No Linux, use PulseAudio/PipeWire..."
}
```

**Response 200:**
```json
{
  "message": "Espelhamento iniciado",
  "status": {
    "running": true,
    "fps": 25,
    "brightness": 200,
    "current_colors": {
      "Hue Play 1": [255, 100, 50],
      "Hue Play 2": [50, 150, 255]
    }
  }
}
```

**Response 400 (Já ativo):**
```json
{
  "detail": "Espelhamento já está ativo"
}
```

**Response 500 (Erro ao iniciar):**
```json
{
  "detail": "Erro ao iniciar espelhamento: Screen capture failed"
}
```

**Exemplo com curl:**
```bash
# Iniciar com configurações padrão
curl -X POST http://localhost:5081/mirror/start \
  -H "Content-Type: application/json" \
  -d '{}'

# Iniciar com 30 FPS e brilho 150
curl -X POST http://localhost:5081/mirror/start \
  -H "Content-Type: application/json" \
  -d '{"fps": 30, "brightness": 150}'
```

**Exemplo com Python:**
```python
import requests

# Iniciar espelhamento
data = {
    "fps": 25,
    "brightness": 200
}

response = requests.post("http://localhost:5081/mirror/start", json=data)
status = response.json()
print(f"Status: {status['message']}")
```

---

### POST /mirror/stop

Para o espelhamento de tela.

**Response 200:**
```json
{
  "message": "Espelhamento parado"
}
```

**Response 400:**
```json
{
  "detail": "Espelhamento não está ativo"
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/mirror/stop
```

---

### GET /mirror/entertainment/status

Status do transporte Entertainment.

**Response 200:**
```json
{
  "enabled": false,
  "ready": false,
  "streaming": false,
  "active_area_id": null,
  "areas": [],
  "transport": "rest",
  "default_area_id": null,
  "fps_default": 40
}
```

### POST /mirror/entertainment/pair

Pareia com a bridge (**pressione o botão de link antes**). Salva credenciais em `ENTERTAINMENT_CREDS_FILE`.

**Request Body (opcional):**
```json
{ "device_type": "marvin_hue#entertainment" }
```

**Response 200:**
```json
{
  "ok": true,
  "username_suffix": "ab12",
  "creds_file": ".res/hue_entertainment_creds.json",
  "message": "Pairing OK. Defina ENTERTAINMENT_ENABLED=true e reinicie se ainda estiver desabilitado."
}
```

### GET /mirror/entertainment/areas

Lista áreas Entertainment (vazio se unpaired).

**Response 200:**
```json
{
  "ready": true,
  "areas": [
    {
      "id": "…",
      "name": "Sala",
      "channel_count": 4,
      "channels": [{ "channel_id": 0, "name": "Hue Play 1", "service_id": "…" }]
    }
  ]
}
```

### GET /mirror/status

Retorna o status unificado do espelhamento ativo. Campos extras: `transport`, `entertainment_enabled`, `entertainment_ready`, `entertainment_area_id`, `beat` (audio).

**Response 200 (modo tela):**
```json
{
  "running": true,
  "mode": "screen",
  "fps": 25,
  "brightness": 200,
  "saturation_boost": 1.2,
  "smoothing_factor": 0.5,
  "transition_time": 1,
  "bass": 0.0,
  "mid": 0.0,
  "treble": 0.0,
  "colors": {
    "Hue Play 1": [255, 100, 50],
    "Hue Play 2": [50, 150, 255]
  }
}
```

**Response 200 (modo áudio):**
```json
{
  "running": true,
  "mode": "audio",
  "fps": 30,
  "brightness": 220,
  "active_profile": "party",
  "bass": 0.72,
  "mid": 0.41,
  "treble": 0.18,
  "colors": {
    "Hue Play 1": [120, 40, 180]
  }
}
```

`mode` é `null` quando nenhum espelhamento está ativo. `bass` / `mid` / `treble` estão em 0–1.

**Exemplo com curl:**
```bash
curl http://localhost:5081/mirror/status
```

---

### GET /mirror/profiles

Lista perfis de tela (`profiles`) e de áudio (`audio_profiles`).

```json
{
  "profiles": { "cinema": { ... }, "fps": { ... }, "ambient": { ... } },
  "audio_profiles": { "party": { ... }, "chill": { ... }, "pulse": { ... } }
}
```

### POST /mirror/profile

Aplica um perfil sem reiniciar o loop.

```json
{ "profile": "cinema" }
```

```json
{ "mode": "audio", "profile": "party" }
```

### POST /mirror/settings

Atualiza configurações do espelhamento em tempo real (sem parar). Aceita `profile` e `mode` opcionais; campos explícitos sobrescrevem o perfil.

**Request Body:**
```json
{
  "mode": "screen",
  "fps": 30,
  "brightness": 180,
  "saturation_boost": 1.5,
  "smoothing_factor": 0.3,
  "transition_time": 0.5,
  "profile": "fps"
}
```

**Parâmetros (todos opcionais):**
- `mode` (string): `screen` | `audio` (padrão: modo ativo ou screen)
- `fps` (int): Taxa de atualização (1-60)
- `brightness` (int): Brilho (0-254)
- `saturation_boost` (float): Boost de saturação (0-3, modo tela)
- `smoothing_factor` (float): Fator de suavização (0-1)
- `transition_time` (float): Tempo de transição (0-10)
- `energy_gain` (float): Ganho de energia 0.1–3 (modo audio)
- `profile` (string): screen=`cinema`|`fps`|`ambient`; audio=`party`|`chill`|`pulse`

**Response 200:**
```json
{
  "message": "Configurações atualizadas",
  "status": {
    "running": true,
    "fps": 30,
    "brightness": 180,
    ...
  }
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/mirror/settings \
  -H "Content-Type: application/json" \
  -d '{"fps": 30, "saturation_boost": 1.5}'
```

**Exemplo com Python:**
```python
import requests

# Ajustar configurações em tempo real
settings = {
    "fps": 30,
    "brightness": 180,
    "saturation_boost": 1.5
}

response = requests.post("http://localhost:5081/mirror/settings", json=settings)
print(response.json()["message"])
```

---

## Chat com Agente IA

### GET /api/chat/status

Retorna o status do agente de chat.

**Response 200 (Disponível):**
```json
{
  "available": true,
  "provider": "openai",
  "model": "gpt-4o-mini"
}
```

**Response 200 (Indisponível):**
```json
{
  "available": false,
  "error": "Agente de chat não inicializado. Verifique as chaves de API."
}
```

**Exemplo com curl:**
```bash
curl http://localhost:5081/api/chat/status
```

---

### POST /api/chat/message

Envia uma mensagem para o agente e retorna a resposta.

**Request Body:**
```json
{
  "message": "Ative a configuração de concentração"
}
```

**Parâmetros:**
- `message` (string, required): Mensagem do usuário (1-1000 caracteres)

**Response 200:**
```json
{
  "response": "Configuração 'concentration' aplicada com sucesso! As lâmpadas estão agora configuradas para estimular a concentração.",
  "success": true
}
```

**Response 400:**
```json
{
  "detail": "Mensagem não pode ser vazia"
}
```

**Response 503:**
```json
{
  "detail": "Agente de chat não disponível. Verifique as configurações."
}
```

**Response 500:**
```json
{
  "detail": "Erro ao processar mensagem: API key not found"
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Quais configurações estão disponíveis?"}'
```

**Exemplo com Python:**
```python
import requests

data = {"message": "Ative um ambiente relaxante"}
response = requests.post("http://localhost:5081/api/chat/message", json=data)
result = response.json()

if result["success"]:
    print(f"Agente: {result['response']}")
```

---

### POST /api/chat/clear

Limpa o histórico de conversação.

**Response 200:**
```json
{
  "message": "Histórico limpo com sucesso"
}
```

**Exemplo with curl:**
```bash
curl -X POST http://localhost:5081/api/chat/clear
```

---

### POST /api/chat/configure

Reconfigura o agente de chat com novos parâmetros.

**Request Body:**
```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "temperature": 0.7
}
```

**Parâmetros:**
- `provider` (string, required): Provedor (openai|anthropic|ollama)
- `model` (string, required): Nome do modelo (1-100 caracteres)
- `temperature` (float, optional): Temperatura (0-2, padrão: 0.7)

**Response 200:**
```json
{
  "message": "Agente reconfigurado com sucesso",
  "provider": "openai",
  "model": "gpt-4o"
}
```

**Response 500:**
```json
{
  "detail": "Erro ao reconfigurar agente: Invalid API key"
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/api/chat/configure \
  -H "Content-Type: application/json" \
  -d '{"provider": "anthropic", "model": "claude-3-sonnet", "temperature": 0.5}'
```

---

## WebSockets

### WS /ws/mirror

WebSocket para streaming de cores em tempo real durante o espelhamento.

**Mensagens enviadas pelo servidor:**

```json
{
  "running": true,
  "fps": 25,
  "brightness": 200,
  "current_colors": {
    "Hue Play 1": [255, 100, 50],
    "Hue Play 2": [50, 150, 255]
  }
}
```

Frequência: 10 FPS (a cada 100ms quando espelhamento está ativo)

**Mensagens enviadas pelo cliente:**

```json
// Iniciar espelhamento
{
  "action": "start",
  "fps": 25,
  "brightness": 200
}

// Parar espelhamento
{
  "action": "stop"
}

// Atualizar configurações
{
  "action": "settings",
  "fps": 30,
  "brightness": 180,
  "saturation_boost": 1.5
}
```

**Exemplo com JavaScript:**
```javascript
// Conectar ao WebSocket
const ws = new WebSocket('ws://localhost:5081/ws/mirror');

// Receber atualizações
ws.onmessage = (event) => {
  const status = JSON.parse(event.data);
  console.log('Status:', status);

  if (status.running) {
    console.log('Colors:', status.current_colors);
  }
};

// Iniciar espelhamento
ws.send(JSON.stringify({
  action: 'start',
  fps: 25,
  brightness: 200
}));

// Atualizar configurações
ws.send(JSON.stringify({
  action: 'settings',
  fps: 30
}));

// Parar espelhamento
ws.send(JSON.stringify({
  action: 'stop'
}));
```

**Exemplo com Python:**
```python
import asyncio
import websockets
import json

async def mirror_websocket():
    uri = "ws://localhost:5081/ws/mirror"

    async with websockets.connect(uri) as websocket:
        # Iniciar espelhamento
        await websocket.send(json.dumps({
            "action": "start",
            "fps": 25,
            "brightness": 200
        }))

        # Receber atualizações
        while True:
            message = await websocket.recv()
            status = json.loads(message)

            if status["running"]:
                print(f"Colors: {status['current_colors']}")

            # Parar após 10 segundos
            await asyncio.sleep(10)
            await websocket.send(json.dumps({"action": "stop"}))
            break

asyncio.run(mirror_websocket())
```

---

### WS /ws/chat

WebSocket para comunicação em tempo real com o agente de chat.

**Mensagens enviadas pelo servidor:**

```json
// Indicador de digitação
{
  "type": "typing",
  "content": true
}

// Resposta do agente
{
  "type": "response",
  "content": "Configuração aplicada com sucesso!"
}

// Erro
{
  "type": "error",
  "content": "Erro: Configuração não encontrada"
}

// Confirmação de limpeza
{
  "type": "cleared",
  "content": "Histórico limpo"
}
```

**Mensagens enviadas pelo cliente:**

```json
// Enviar mensagem
{
  "action": "message",
  "message": "Ative a configuração de concentração"
}

// Limpar histórico
{
  "action": "clear"
}
```

**Exemplo com JavaScript:**
```javascript
const ws = new WebSocket('ws://localhost:5081/ws/chat');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.type) {
    case 'typing':
      console.log('Agente está digitando...');
      break;
    case 'response':
      console.log('Agente:', data.content);
      break;
    case 'error':
      console.error('Erro:', data.content);
      break;
  }
};

// Enviar mensagem
ws.send(JSON.stringify({
  action: 'message',
  message: 'Quais configurações estão disponíveis?'
}));

// Limpar histórico
ws.send(JSON.stringify({
  action: 'clear'
}));
```

---

## Páginas HTML

### GET /

Página principal da aplicação.

**Response**: `text/html`

Retorna a interface web principal com controle de configurações.

---

### GET /positions-config

Página de configuração de posicionamento de lâmpadas.

**Response**: `text/html`

Interface para configurar quais lâmpadas espelham quais regiões da tela.

---

### GET /mirror

Página de controle do espelhamento de tela.

**Response**: `text/html`

Interface para iniciar/parar espelhamento e ajustar configurações em tempo real.

---

### GET /chat

Página de chat com o agente IA.

**Response**: `text/html`

Interface de chat para controlar as lâmpadas por linguagem natural.

---

## Códigos de Status HTTP

| Código | Significado | Uso |
|--------|-------------|-----|
| 200 | OK | Requisição bem-sucedida |
| 201 | Created | Recurso criado (ex: `POST /api/lights`) |
| 400 | Bad Request | Parâmetros inválidos ou estado inválido |
| 404 | Not Found | Recurso não encontrado (ex: light id inexistente no catálogo) |
| 409 | Conflict | Conflito de recurso (ex: nome ativo duplicado no catálogo) |
| 500 | Internal Server Error | Erro no servidor |
| 503 | Service Unavailable | Serviço não disponível (ex: chat agent não inicializado; sync do registry indisponível) |

---

## Notas de Implementação

### Validação de Inputs

Todos os endpoints validam inputs usando Pydantic:
- Strings são sanitizadas (caracteres especiais removidos)
- Ranges numéricos são validados
- Padrões regex são aplicados quando necessário

### Segurança

**Recomendações para produção:**
1. Implementar autenticação (API keys, OAuth, etc)
2. Configurar CORS para domínios específicos
3. Adicionar rate limiting (ex: slowapi)
4. Usar HTTPS
5. Validar origem dos WebSockets

### Limitações

- **Bridge Hue**: Taxa de atualização limitada (~10-25 req/s)
- **Espelhamento**: FPS máximo recomendado: 25-30
- **WebSocket**: 10 FPS para updates de UI (25 FPS para lâmpadas)
- **Chat**: Depende de API externa (OpenAI, Anthropic, etc)

### Performance

- Light cache: Lookup O(1) por nome
- JSON assíncrono: Operações de arquivo não bloqueantes
- Executor thread pool: Operações síncronas executadas em threads separadas

---

## Troubleshooting

### Erro: "Bridge not found"

Verificar:
1. IP da bridge está correto no `.env`
2. Bridge está ligada e acessível na rede
3. Botão da bridge foi pressionado (primeira conexão)

### Erro: "Light not found"

Verificar:
1. Nome da lâmpada está correto (case-sensitive)
2. Lâmpada está ligada e acessível
3. Executar `GET /api/lights/status` para listar lâmpadas disponíveis

### Erro: "Chat agent not available"

Verificar:
1. Variável de ambiente `OPENAI_API_KEY` ou equivalente está configurada
2. `CHAT_PROVIDER` e `CHAT_MODEL` estão corretos
3. API key é válida e tem créditos

### Espelhamento não inicia

Verificar:
1. Permissões de captura de tela no sistema operacional
2. Arquivo `light_positions.json` existe e é válido
3. Pelo menos uma lâmpada tem `enabled: true` e `position != "none"`

---

## Exemplos Completos

### Script Python: Aplicar Configuração

```python
import requests
import time

BASE_URL = "http://localhost:5081"

def apply_config(name, transition=0):
    """Aplica uma configuração de iluminação."""
    response = requests.post(
        f"{BASE_URL}/apply",
        json={
            "config_name": name,
            "transition_time_secs": transition
        }
    )
    return response.json()

def list_configs():
    """Lista todas as configurações disponíveis."""
    response = requests.get(f"{BASE_URL}/configurations")
    return response.json()

# Listar configurações
configs = list_configs()
print("Configurações disponíveis:")
for cfg in configs:
    print(f"  - {cfg['name']}: {cfg['description']}")

# Aplicar configuração com transição
result = apply_config("concentration", transition=2.0)
print(f"\n{result['message']}")

# Aguardar 60 segundos
time.sleep(60)

# Aplicar outra configuração
result = apply_config("relax", transition=3.0)
print(f"{result['message']}")
```

### Script Python: Controlar Espelhamento

```python
import requests
import time

BASE_URL = "http://localhost:5081"

def start_mirror(fps=25, brightness=200):
    """Inicia o espelhamento."""
    response = requests.post(
        f"{BASE_URL}/mirror/start",
        json={"fps": fps, "brightness": brightness}
    )
    return response.json()

def stop_mirror():
    """Para o espelhamento."""
    response = requests.post(f"{BASE_URL}/mirror/stop")
    return response.json()

def get_status():
    """Obtém status do espelhamento."""
    response = requests.get(f"{BASE_URL}/mirror/status")
    return response.json()

# Iniciar espelhamento
print("Iniciando espelhamento...")
result = start_mirror(fps=25, brightness=200)
print(result["message"])

# Aguardar 30 segundos
time.sleep(30)

# Verificar status
status = get_status()
print(f"\nStatus: {status['running']}")
print(f"Cores atuais: {status['current_colors']}")

# Parar espelhamento
print("\nParando espelhamento...")
result = stop_mirror()
print(result["message"])
```

### Script JavaScript: WebSocket Chat

```javascript
class HueChatClient {
  constructor(url = 'ws://localhost:5081/ws/chat') {
    this.ws = new WebSocket(url);
    this.setupHandlers();
  }

  setupHandlers() {
    this.ws.onopen = () => {
      console.log('Connected to chat');
    };

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleMessage(data);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  handleMessage(data) {
    switch(data.type) {
      case 'typing':
        console.log('Agent is typing...');
        break;
      case 'response':
        console.log('Agent:', data.content);
        break;
      case 'error':
        console.error('Error:', data.content);
        break;
      case 'cleared':
        console.log('History cleared');
        break;
    }
  }

  sendMessage(message) {
    this.ws.send(JSON.stringify({
      action: 'message',
      message: message
    }));
  }

  clearHistory() {
    this.ws.send(JSON.stringify({
      action: 'clear'
    }));
  }
}

// Uso
const chat = new HueChatClient();

// Enviar mensagens após conexão
setTimeout(() => {
  chat.sendMessage('Ative a configuração de concentração');
}, 1000);
```

---

## Future / Roadmap — Hue Entertainment

Planned extensions to mirror endpoints (not yet implemented): Entertainment area listing and pairing, `transport` field on start/status (`rest` | `entertainment`), optional intensity profiles, and status fields for stream area name / fps. Full design and task breakdown: [`docs/plans/2026-08-08-hue-entertainment-music-upgrade.md`](plans/2026-08-08-hue-entertainment-music-upgrade.md). Until that lands, audio/screen mirror continue to use REST (`phue`) only.

---

## Changelog da API

### Versão 2.0.0 (Atual)
- Adicionado chat com agente IA
- Adicionado espelhamento de tela
- Refatoração completa para FastAPI
- WebSockets para updates em tempo real
- Validação de inputs com Pydantic

### Versão 1.0.0
- Versão inicial
- Endpoints básicos de configuração
- Suporte para Philips Hue Bridge

---

Esta documentação foi gerada automaticamente pelo Marvin Hue Controller v2.0.0
