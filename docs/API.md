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

**Não exigem chave** (UI local e legado): páginas HTML, `/static/*`, WebSocket do mirror, e endpoints JSON fora de `/api` (`/apply`, `/lights/off`, `/configurations`, `/mirror/*`, `/positions`). Os aliases sob `/api` (`/api/apply`, `/api/lights/off`, `/api/configurations`, `/api/mirror/*`, `/api/positions`) exigem a chave.

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

### GET /api/health

Agrega a saúde do sistema numa resposta só: bridge, lâmpadas, espelhamento, chat, catálogo e agendamentos. Sempre responde 200. Se uma sonda falhar, o bloco dela vem degradado (por exemplo `connected: false` ou contagens zeradas) em vez de erro. A página **Saúde** (`/health`) e a tool de chat `get_system_health` leem este payload.

**Response 200:**
```json
{
  "bridge": {"connected": true, "bridge_ip": "192.168.1.100", "light_count": 9},
  "lights": {"total": 9, "unreachable": 0, "disabled_in_app": 0},
  "mirror": {
    "running": true,
    "mode": "audio",
    "fps": 30,
    "profile": "party",
    "audio": {"bass": 0.5, "mid": 0.25, "treble": 0.12, "beat": 1.0, "config_name": "relax"}
  },
  "chat": {"available": false, "reason": "Provider 'openai' sem OPENAI_API_KEY configurada."},
  "registry": {"count": 9, "db_path": ".res/marvin_hue.sqlite", "last_sync_at": null},
  "schedules": {"enabled_count": 2, "runner_alive": true},
  "timestamp": "2026-10-21T12:00:00+00:00"
}
```

**Bloco `mirror`** (reflete o espelhamento ativo, de tela ou de música; se os dois estiverem rodando, o de música prevalece, como em `GET /mirror/status`):

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `running` | bool | Algum espelhamento está ativo |
| `mode` | `"screen"` \| `"audio"` \| null | Espelhamento ativo; null quando parado |
| `fps` | int \| null | FPS do espelhamento ativo; null quando parado |
| `profile` | string \| null | Perfil ativo (`active_profile`); null quando parado ou sem perfil |
| `audio` | object \| null | Só com `mode: "audio"`: níveis `bass`/`mid`/`treble`/`beat` (0–1) e `config_name` |

Uma falha ao consultar o áudio cai para o status da tela: um erro de áudio não esconde um espelhamento de tela rodando.

