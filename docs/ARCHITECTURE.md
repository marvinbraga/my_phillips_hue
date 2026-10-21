# Arquitetura do Sistema - Marvin Hue

Este documento descreve o design e a arquitetura do Marvin Hue Controller, um sistema de controle de iluminação Philips Hue com recursos avançados.

---

## Índice

1. [Visão Geral](#visão-geral)
2. [Componentes Principais](#componentes-principais)
3. [Fluxo de Dados](#fluxo-de-dados)
4. [Decisões de Design](#decisões-de-design)
5. [Dependências Externas](#dependências-externas)
6. [Estrutura de Diretórios](#estrutura-de-diretórios)

---

## Visão Geral

Marvin Hue é uma aplicação Python que controla luzes Philips Hue através de:
- **Configurações pré-definidas**: Ambientes temáticos (concentração, relax, cyberpunk, etc)
- **Espelhamento de tela**: Luzes que refletem cores da tela em tempo real (ambient lighting)
- **Chat com IA**: Controle por linguagem natural (OpenAI, Anthropic, xAI, Groq)
- **API REST + WebSocket**: Interface programática e web para controle

### Arquitetura de Alto Nível

```
┌─────────────────┐
│   Web Browser   │
│   (Frontend)    │
└────────┬────────┘
         │ HTTP/WebSocket
         ▼
┌─────────────────────────────────────────┐
│          FastAPI Application            │
│  (app.py - Async Web Server)            │
│                                         │
│  ┌──────────────────────────────────┐  │
│  │  Routers & Endpoints             │  │
│  │  - Configurations                │  │
│  │  - Positions                     │  │
│  │  - Mirror Control                │  │
│  │  - Chat                          │  │
│  │  - WebSockets                    │  │
│  └──────────────┬───────────────────┘  │
└─────────────────┼───────────────────────┘
                  │
      ┌───────────┼───────────┐
      ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│   Hue    │ │  Screen  │ │   Chat   │
│Controller│ │  Mirror  │ │  Agent   │
└────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │             │
     ▼            ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│Philips   │ │  Screen  │ │ OpenAI/  │
│Hue Bridge│ │  Capture │ │Anthropic │
│(Hardware)│ │  (mss)   │ │xAI /Groq │
└──────────┘ └──────────┘ └──────────┘

┌─────────────────────────────────────────┐
│      Core Modules (marvin_hue/)         │
│                                         │
│  ┌────────┐  ┌────────┐  ┌──────────┐  │
│  │ Colors │  │ Utils  │  │  Basics  │  │
│  └────────┘  └────────┘  └──────────┘  │
│                                         │
│  ┌────────────┐  ┌─────────────────┐   │
│  │   Setup    │  │    Logging      │   │
│  │  Builder   │  │    Config       │   │
│  └────────────┘  └─────────────────┘   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│      Data Storage                       │
│                                         │
│  - setups.json (Configurations)         │
│  - light_positions.json (Mirror config) │
│  - marvin_hue.sqlite (Lights registry)  │
│  - chat_memory.sqlite (chat only; opt.) │
│  - .env (Environment variables)         │
└─────────────────────────────────────────┘
```

---

## Componentes Principais

### 1. Core Package (`marvin_hue/`)

#### 1.1 `colors.py` - Representação de Cores

**Responsabilidade**: Classe `Color` para representar cores RGBA.

```python
class Color:
    """
    Representa uma cor RGBA para Philips Hue.

    Attributes:
        red (int): 0-255
        green (int): 0-255
        blue (int): 0-255
        brightness (int): 0-254 (limite da API Hue)
    """
```

**Funcionalidades**:
- Validação de valores RGB (0-255) e brightness (0-254)
- Serialização para dicionário
- Geração de cores aleatórias

**Decisões de Design**:
- Brightness separado de RGB (API Hue funciona assim)
- Validação estrita no `__init__` para evitar erros downstream
- Range de brightness 0-254 (não 255) conforme limitação da API Hue

---

#### 1.2 `utils.py` - Conversão de Cores

**Responsabilidade**: Conversões entre espaços de cor RGB ↔ XY.

```python
class ColorConverter:
    """
    Conversões bidirecionais RGB ↔ XY para Philips Hue.
    """

    @staticmethod
    def rgb_to_xy(red, green, blue) -> tuple[float, float]:
        """RGB → XY (sRGB → CIE XYZ → xy chromaticity)"""

    @staticmethod
    def xy_to_rgb(xy, brightness) -> tuple[int, int, int]:
        """XY → RGB (inverso)"""
```

**Pipeline de Conversão RGB → XY**:

```
RGB (0-255)
    ↓ Normalização
RGB (0.0-1.0)
    ↓ Correção Gamma Reversa (sRGB → Linear RGB)
Linear RGB
    ↓ Matriz de Transformação (Wide RGB D65)
CIE XYZ
    ↓ Cálculo de Cromaticidade
XY Coordinates (x, y)
```

**Decisões de Design**:
- Usa espaço de cor Wide RGB D65 (melhor para Philips Hue)
- Proteção contra divisão por zero
- Validação de gamut (coordenadas XY válidas)
- Caching futuro com `@lru_cache` (planejado na Fase 4)

---

#### 1.3 `basics.py` - Estruturas de Dados

**Responsabilidade**: Estruturas de dados fundamentais.

```python
class LightSetting:
    """Associa uma luz a uma cor."""
    def __init__(self, light_name: str, color: Color)

class LightConfig:
    """Agrupa múltiplos LightSettings em uma configuração nomeada."""
    def __init__(self, name: str, settings: list[LightSetting], description: str = "")

class LightSetupsManager:
    """Gerencia carga/salvamento de configurações de JSON."""
    def load() -> self
    def save() -> self
    def get_config(name: str) -> LightConfig | None
```

**Fluxo de Dados**:

```
setups.json (Disco)
    ↓ load()
LightSetupsManager._data (Dict)
    ↓ update()
LightSetupsManager._configs (List[LightConfig])
    ↓ get_config(name)
LightConfig (settings: List[LightSetting])
```

**Decisões de Design**:
- Separação de dados (dict) e objetos (LightConfig)
- Load/update em dois passos para permitir recargas
- Logging de erros ao invés de exceções silenciosas

---

#### 1.4 `controllers.py` - Interação com Hue Bridge

**Responsabilidade**: Comunicação com Philips Hue Bridge.

```python
class HueController:
    """
    Controlador para Philips Hue Bridge.

    Attributes:
        bridge: Instância phue.Bridge
        lights: Lista de objetos Light
        _light_cache: Dict[str, Light] para lookup O(1)
    """

    def set_light_color(light_name: str, color: Color) -> Light
    def apply_light_config(config: LightConfig, transition_time: float = 0)
    def get_lights_status() -> list[dict]
    def refresh_lights()
```

**Cache de Lâmpadas**:

```
bridge.get_light_objects()  # O(n) - API call
    ↓
self.lights: List[Light]
    ↓ _refresh_cache()
self._light_cache: Dict[str, Light]
    ↓
_get_light_by_name(name)  # O(1) - hash lookup
```

**Validações**:
1. IP address válido
2. Lâmpada existe antes de aplicar cor
3. Coordenadas XY dentro do gamut
4. Brightness dentro do range 0-254

**Decisões de Design**:
- Cache de luzes para performance (O(1) vs O(n))
- Validação em múltiplas camadas (fail-fast)
- Logging extensivo para debugging
- Timeout configurável para operações de rede (planejado)

---

#### 1.5 `setup_builder.py` - Construtor de Configurações

**Responsabilidade**: Elimina duplicação na definição de setups.

**Antes (setups.py - 808 linhas)**:
```python
class SetupConcentration(LightConfig):
    def __init__(self):
        settings = [
            LightSetting('Lâmpada 1', Color(255, 244, 229, 255)),
            # ... repetir para 9 luzes
        ]
        super().__init__('concentration', settings, '...')

# Repetido 50+ vezes!
```

**Depois (setup_builder.py + setups.json - ~100 linhas)**:
```python
class LightConfigBuilder:
    @staticmethod
    def from_dict(config: Dict) -> LightConfig:
        """Cria LightConfig a partir de dicionário JSON."""

    @staticmethod
    def create_uniform(name, color, description, lights=None):
        """Config com mesma cor para todas as luzes."""
```

**Benefícios**:
- Redução de 87% no código (808 → 100 linhas)
- Configurações editáveis sem código Python
- Validação centralizada
- Fácil adicionar novos setups

---

#### 1.6 `screen_mirror.py` - Espelhamento de Tela

**Responsabilidade**: Captura de tela e aplicação de cores às luzes.

```python
class ScreenMirror:
    """
    Espelhamento de tela em tempo real.

    Attributes:
        hue: HueController
        running: bool
        fps: int (1-60)
        brightness: int (0-254)
        saturation_boost: float (multiplicador)
        smoothing_factor: float (0-1, suavização temporal)
    """

    def start(fps: int = 25, brightness: int = 200)
    def stop()
    def get_status() -> dict
```

**Mapeamento de Posições**:

```
┌─────────────────────────────┐
│ top-left   top   top-right  │
│                             │
│  left    center    right    │
│                             │
│bottom-left bottom bottom-rt │
└─────────────────────────────┘

ambient = tela inteira
none = não participa
```

**Pipeline de Captura**:

```
Screen (1920x1080)
    ↓ mss.grab()
Screenshot (PIL Image)
    ↓ crop(region)
Region (ex: left = 15% esquerda)
    ↓ resize(small) + quantize
Dominant Color (RGB)
    ↓ Color Smoothing (temporal)
Smoothed Color
    ↓ apply_to_light()
Hue Bridge → Light
```

**Otimizações**:
- **Sampling**: Resize para ~100x100 antes de processar
- **Change Detection**: Só atualiza se cor mudou significativamente
- **Throttling**: FPS limitado (padrão 25)
- **Smoothing**: Interpolação temporal para transições suaves
- **Threading**: Captura em thread separada

**Decisões de Design**:
- FPS padrão 25 (balanço entre responsividade e carga na bridge)
- Saturation boost para cores mais vibrantes
- Smoothing para evitar flicker
- Position config em JSON (fácil customizar)

---

#### 1.7 `logging_config.py` - Sistema de Logging

**Responsabilidade**: Configuração centralizada de logging.

```python
def get_logger(name: str) -> logging.Logger:
    """
    Retorna logger configurado por módulo.

    - Rotating file handler (10MB, 5 backups)
    - Console handler para stderr
    - Formato: [timestamp] [level] [module] message
    """
```

**Níveis de Log**:
- **DEBUG**: Detalhes internos (ex: coordenadas XY calculadas)
- **INFO**: Operações normais (ex: configuração aplicada)
- **WARNING**: Problemas não críticos (ex: luz não encontrada)
- **ERROR**: Erros tratáveis (ex: falha ao salvar JSON)

**Decisões de Design**:
- Logger por módulo (fácil filtrar)
- Rotating files para evitar logs gigantes
- Sem print statements (todos substituídos por logging)
- Tracebacks completos em erros

---

### 2. API Layer (`app.py`)

**Responsabilidade**: Interface web REST + WebSocket.

```python
app = FastAPI(
    title="Marvin Hue Controller",
    version="2.0.0",
    lifespan=lifespan  # Startup/shutdown
)
```

**Grupos de endpoints**:

1. **Páginas**: `/`, `/lights`, `/groups`, `/schedules`, `/positions-config`, `/mirror`, `/health`, `/chat`
2. **Status**: `/api/bridge/status`, `/api/lights/status`, `/api/health` (`schedules.runner_alive`)
3. **Lights registry**: `/api/lights` CRUD + `POST /api/lights/sync`
4. **Groups / schedules / history / backup**: `/api/groups`, `/api/schedules`, `/api/history`, `/api/backup`
5. **Configurations**: `/configurations`, `/apply` (`ApplyResult` → 200 / 207 / 500; `duration_minutes` ignorado)
6. **Positions**: `/positions`, `/positions/reset`
7. **Mirror**: `/mirror/*` via `MirrorControlService`
8. **Chat**: `/api/chat/*`
9. **WebSockets**: `/ws/mirror`, `/ws/chat`

**Validação com Pydantic**:

```python
class ApplyConfigRequest(BaseModel):
    config_name: str = Field(..., min_length=1, max_length=100)
    transition_time_secs: float = Field(default=0, ge=0, le=60)

    @field_validator('config_name')
    def sanitize_config_name(cls, v: str) -> str:
        """Remove caracteres potencialmente perigosos."""
        return re.sub(r'[^\w\s\-]', '', v).strip()
```

**Lifecycle Management**:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global hue, manager, screen_mirror, chat_agent
    hue = HueController(os.getenv("BRIDGE_IP"))
    manager = LightSetupsManager("setups.json")
    screen_mirror = ScreenMirror(hue, "light_positions.json")
    chat_agent = create_hue_agent(...)

    yield

    # Shutdown
    if screen_mirror.is_running():
        screen_mirror.stop()
```

**Decisões de Design**:
- FastAPI para async, validação automática, OpenAPI docs
- Pydantic models para segurança de tipos
- CORS configurável (produção deve restringir)
- Async file I/O com aiofiles
- Executor threads para código síncrono (phue)

---

### 3. Chat Agent

**Responsabilidade**: Controle por linguagem natural usando LLMs.

**Arquitetura**:

```
User Message
    ↓
LangChain Agent (ReAct)
    ↓ Tools
┌─────────────────────────────┐
│ - list_configurations()     │
│ - apply_configuration()     │
│ - get_lights_status()       │
│ - control_mirror()          │
└─────────────────────────────┘
    ↓ Tool Call
HueController / ScreenMirror
    ↓
Philips Hue Bridge
```

**Providers suportados**:
- **OpenAI**: gpt-4o, gpt-4o-mini
- **Anthropic**: Claude
- **xAI**: Grok
- **Groq**: modelos via API compatível com OpenAI

Não há provider **Ollama**.

**Decisões de Design**:
- Tools específicas para domínio Hue
- Fallback se API key não disponível

> **Atualizado:** o chat foi migrado de `create_react_agent` (prebuilt) para um
> harness de primeira classe sobre `langchain.agents.create_agent` + LangGraph.
> Veja a seção **"Harness de Chat (middleware + subagents + tools)"** abaixo para
> o design vigente (memória por sessão via checkpointer, middleware de contexto/
> segurança, e delegação a subagents).

---

## Harness de Chat (middleware + subagents + tools)

O assistente "Marvin" (`marvin_hue/chat/`) roda sobre
`langchain.agents.create_agent` + LangGraph — não o prebuilt `create_react_agent`.

### Fluxo

```
Cliente (WebSocket /ws/chat | REST /api/chat/*)
        │  message + session_id
        ▼
HueLightAgent.ainvoke(message, session_id)
        │  config = {"configurable": {"thread_id": session_id}}
        ▼
create_agent(model, tools=[*build_all_tools(...), task], middleware=[...], checkpointer)
        │
        ├─ middleware (ordem):
        │   1. HueContextMiddleware    → injeta status vivo + localizações +
        │                                presets no system message a cada chamada
        │                                de modelo (cache TTL p/ não marretar a bridge).
        │   2. EyeSafetyMiddleware     → clampa brilho nas tools diretas (feedback).
        │   3. TodoListMiddleware      → planejamento de tarefas.
        │   4. SummarizationMiddleware → resume contexto ao exceder ~3000 tokens.
        │   5. AnthropicPromptCaching  → só quando provider == "anthropic".
        │   (+ HumanInTheLoopMiddleware se require_approval / env
        │    CHAT_REQUIRE_APPROVAL — off por padrão;
        │    interrupt_on = chat/hitl.HITL_INTERRUPT_ON: create_config,
        │    save_current_config, create_schedule, set_schedule_enabled,
        │    start_mirror; os subagents recebem o mesmo filtro p/ suas tools.
        │    Fluxo interrupt/resume: ver "Aprovação humana (HITL)" abaixo)
        │   recursion_limit do orquestrador = 25 por turno (AGENT_RECURSION_LIMIT)
        │
        ├─ ChatServices (chat/services.py): providers preguiçosos resolvidos a
        │   cada chamada de tool (padrão: api.dependencies, import tardio).
        │   favorites, history, groups, schedules, mirror, health,
        │   last_applied; lights_off(controller) compõe LightsOffService como
        │   POST /lights/off (lights_off_provider é só gancho de teste).
        │   Serviço indisponível → a tool devolve mensagem (fail-open, logado).
        │   Erro inesperado → mensagem genérica ao modelo; detalhe só no log.
        │
        ├─ build_all_tools (chat/tools/__init__.py) junta, sem duplicatas:
        │   ├─ light_tools.py (closures sobre controller/manager):
        │   │   list_lights, get_light_status, set_light_color, apply_config,
        │   │   list_configs, turn_off_lights, turn_on_lights, set_brightness,
        │   │   save_current_config, get_light_locations, get_rooms,
        │   │   list_lights_by_room, set_room_power, set_room_brightness
        │   │   (apply_config async → ApplyConfigService source "chat":
        │   │    snapshot "before apply" + registro da última cena (#14);
        │   │    turn_off_lights("all") async → LightsOffService (para mirror,
        │   │    snapshot, limpa última cena); sync → controller direto)
        │   ├─ rooms.py: índice sala → lâmpadas (registry ou JSON), normalizado
        │   │   uma vez; "teto" casa "Teto, à direita" e "Teto, à esquerda"
        │   │   (prefixo de palavra, sem acento) e as tools agem na união
        │   ├─ scene_tools.py: search_configs, describe_config (build_scene_preview),
        │   │   create_config (grava pela especificação, sem aplicar; brilho
        │   │   limitado por effective_hue_brightness), undo_last_scene
        │   │   (SceneHistoryService.restore_last + clear_after_undo da última
        │   │   cena), list/add/remove_favorite. Cenas novas passam por
        │   │   LightSetupsManager.add_config (lock + escrita atômica)
        │   ├─ automation_tools.py: list_groups, apply_config_to_group
        │   │   (sem interseção cena∩grupo nada é feito; senão snapshot
        │   │   "group_apply" antes, fail-open), list_schedules,
        │   │   create_schedule (apply_config | power_on | power_off; nasce
        │   │   desativado salvo pedido explícito),
        │   │   set_schedule_enabled — grupo/agendamento pelo nome ou id
        │   └─ system_tools.py: get_mirror_status, start_mirror, stop_mirror
        │       (MirrorControlService), get_system_health (collect_health),
        │       set_color_temperature (Kelvin→RGB Tanner Helland, 2000–6500 K,
        │       via HueController.set_light_color)
        │   Tools de serviço async têm coroutine=; o invoke síncrono (CLI) não
        │   roda serviços aiosqlite fora do loop do app: devolve
        │   "disponível apenas no app".
        │
        └─ task tool → delega a subagents isolados:
            scene-designer | config-librarian | general-purpose
            (allow-lists em subagents/definitions.py: scene-designer ganha
             set_color_temperature/describe_config/create_config;
             config-librarian ganha search/describe/create_config + favoritos;
             general-purpose ganha get_system_health/get_mirror_status/
             list_groups/list_schedules — só consulta)
            (cada um é um create_agent aninhado, com subconjunto restrito de
             tools + os mesmos middleware de segurança; SEM a tool task → sem
             recursão de delegação; recursion_limit explícito; texto final
             extraído por chat/messages.message_text, que ignora blocos
             "thinking")
        ▼
HueController (chokepoint) → bridge Philips Hue
```

### Memória por sessão

Histórico mantido por um checkpointer LangGraph keyed por
`thread_id = session_id` — não há mais `_conversation_history` de instância
(corrige o estado compartilhado entre sessões). O `session_id` é gerado no
cliente (`crypto.randomUUID` + `localStorage`) e enviado em TODOS os frames do
WebSocket e nas rotas REST. Eviction LRU (`MAX_SESSIONS=100`) evita vazamento
monotônico de memória no `InMemorySaver`.

Persistência do **chat** é opcional e config-driven (`CHAT_CHECKPOINT=memory|sqlite`). O
ciclo de vida de um checkpointer persistente é do COMPOSITOR (o `lifespan` em
`app.py`, via `AsyncExitStack` + `AsyncSqliteSaver`), nunca do agente — o agente
só RECEBE um checkpointer injetado (ou usa `InMemorySaver` volátil por padrão).

O **catálogo de lâmpadas** (registry) usa outro arquivo SQLite
(`APP_DB_PATH`, padrão `.res/marvin_hue.sqlite`), isolado de
`chat_memory.sqlite`. A bridge continua fonte de verdade do inventário físico e
do estado ao vivo; o registry guarda metadados app-side (nickname, room, notes,
soft-delete) e se sincroniza via `POST /api/lights/sync` sem reativar soft-deleted
por padrão.

### Invariante de segurança ocular

| Lâmpada    | Limite | Onde é GARANTIDO |
|------------|--------|------------------|
| Fita Led   | ≤25% (≤63/254) | `HueController.set_light_color` / `set_brightness` / `set_all_brightness` (chokepoint) |
| Led cima   | ≤25% (≤63/254) | idem |
| Demais     | sem limite | — |

A garantia AUTORITATIVA é o chokepoint do `HueController`, cobrindo presets
(`apply_light_config → set_light_color`), screen-mirror, tools diretas e o
caminho `"all"` (`set_all_brightness` clampa POR LÂMPADA). O
`EyeSafetyMiddleware` é defesa em profundidade. Ambos reusam `clamp_eye_safety`
de `marvin_hue/eye_safety.py` (raiz do pacote — domínio físico, fora de `chat/`),
que arredonda PARA BAIXO (floor: 25% de 254 = 63, nunca 64). O teste de eval
reconcilia `EYE_SAFETY_LIMITS` (código, canônico) com
`.res/light_physical_locations.json` (informativo ao modelo).

### Eval-gate

`tests/eval/invariants.json` é o golden set versionado (`hue.chat@2`, com dono).
Casos `level="code"` (clamp ocular, desligar tudo, superfície de tools,
privilégio mínimo dos subagents, Kelvin, desfazer sem histórico, payload de
agendamento) rodam no CI. Os 17 casos `level="prompt"` medem seleção de tool
ao vivo (`tests/eval/run_tool_selection.py`, N=3, bridge e serviços mockados,
baseline = `origin/master`); relatório em `docs/evals/`. O CI confere o hash da
superfície de prompt contra `tests/eval/prompt_version.json`: qualquer mudança
de prompt, descrição ou schema de tool exige bump de `PROMPT_VERSION` e nova
rodada do eval ao vivo. **Gate:** Δ ≥ 0 nos intents pré-existentes e ≥ 90% nas
tools novas.

### Canal de chat = privilégio total

O chat comanda luzes, cenas, agendamentos e espelhamento. Fica aberto na LAN
(sem `API_KEY` no `/ws/chat`), mas o WebSocket recusa conexões de navegador
cross-origin (`Origin` ≠ `Host` → close 1008) para evitar Cross-Site WebSocket
Hijacking. Clientes sem `Origin` (scripts/CLI) continuam aceitos.

### Follow-ups conhecidos (não-bloqueantes)

- **Prompt caching vs contexto vivo (Anthropic):** o `HueContextMiddleware`
  injeta status volátil no system message a cada turno, reduzindo o ganho do
  `AnthropicPromptCachingMiddleware`. É otimização de custo (Anthropic), não
  correção de comportamento; mitigar injetando o contexto vivo como mensagem
  separada, fora do prefixo cacheado.

### Aprovação humana (HITL)

Com `CHAT_REQUIRE_APPROVAL=true` (lido em `app.py` e em
`POST /api/chat/configure`), o `HumanInTheLoopMiddleware` interrompe o grafo
antes das tools de `HITL_INTERRUPT_ON`. Conferido na prática com langchain
1.3.8 / langgraph 1.2.4 (`tests/chat/test_hitl_flow.py`):

```
POST /api/chat/message | WS action "message"
  → HueLightAgent.ainvoke: result["__interrupt__"] = [Interrupt(value=
      {"action_requests": [...], "review_configs": [...]}, id)]
  → ApprovalRequired (chat/hitl.py): requests [{id "<interrupt>:<i>", tool,
      args, description, allowed_decisions ⊆ {approve, reject}}]
  → 200 {approval_required, session_id} | WS {"type": "approval_required"}
POST /api/chat/resume | WS action "resume"
  → HueLightAgent.aresume: relê state.interrupts, valida as decisões
      (id obrigatório e exato, tipo) ANTES de retomar
  → Command(resume={interrupt_id: {"decisions": [...]}}) no mesmo thread_id
  → texto final ou outro ApprovalRequired
```

- **Subagents:** a interrupção dentro de um subagent (tool `task`) sobe até
  o orquestrador. O subagent não tem checkpointer próprio e herda o do pai
  pelo config; na retomada ele continua do próprio nó HITL, sem chamar o
  modelo de novo, e tools irmãs já concluídas não reexecutam. Por isso o
  HITL fica nos subagents (o `task` em si não pede aprovação). Não dê
  checkpointer próprio ao subagent nem um config desligado do pai em
  `subagents/task.py`.
- **Política:** só pede aprovação o que grava algo que fica ou toma o
  controle (`create_config`, `save_current_config`, `create_schedule`,
  `set_schedule_enabled`, `start_mirror`). Mutações reversíveis ficam fora
  de propósito para evitar fadiga de aprovação; a lista completa e o motivo
  estão no docstring de `chat/hitl.py`.
- **Várias interrupções** (ex.: duas `task` em paralelo) exigem resume por
  id; a forma por id é usada sempre. A ordem de `__interrupt__` e de
  `state.interrupts` pode divergir (visto na prática), por isso cada
  decisão TEM de levar o `id` do pedido; id ausente, repetido, desconhecido
  ou de um conjunto antigo é recusado.
- **Pendência:** mensagem nova com aprovação pendente não roda turno (uma
  tool call sem `ToolMessage` quebraria a thread nos provedores reais) e
  devolve o pedido pendente.
- **Concorrência:** um `asyncio.Lock` por sessão, de módulo
  (`WeakValueDictionary`, compartilhado com o agente novo de
  `/api/chat/configure`), serializa turno, resume e clear: dois resumes
  simultâneos executam a ação uma vez só; o outro recebe 409.
- **Flag desligada com pendência antiga:** o grafo sem o middleware não
  enxerga a interrupção; o turno seguinte fecha as tool calls órfãs com uma
  `ToolMessage` "Aprovação desativada; ação cancelada." (sem executar) via
  `aupdate_state` e segue.
- **Decisões:** só `approve` e `reject` (motivo opcional, até 500
  caracteres). `edit` fica fora: o middleware montaria o novo tool call com o
  nome vindo do cliente.
- **Revalidação:** a tool aprovada roda pelo ToolNode normal (schema
  Pydantic + `EyeSafetyMiddleware`); aprovar não contorna nada.
- **Persistência:** o pedido pendente vive no checkpointer (`thread_id =
  session_id`). Com `CHAT_CHECKPOINT=sqlite` ele sobrevive a restart e a
  `configure`; com `memory`, some no restart.
- **UI:** a tela Chat mostra um cartão por pedido (rótulo pt-BR, descrição,
  args em lista chave/valor via `textContent`, uma linha por lâmpada,
  Aprovar/Rejeitar), bloqueia o input até decidir e envia
  `action: "pending"` ao conectar; a resposta (lista vazia = nada pendente)
  reapresenta ou limpa o cartão após recarregar ou reconectar.
- **Markdown das respostas (#25):** o DOMPurify proíbe `img`/mídia/`svg` e
  `src`/`srcset`/`style`; links abrem em nova aba com
  `rel="noopener noreferrer"`. As páginas HTML mandam
  `Content-Security-Policy: img-src 'self' data:`
  (`marvin_hue/api/middleware/csp.py`) como segunda barreira contra
  exfiltração por URL de imagem.

---

## Fluxo de Dados

### Fluxo 1: Aplicar Configuração

```
1. User → POST /apply {"config_name": "concentration"}
2. FastAPI → ApplyConfigRequest (validação Pydantic)
3. Manager → get_config("concentration")
4. Manager → LightConfig (com settings)
5. HueController → apply_light_config(config)
6. Para cada LightSetting:
   a. Color → RGBtoXYAdapter.convert(r, g, b)
   b. XY → Validação de gamut
   c. Bridge → set_light(xy, brightness)
7. Response → ApplyResult (`applied` / `failed`) com HTTP 200 / 207 / 500
   (`duration_minutes` no request é ignorado)
```

### Fluxo 2: Espelhamento de Tela

```
1. User → POST /mirror/start {"fps": 25}
2. ScreenMirror → start(fps=25)
3. Thread Loop (25 FPS):
   a. mss.grab() → Screenshot
   b. Para cada luz ativa:
      i. Crop região (ex: left = 15% esquerda)
      ii. Resize + quantize → Dominant color
      iii. Smoothing temporal
      iv. HueController.set_light_color()
   c. Sleep(1/fps)
4. WebSocket `/ws/mirror` → status unificado (~12 FPS tela, ~25 FPS áudio)
   Luzes: FPS configurado (padrão 25 no start; perfis cinema/fps/ambient)
```

### Fluxo 3: Chat com IA

```
1. User → POST /api/chat/message {"message": "Ative concentração"}
2. ChatAgent → ainvoke(message)
3. LLM → Analisa intenção
4. LLM → Decide tool: "apply_configuration"
5. Tool → apply_configuration("concentration")
6. HueController → apply_light_config()
7. Tool Result → LLM
8. LLM → Gera resposta natural
9. Response → {"response": "Configuração aplicada!", "success": true}
```

---

## Decisões de Design

### 1. JSON ao invés de Classes Python (Setups)

**Problema**: 808 linhas de código duplicado em `setups.py`.

**Solução**: Mover configurações para `setups.json` + builder pattern.

**Benefícios**:
- Redução de 87% no código
- Não precisa recompilar para adicionar configuração
- Usuários não-técnicos podem editar JSON
- Validação centralizada

**Trade-off**: Performance mínima (parsing JSON), mas insignificante.

---

### 2. Cache de Lâmpadas (O(1) Lookup)

**Problema**: Busca linear `for light in lights if light.name == name` é O(n).

**Solução**: Dict `_light_cache` para lookup O(1).

**Benefícios**:
- Performance: 9 luzes (incluindo `Lâmpada 3`) → lookup O(1) mesmo assim escala melhor
- Preparado para setups maiores (50+ luzes)

**Trade-off**: Memória adicional (mínima), precisa refresh manual se topologia mudar.

---

### 3. Async FastAPI + Thread Executor

**Problema**: phue é síncrono, FastAPI é async.

**Solução**:
```python
loop = asyncio.get_event_loop()
await loop.run_in_executor(None, sync_function)
```

**Benefícios**:
- Não bloqueia event loop
- Múltiplas requisições processadas concorrentemente
- Melhor performance sob carga

**Trade-off**: Complexidade adicional.

---

### 4. Smoothing Temporal (Screen Mirror)

**Problema**: Cores da tela mudam rapidamente → flicker nas luzes.

**Solução**: Interpolação temporal:
```python
smoothed = previous * (1 - factor) + current * factor
```

**Benefícios**:
- Transições suaves
- Menos stress na bridge Hue
- Melhor experiência visual

**Trade-off**: Latência adicional (~100-200ms).

---

### 5. Validação em Múltiplas Camadas

**Camadas de Validação**:

1. **Pydantic (API)**: Valida request bodies
2. **Color.__init__**: Valida RGB/brightness
3. **ColorConverter**: Valida antes de conversão
4. **HueController**: Valida luz existe, XY no gamut

**Benefícios**:
- Fail-fast: erros detectados cedo
- Mensagens de erro claras
- Sistema robusto

**Trade-off**: Overhead mínimo de validação.

---

### 6. Logging ao invés de Prints

**Problema**: `print()` não estruturado, sem níveis, não rotaciona.

**Solução**: Logging com `logging` module.

**Benefícios**:
- Níveis (DEBUG, INFO, WARNING, ERROR)
- Filtros por módulo
- Rotação automática (evita logs gigantes)
- Fácil debugging em produção

---

## Dependências Externas

### Core Dependencies

#### 1. `phue` - Philips Hue Bridge API

**Uso**: Comunicação com bridge Hue.

```python
from phue import Bridge, Light

bridge = Bridge(ip_address)
bridge.connect()
lights = bridge.get_light_objects()
```

**Limitações**:
- Síncrono (não async)
- Taxa de atualização ~10-25 req/s
- Primeira conexão requer botão da bridge

**Alternativas Consideradas**:
- `aiohue` (async) - menos maduro
- API REST direta - mais trabalho

**Decisão**: phue é estável e bem testado.

---

#### 2. `FastAPI` - Web Framework

**Uso**: API REST + WebSocket.

**Benefícios**:
- Async nativo
- Validação automática (Pydantic)
- OpenAPI docs automáticas
- WebSocket support

**Alternativas Consideradas**:
- Flask - síncrono, sem validação automática
- Django - muito pesado para este projeto

---

#### 3. `mss` - Screen Capture

**Uso**: Captura de tela para espelhamento.

**Benefícios**:
- Rápido (usa APIs nativas do OS)
- Cross-platform (Linux, Windows, macOS)
- Baixo overhead

**Alternativas Consideradas**:
- `pyautogui` - mais lento
- `PIL.ImageGrab` - Windows only

---

#### 4. `LangChain` - Chat Agent

**Uso**: Orquestração de LLMs e tools.

**Benefícios**:
- Abstração sobre múltiplos providers
- ReAct agent para raciocínio
- Tool calling padronizado

**Alternativas Consideradas**:
- Chamar APIs diretamente - mais trabalho
- LlamaIndex - mais voltado para RAG

---

### Development Dependencies

- `pytest` + `pytest-asyncio`: Testes
- `pytest-cov`: Cobertura de testes
- `mypy`: presente no extra `dev`; **não** roda no CI (stubs numpy). Ruff + pytest no CI.

---

## Estrutura de Diretórios

```
my_phillips_hue/
├── marvin_hue/                 # Pacote da aplicação
│   ├── colors.py               # Color (RGBA, brightness 0–254)
│   ├── utils.py                # RGB ↔ XY
│   ├── basics.py               # LightSetting, LightConfig, LightSetupsManager
│   ├── apply_result.py         # ApplyResult por lâmpada (200 / 207 / 500)
│   ├── controllers.py          # HueController (phue REST)
│   ├── setup_builder.py        # LightConfig a partir de JSON
│   ├── screen_mirror.py        # Captura de tela
│   ├── audio_mirror.py         # Espelhamento de áudio
│   ├── config.py / eye_safety.py / logging_config.py
│   ├── domain/                 # lights, groups, schedules, scene_history
│   ├── persistence/            # repositórios SQLite + schema
│   ├── services/               # registry, groups, schedules, schedule_runner,
│   │                           # health, mirror_control, backup, scene_history
│   ├── output/                 # LightOutputPort (REST / Entertainment / fallback)
│   ├── entertainment/          # cliente DTLS e credenciais
│   ├── chat/                   # agente LangGraph, providers, tools, middleware
│   └── api/                    # rotas, models, websockets, API-key middleware
│
├── web/
│   ├── templates/              # Controle, Lâmpadas, Grupos, Agendamentos,
│   │                           # Posicionamento, Espelhamento, Saúde, Chat
│   └── static/                 # index.js, lights.js, groups.js, schedules.js,
│                               # positions.js, mirror.js, health.js
│
├── .res/
│   ├── setups.json             # ~69 temas (fonte canônica)
│   ├── light_positions.json
│   ├── marvin_hue.sqlite       # catálogo (APP_DB_PATH)
│   └── chat_memory.sqlite      # checkpointer do chat (opcional)
│
├── tests/                      # pytest (conftest, test_*.py, chat/, eval/)
├── docs/                       # API.md, ARCHITECTURE.md, CONFIGURATION.md
├── .github/workflows/ci.yml    # pytest + ruff
├── app.py                      # FastAPI (version string 2.0.0, porta 5081)
├── main.py                     # CLI — JSON via LightSetupsManager
└── pyproject.toml              # pacote 0.1.0, Python ≥3.11, uv
```

---

## Padrões de Código

### 1. Type Hints

Todos os módulos principais usam type hints:

```python
def set_light_color(self, light_name: str, color: Color) -> Light:
    """..."""
```

### 2. Docstrings (Google Style)

```python
def rgb_to_xy(red: int, green: int, blue: int) -> tuple[float, float]:
    """
    Converte RGB para XY.

    Args:
        red: Valor vermelho (0-255)
        green: Valor verde (0-255)
        blue: Valor azul (0-255)

    Returns:
        tuple[float, float]: Coordenadas (x, y) no espaço de cor Hue

    Raises:
        ValueError: Se valores RGB estiverem fora do intervalo 0-255

    Example:
        >>> xy = rgb_to_xy(255, 100, 50)
        >>> print(xy)
        (0.6, 0.3)
    """
```

### 3. Logging ao invés de Prints

```python
# ❌ Não fazer
print(f"Aplicando configuração {name}")

# ✅ Fazer
logger.info(f"Applying configuration '{name}' with {len(settings)} lights")
```

### 4. Validação Explícita

```python
# ❌ Não fazer
def apply_config(config):
    for setting in config.settings:
        # ...

# ✅ Fazer
def apply_config(config: LightConfig) -> "HueController":
    if not config or not hasattr(config, 'settings'):
        raise ValueError("LightConfig inválido")
    # ...
```

---

## Evolução do Sistema

### Versão 1.0 (Original)
- Configurações hardcoded em classes Python
- Controle básico via CLI
- Sem interface web

### Versão 2.0 (Atual)
- ✅ Configurações em JSON (data-driven, ~69 temas em `.res/setups.json`)
- ✅ API REST + WebSocket
- ✅ Interface web (Controle, Lâmpadas, Grupos, Agendamentos, Posicionamento, Espelhamento, Saúde, Chat)
- ✅ Espelhamento de tela e áudio (`MirrorControlService`)
- ✅ `ScheduleRunner` (health: `schedules.runner_alive`)
- ✅ `POST /apply` com `ApplyResult` (HTTP 200 / 207 / 500)
- ✅ Chat com IA (openai / anthropic / xai / groq)
- ✅ Logging estruturado
- ✅ Testes automatizados (`uv run pytest`; cobertura em `htmlcov/`)
- ✅ Validação de inputs
- ✅ Type hints completos

### Versão 3.0 (Planejado)
- Autenticação e autorização
- Rate limiting
- Métricas e monitoring
- Suporte para múltiplas bridges
- Integração com home automation (Home Assistant, etc)

---

## Performance

### Métricas Atuais

| Operação | Tempo | Otimização |
|----------|-------|------------|
| Aplicar configuração | ~200-500ms | Async executor |
| Lookup de luz | O(1) | Dict cache |
| Screen capture | ~10-40ms/frame | mss + resize |
| API response | <100ms | FastAPI async |
| Load JSON configs | <50ms | Async I/O |

### Gargalos

1. **Bridge Hue**: Taxa limitada a ~10-25 req/s
2. **Screen Capture**: CPU-bound (mitigado com sampling)
3. **LLM API**: Latência 1-3s (inevitável)

### Otimizações Futuras (Fase 4)

- `@lru_cache` em conversões RGB→XY
- Multiprocessing para screen capture
- Batching de updates para bridge
- Cache de configs JSON com TTL

---

## Segurança

### Implementado

- ✅ Validação de inputs (Pydantic)
- ✅ Sanitização de strings (regex)
- ✅ Range checks (RGB, brightness, FPS, etc)
- ✅ Gamut validation (coordenadas XY)
- ✅ .env no .gitignore
- ✅ `API_KEY` opcional somente em `/api/*`

### Faltando (Produção)

- ⚠️ Autenticação completa (OAuth / sessões) — `API_KEY` não cobre HTML, `/apply` nem WebSockets
- ⚠️ CORS restrito (atualmente aceita todas origens)
- ⚠️ Rate limiting
- ⚠️ HTTPS/WSS
- ⚠️ Input size limits
- ⚠️ CSRF protection

---

## Troubleshooting

### Problema: Alta latência em espelhamento

**Causa**: FPS muito alto ou bridge sobrecarregada.

**Solução**:
1. Reduzir FPS (padrão 25 é ideal)
2. Aumentar smoothing_factor
3. Usar menos lâmpadas ativas

### Problema: Cores imprecisas

**Causa**: Gamut da lâmpada não suporta a cor.

**Solução**:
1. Implementado: Clamping de XY
2. Futuro: Gamut mapping por modelo de lâmpada

### Problema: Bridge desconecta

**Causa**: Timeout ou bridge reiniciada.

**Solução**:
1. Implementar retry logic (planejado)
2. Refresh automático de luzes

---

## Dual transport — Hue Entertainment streaming

High-rate music/screen paths push frames through `LightOutputPort`:

| Component | Path |
|-----------|------|
| Port | `marvin_hue/output/port.py` |
| REST adapter | `marvin_hue/output/rest_adapter.py` (`HueController` / phue) |
| Entertainment adapter | `marvin_hue/output/entertainment_adapter.py` (DTLS HueStream) |
| Fallback | `marvin_hue/output/fallback.py` (Entertainment → REST on failure) |
| Factory | `marvin_hue/output/factory.py` |
| Client | `marvin_hue/entertainment/client.py` (`hue-entertainment`) |
| Credentials | env + `.res/hue_entertainment_creds.json` (never chat SQLite) |

Feature flag `ENTERTAINMENT_ENABLED` (default **false**). When disabled or unpaired, behavior is REST-only. Eye safety still clamps brightness before frames are sent. Plan: [`docs/plans/2026-08-08-hue-entertainment-music-upgrade.md`](plans/2026-08-08-hue-entertainment-music-upgrade.md).

---

## Referências

- [Philips Hue API Documentation](https://developers.meethue.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [LangChain Documentation](https://python.langchain.com/)
- [Color Space Conversion](https://en.wikipedia.org/wiki/SRGB)
- [CIE 1931 Color Space](https://en.wikipedia.org/wiki/CIE_1931_color_space)

---

Este documento foi gerado como parte da Fase 3.3 do plano de melhorias.
Última atualização: 2026-08-08
