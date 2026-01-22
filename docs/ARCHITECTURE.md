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
- **Chat com IA**: Controle por linguagem natural usando LLMs (OpenAI, Anthropic, etc)
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
│(Hardware)│ │  (mss)   │ │   API    │
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
│      Data Storage (JSON Files)          │
│                                         │
│  - setups.json (Configurations)         │
│  - light_positions.json (Mirror config) │
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
            # ... repetir para 8 luzes
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

**Grupos de Endpoints**:

1. **Status**: `/api/bridge/status`, `/api/lights/status`
2. **Configurations**: `/configurations`, `/apply`
3. **Positions**: `/positions`, `/positions/reset`
4. **Mirror**: `/mirror/start`, `/mirror/stop`, `/mirror/status`
5. **Chat**: `/api/chat/message`, `/api/chat/status`
6. **WebSockets**: `/ws/mirror`, `/ws/chat`

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

**Providers Suportados**:
- **OpenAI**: gpt-4o, gpt-4o-mini
- **Anthropic**: claude-3-sonnet, claude-3-haiku
- **Ollama**: llama2, mistral (local)

**Decisões de Design**:
- ReAct agent para raciocínio + ação
- Tools específicas para domínio Hue
- História de conversação mantida em memória
- Fallback se API key não disponível

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
7. Response → {"message": "Applied..."}
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
4. WebSocket → Broadcast status (10 FPS)
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
- Performance: 8 luzes → não importa muito, mas escala melhor
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
- `mypy`: Type checking (planejado Fase 3.2)

---

## Estrutura de Diretórios

```
my_phillips_hue/
│
├── marvin_hue/              # Core package
│   ├── __init__.py
│   ├── colors.py            # Classe Color
│   ├── utils.py             # Conversão RGB ↔ XY
│   ├── basics.py            # LightSetting, LightConfig, Manager
│   ├── controllers.py       # HueController
│   ├── setup_builder.py     # Builder pattern para configs
│   ├── screen_mirror.py     # Espelhamento de tela
│   ├── logging_config.py    # Configuração de logging
│   ├── factories.py         # (Deprecated, manter por compatibilidade)
│   └── setups.py            # (Deprecated, usar setups.json)
│
├── web/                     # Frontend assets
│   ├── templates/           # Jinja2 templates
│   │   ├── index.html       # Página principal
│   │   ├── positions.html   # Config de posicionamento
│   │   ├── mirror.html      # Controle de espelhamento
│   │   └── chat.html        # Chat com agente
│   └── static/              # CSS, JS, imagens
│       ├── css/
│       ├── js/
│       └── img/
│
├── .res/                    # Recursos de dados
│   ├── setups.json          # Configurações de iluminação
│   └── light_positions.json # Mapeamento de posições
│
├── tests/                   # Testes
│   ├── __init__.py
│   ├── conftest.py          # Fixtures compartilhadas
│   ├── test_colors.py
│   ├── test_utils.py
│   ├── test_basics.py
│   ├── test_controllers.py
│   └── test_api.py
│
├── docs/                    # Documentação
│   ├── API.md               # Documentação da API
│   ├── ARCHITECTURE.md      # Este arquivo
│   ├── CONFIGURATION.md     # Configuração e variáveis
│   └── IMPROVEMENT_PLAN.md  # Plano de melhorias
│
├── logs/                    # Arquivos de log (gitignored)
│   └── marvin_hue.log
│
├── app.py                   # Aplicação FastAPI
├── main.py                  # CLI para testes
├── pyproject.toml           # Dependências e configuração
├── .env                     # Variáveis de ambiente (gitignored)
├── .env.example             # Template de .env
├── readme.md                # Documentação principal
└── LICENSE                  # GNU AGPL v3.0
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
- ✅ Configurações em JSON (data-driven)
- ✅ API REST + WebSocket
- ✅ Interface web
- ✅ Espelhamento de tela
- ✅ Chat com IA
- ✅ Logging estruturado
- ✅ Testes automatizados (70%+ coverage)
- ✅ Validação de inputs
- ✅ Type hints completos

### Versão 3.0 (Planejado)
- Autenticação e autorização
- Rate limiting
- Métricas e monitoring
- Suporte para múltiplas bridges
- Scheduler para automações temporais
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

### Faltando (Produção)

- ⚠️ Autenticação (API keys, OAuth)
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

## Referências

- [Philips Hue API Documentation](https://developers.meethue.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [LangChain Documentation](https://python.langchain.com/)
- [Color Space Conversion](https://en.wikipedia.org/wiki/SRGB)
- [CIE 1931 Color Space](https://en.wikipedia.org/wiki/CIE_1931_color_space)

---

Este documento foi gerado como parte da Fase 3.3 do plano de melhorias.
Última atualização: 2026-01-22