**Exemplo com curl:**
```bash
curl http://localhost:5081/api/health
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

**Query parameters:**

| Parâmetro | Tipo | Padrão | Descrição |
|-----------|------|--------|-----------|
| `include_settings` | boolean | `false` | Quando `true`, cada configuração traz também `settings` (cor por lâmpada + prévia). Sem o parâmetro, a resposta é a lista simples abaixo, inalterada. |

`/configurations` não exige `API_KEY`. O alias `/api/configurations` (sujeito a `API_KEY` quando configurada) aceita o mesmo parâmetro.

**Response 200 (padrão):**
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

**Response 200 (`include_settings=true`):**
```json
[
  {
    "name": "afternoon_delight",
    "description": "...",
    "settings": [
      {
        "light_name": "Lâmpada 1",
        "color": {"red": 255, "green": 230, "blue": 200, "brightness": 150},
        "preview": {"r": 255, "g": 221, "b": 180, "brightness": 150, "enabled": true}
      }
    ]
  }
]
```

| Campo | Descrição |
|-------|-----------|
| `settings[].light_name` | Nome exato da lâmpada na bridge Hue |
| `settings[].color` | Cor RGBA como está em `.res/setups.json` (brilho 0–254) |
| `settings[].preview.r/g/b` | Cor que a lâmpada deve mostrar após o apply. Calculada pelo mesmo pipeline RGB → XY → RGB usado em `GET /api/lights/status`, então é comparável ao estado real |
| `settings[].preview.brightness` | Brilho efetivo (0–254) após o limite de eye safety (Fita Led, Led cima) |
| `settings[].preview.enabled` | `false` quando a lâmpada está com `enabled_for_app` desligado no registro; o apply não altera essa lâmpada |

Nada é enviado à bridge: o resultado serve apenas para a prévia na tela Controle (`/`).

**Exemplo com curl:**
```bash
curl "http://localhost:5081/configurations?include_settings=true"
```

---

### GET /configurations/favorites

Lista os nomes das cenas marcadas como favoritas na tela Controle (`/`). Os favoritos ficam no SQLite do app (tabela `scene_favorites`).

A resposta traz só as cenas que existem em `.res/setups.json` naquele momento. Se uma cena favorita for renomeada ou removida, o favorito continua no banco, mas não aparece aqui; quando a cena volta, o favorito volta junto. `GET /configurations` não muda: os favoritos têm rota própria.

`/configurations/favorites` não exige `API_KEY`. O alias `/api/configurations/favorites` fica sujeito a `API_KEY` quando configurada. O mesmo vale para `PUT` e `DELETE` abaixo.

**Response 200:**
```json
{
  "favorites": ["concentration", "relax"]
}
```

**Exemplo com curl:**
```bash
curl http://localhost:5081/configurations/favorites
```

---

### PUT /configurations/favorites/{name}

Marca a cena `name` como favorita. É idempotente: repetir a chamada devolve o mesmo resultado. Nomes com espaço ou acento vão codificados na URL (`Pôr do sol` → `P%C3%B4r%20do%20sol`).

**Response 200:**
```json
{
  "name": "relax",
  "favorite": true
}
```

**Response 404:** a cena não existe em `.res/setups.json`.
```json
{
  "detail": "Configuração 'nao_existe' não encontrada"
}
```

**Exemplo com curl:**
```bash
curl -X PUT http://localhost:5081/configurations/favorites/relax
```

---

### DELETE /configurations/favorites/{name}

Desmarca a cena `name`. É idempotente: um nome que não estava marcado, ou que nem existe, também devolve 204.

**Response 204:** sem corpo.

**Exemplo com curl:**
```bash
curl -X DELETE http://localhost:5081/configurations/favorites/relax
```

O backup (`GET /api/backup/export`) inclui o membro `favorites.json` com todos os nomes guardados, inclusive os de cenas que não existem mais. Na importação, `merge` faz a união com os favoritos locais e `replace` substitui o conjunto. Bundles antigos, sem esse membro, não alteram os favoritos. Um `favorites.json` presente com `null` ou qualquer valor que não seja lista de strings faz a importação falhar (400) antes de qualquer escrita; o limite é 1000 nomes de até 200 caracteres. A resposta da importação traz `favorites: {"added", "removed", "total"}` (diferença entre os conjuntos antes e depois), com `"skipped": true` quando o membro está ausente. O backup só inclui `favorites.json` quando o repositório de favoritos está ativo.

Nomes de cena com `/` funcionam em `PUT`/`DELETE` (a rota usa `{name:path}`).

### GET /configurations/last-applied

Devolve a última cena aplicada. A tela Controle (`/`) usa esta rota para já abrir com a cena selecionada, sem prévia, e com o selo "Última aplicada · há X".

O registro fica no SQLite do app (tabela `last_applied_scene`, migração v6, uma linha só). Ele é gravado pelo `ApplyConfigService` sempre que ao menos uma lâmpada aplica (HTTP 200 ou 207). O `source` diz quem aplicou:

| `source` | Origem |
|----------|--------|
| `apply` | `POST /apply` (tela Controle) |
| `group` | `POST /api/groups/{id}/apply` e agendamentos `apply_group` |
| `schedule` | agendamentos `apply_config` |
| `chat` | tool `apply_config` do chat (REST e WebSocket); passa pelo mesmo `ApplyConfigService`, então também grava o snapshot "before apply" para o undo |

Uma aplicação em que todas as lâmpadas falham (500) não muda o registro.

O registro é limpo (`name` volta a `null`) quando as lâmpadas deixam de mostrar a cena:

| Gatilho | `source` gravado |
|---------|------------------|
| `POST /lights/off` com ao menos uma lâmpada desligada | `lights_off` |
| `POST /api/history/undo` que restaurou ao menos uma lâmpada (`restored_count > 0`) | `undo` |
| Agendamento `power_off` sem `group_id` (casa inteira) com ao menos uma lâmpada afetada | `schedule_off` |
| Início do espelhamento de tela ou de música (`POST /mirror/start`) | `mirror` |

O `power_off` de um grupo não limpa o registro, porque as outras lâmpadas continuam na cena. Gravar e limpar são best-effort: falhas só geram log e nunca afetam a ação que as disparou.

Os três campos vêm `null` quando nada foi aplicado ainda, quando o registro foi limpo ou quando a cena não existe mais em `.res/setups.json`. Nesse último caso o nome continua no banco e volta a aparecer se a cena voltar.

`/configurations/last-applied` não exige `API_KEY`, por decisão de projeto: a tela Controle na LAN precisa dela sem chave, como `/configurations`. Isso expõe na LAN o nome da última cena e o horário da última atividade de iluminação. O alias `/api/configurations/last-applied` fica sujeito a `API_KEY` quando configurada.

A tela Controle consulta esta rota de novo quando a aba volta a ficar visível: só o selo é atualizado, e a seleção feita pelo usuário não muda.

**Response 200:**
```json
{
  "name": "relax",
  "source": "apply",
  "applied_at": "2026-10-21T10:34:29.119451+00:00"
}
```

`applied_at` é ISO 8601 em UTC.

```bash
curl http://localhost:5081/configurations/last-applied
```

---

### POST /apply

Aplica uma configuração de iluminação específica. O corpo reflete o `ApplyResult`
por lâmpada (`applied` / `failed`). `duration_minutes` é aceito no request por
compatibilidade e **é ignorado** — não há timer nem restauração automática.

**Request Body:**
```json
{
  "config_name": "concentration",
  "transition_time_secs": 2.0
}
```

**Parâmetros:**
- `config_name` (string, required): Nome da configuração (1-100 caracteres)
- `transition_time_secs` (float, optional): Tempo de transição em segundos (0-60, padrão: 0)
- `duration_minutes` (float, optional): Campo legado; ignorado. Não agenda duração.

**Response 200 (todas as lâmpadas aplicadas):**
```json
{
  "message": "Applying configuration concentration",
  "applied": ["Lâmpada 1", "Lâmpada 2"],
  "failed": [],
  "details": {
    "config_name": "concentration",
    "transition_time_secs": 2.0
  }
}
```

**Response 207 (aplicação parcial):**
```json
{
  "message": "Configuração 'concentration' aplicada parcialmente; algumas lâmpadas falharam",
  "applied": ["Lâmpada 1"],
  "failed": [{"name": "Lâmpada 2", "error": "boom"}],
  "details": {
    "config_name": "concentration",
    "transition_time_secs": 0.0
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

**Response 500 (todas as tentativas falharam):**
```json
{
  "message": "Falha ao aplicar configuração 'concentration'; nenhuma lâmpada aplicada",
  "applied": [],
  "failed": [{"name": "Lâmpada 1", "error": "boom"}],
  "details": {
    "config_name": "concentration",
    "transition_time_secs": 0.0
  }
}
```

Erros inesperados (exceção ao aplicar, fora do `ApplyResult`) ainda usam
`{"detail": "Erro ao aplicar configuração: ..."}`.

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

### POST /lights/off

Desliga todas as lâmpadas habilitadas no app (`enabled_for_app=true`) que a
bridge conhece. É o endpoint do botão **Desligar Todas** da tela Controle.
Lâmpadas desabilitadas no catálogo são ignoradas e não aparecem em `applied`
nem em `failed`.

Ordem das operações:

1. Se o espelhamento de tela ou de música estiver ativo, ele é parado primeiro
   (senão o loop de captura religaria as lâmpadas). A parada grava o snapshot
   `mirror_stop` de sempre. Se parar falhar, o desligamento continua.
2. O servidor lê o estado da bridge uma vez e grava um snapshot da cena atual
   no histórico (`source: "lights_off"`, `label: "before lights off"`). Ele é o
   snapshot mais recente, então **Desfazer última cena**
   (`POST /api/history/undo`) religa as lâmpadas como estavam.
3. As lâmpadas habilitadas são desligadas com a transição pedida.

O snapshot é idempotente: se todas as lâmpadas habilitadas já estão apagadas,
nenhum snapshot é gravado. Apertar **Desligar Todas** duas vezes não faz o
**Desfazer** restaurar "tudo apagado". Se gravar o snapshot falhar, o
desligamento continua (fail-open).

Com ao menos uma lâmpada desligada, a última cena aplicada é limpa
(`GET /configurations/last-applied` passa a devolver `null`).

Não exige `API_KEY`. O alias `POST /api/lights/off` tem o mesmo comportamento e
exige a chave quando ela está configurada.

**Request Body (opcional):**
```json
{
  "transition_time_secs": 1.0
}
```

**Parâmetros:**
- `transition_time_secs` (float, optional): Tempo de transição em segundos (0-60, padrão: 1). Sem corpo, usa o padrão. O padrão é 1 s (e não 0 como em `/apply`) para o apagão geral ter um fade curto em vez de um corte seco. Com `0`, o desligamento é instantâneo. A transição vale só para este comando: não fica gravada na lâmpada.

**Response 200 (todas as lâmpadas habilitadas desligadas):**
```json
{
  "message": "Lâmpadas desligadas",
  "applied": ["Lâmpada 1", "Lâmpada 2"],
  "failed": [],
  "details": {
    "config_name": "lights_off",
    "transition_time_secs": 1.0
  }
}
```

O corpo segue o formato de `POST /apply`. `details.config_name` é sempre
`"lights_off"`: não é uma cena do `setups.json`.

**Response 200 (nenhuma lâmpada habilitada):** `applied` e `failed` vazios,
nenhum snapshot gravado.
```json
{
  "message": "Nenhuma lâmpada habilitada para desligar",
  "applied": [],
  "failed": [],
  "details": {
    "config_name": "lights_off",
    "transition_time_secs": 1.0
  }
}
```

**Response 207 (desligamento parcial):**
```json
{
  "message": "Lâmpadas desligadas parcialmente; algumas lâmpadas falharam",
  "applied": ["Lâmpada 1"],
  "failed": [{"name": "Lâmpada 2", "error": "boom"}],
  "details": {
    "config_name": "lights_off",
    "transition_time_secs": 1.0
  }
}
```

**Response 422:** `transition_time_secs` fora de 0-60.

**Response 500 (todas as tentativas falharam):** mesmo formato, com `applied: []`
e a mensagem `"Falha ao desligar as lâmpadas; nenhuma lâmpada desligada"`.

**Response 500 (bridge indisponível):** se o estado da bridge não pode ser lido
antes do desligamento, nenhum comando é enviado e nenhum snapshot é gravado. O
corpo tem o mesmo formato; cada lâmpada habilitada aparece em `failed` com o
erro da bridge.
```json
{
  "message": "Bridge indisponível; nenhuma lâmpada desligada",
  "applied": [],
  "failed": [
    {"name": "Lâmpada 1", "error": "bridge unreachable"},
    {"name": "Lâmpada 2", "error": "bridge unreachable"}
  ],
  "details": {
    "config_name": "lights_off",
    "transition_time_secs": 1.0
  }
}
```

**Exemplo com curl:**
```bash
curl -X POST http://localhost:5081/lights/off \
  -H "Content-Type: application/json" \
  -d '{"transition_time_secs": 1}'
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
- `provider` (string, required): Provedor (`openai` | `anthropic` | `xai` | `groq`). Não há Ollama.
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
| 207 | Multi-Status | Aplicação parcial: algumas lâmpadas falharam (`POST /apply`, `POST /lights/off`) |
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
