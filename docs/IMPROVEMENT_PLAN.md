# Plano de Melhorias: Marvin Hue

## Objetivo Principal
Facilitar a manutenção futura do projeto através de:
- Redução significativa de duplicação de código
- Melhor organização e documentação
- Fundação sólida de testes e segurança
- Otimizações de performance e configuração

## Resumo Executivo

O codebase atual (~2.253 LOC) possui áreas críticas que precisam de melhoria:

**Crítico:**
- 🔴 Segurança: Possível exposição de chaves, falta de validação de inputs
- 🔴 Testes: Zero cobertura de testes (nenhum arquivo de teste encontrado)

**Alta Prioridade (Manutenibilidade):**
- 🟡 Duplicação: `setups.py` com 808 linhas de classes repetitivas (50+ configs idênticas)
- 🟡 Tratamento de Erros: Exceções silenciosas, prints ao invés de logging
- 🟡 Organização: `app.py` muito grande (604 linhas), sem separação por routers

**Média Prioridade:**
- 🟢 Type Hints: Faltando em `colors.py`, `utils.py` e outros arquivos críticos
- 🟢 Performance: Busca linear, I/O em loops, sem caching
- 🟢 Configuração: Nomes de luzes hardcoded, configurações espalhadas

---

## Fase 1: Segurança e Fundação de Testes (Semanas 1-2)

### 1.1 Segurança e Validação

**Arquivos a Modificar:**
- `marvin_hue/colors.py` (31 linhas)
- `marvin_hue/utils.py` (25 linhas)
- `marvin_hue/controllers.py` (102 linhas)
- `app.py` (604 linhas)
- `.env` / `.gitignore`

**Mudanças:**

1. **Validação de Inputs (colors.py)**
   - Adicionar validação no `__init__` da classe `Color`:
     - RGB: 0-255
     - Brightness: 0-254
     - Levantar `ValueError` com mensagens claras
   - Adicionar type hints completos

2. **Segurança de Conversão de Cores (utils.py)**
   - Validar RGB antes da conversão para XY
   - Proteger contra divisão por zero
   - Adicionar type hints
   - Documentar a matemática de conversão (sRGB → XY)

3. **Validação no Controller (controllers.py)**
   - Verificar se luz existe antes de aplicar cor
   - Adicionar timeout para operações com bridge
   - Validar coordenadas XY no gamut válido
   - Substituir `except: pass` por logging apropriado

4. **Segurança de API (app.py)**
   - Validar `config_name` antes de lookup
   - Sanitizar inputs de usuário
   - Adicionar rate limiting opcional (usar `slowapi`)
   - Configurar CORS adequadamente

5. **Auditoria de .env**
   - Verificar se `.env` está no `.gitignore`
   - Confirmar que não há secrets expostos no repo
   - Atualizar `.env.example` com todas as variáveis necessárias

**Resultado Esperado:**
- Todas as entradas validadas
- Erros claros e informativos
- Sem falhas silenciosas
- Sistema mais robusto

---

### 1.2 Infraestrutura de Logging

**Arquivos a Criar:**
- `marvin_hue/logging_config.py` (novo)

**Arquivos a Modificar:**
- `marvin_hue/basics.py` (95 linhas)
- `marvin_hue/controllers.py` (102 linhas)
- `marvin_hue/screen_mirror.py` (281 linhas)
- `app.py` (604 linhas)

**Mudanças:**

1. **Criar Configuração de Logging (logging_config.py)**
   ```python
   import logging
   from logging.handlers import RotatingFileHandler

   def setup_logging(log_level="INFO", log_file="logs/marvin_hue.log"):
       # Configurar loggers para cada módulo
       # Usar RotatingFileHandler para evitar logs gigantes
       # Formato estruturado com timestamps
       # Retornar dict de loggers
   ```

2. **Substituir Print Statements**
   - `basics.py:73-74`: `print(f"An error occurred...")` → `logger.error()`
   - `controllers.py:64-65`: `except: pass` → `logger.warning()` com contexto
   - `screen_mirror.py:194-195`: Adicionar logging em exceções
   - `app.py`: Substituir todos os `print()` por `logger.info()`

3. **Adicionar Contexto aos Logs**
   - Incluir nome da luz, valores RGB, nome da config
   - Logar tracebacks completos em erros
   - Usar níveis apropriados (DEBUG, INFO, WARNING, ERROR)

**Resultado Esperado:**
- Zero print statements no código
- Logs estruturados e rotacionados
- Fácil debugging de problemas em produção

---

### 1.3 Fundação de Testes

**Arquivos a Criar:**
- `tests/__init__.py`
- `tests/conftest.py` (fixtures compartilhadas)
- `tests/test_colors.py`
- `tests/test_utils.py`
- `tests/test_basics.py`
- `tests/test_controllers.py`
- `tests/test_api.py`

**Arquivos a Modificar:**
- `pyproject.toml` (adicionar dependências de teste)

**Mudanças:**

1. **Adicionar Dependências de Teste**
   ```toml
   [project.optional-dependencies]
   dev = [
       "pytest>=8.0.0",
       "pytest-asyncio>=0.23.0",
       "pytest-cov>=4.1.0",
       "pytest-mock>=3.12.0",
       "httpx>=0.26.0",
   ]
   ```

2. **Criar Fixtures (conftest.py)**
   - Mock do `HueController` (sem bridge real)
   - Mock do `LightSetupsManager`
   - Cliente de teste FastAPI
   - Configs de exemplo

3. **Testes Unitários (Prioridade)**

   **test_colors.py** (Mais crítico)
   - Validação de inputs (valores válidos/inválidos)
   - Serialização (`to_dict()`)
   - Edge cases (0, 255, 254)

   **test_utils.py** (Crítico - conversão de cores)
   - RGB → XY conversão precisa
   - Edge cases (preto, branco, cinzas)
   - Divisão por zero

   **test_basics.py**
   - Criação de `LightSetting` e `LightConfig`
   - Load/save de JSON
   - Lookup de configurações

   **test_controllers.py** (com mocks)
   - `set_light_color()` com inputs válidos
   - Erro quando luz não existe
   - `apply_light_config()`
   - Conversão XY → RGB

   **test_api.py**
   - GET /configurations
   - POST /apply (válido/inválido)
   - Tratamento de erros

**Meta de Cobertura:** 70% na Fase 1

**Resultado Esperado:**
- Suite de testes funcionando
- Coverage report configurado
- Testes passando em CI (GitHub Actions)

---

## Fase 2: Eliminar Duplicação de Código (Semanas 3-4)

**IMPACTO: 🎯 Reduzir setups.py de 808 linhas para ~100 linhas (-87%)**

### 2.1 Refatoração de Setups

**Arquivos a Criar:**
- `marvin_hue/setup_builder.py` (novo)
- `tests/test_setup_builder.py`

**Arquivos a Modificar:**
- `marvin_hue/setups.py` (808 linhas → ~100 linhas)
- `marvin_hue/factories.py`
- `.res/setups.json` (expandir)

**Problema Atual:**
```python
# setups.py tem 50+ classes quase idênticas:
class SetupConcentration(LightConfig):
    def __init__(self):
        settings = [
            LightSetting('Lâmpada 1', Color(255, 244, 229, 255)),
            LightSetting('Lâmpada 2', Color(255, 244, 229, 255)),
            # ... repetir para 8 luzes
        ]
        super().__init__('concentration', settings, 'Ambiente...')

class SetupRelax(LightConfig):
    def __init__(self):
        settings = [
            LightSetting('Lâmpada 1', Color(255, 147, 41, 180)),
            # ... repetir para 8 luzes
        ]
        super().__init__('relax', settings, 'Ambiente...')

# Repetido 50+ vezes!
```

**Solução: Abordagem Data-Driven**

1. **Criar Builder (setup_builder.py)**
   ```python
   from typing import Dict, List, Tuple
   from marvin_hue.basics import LightConfig, LightSetting
   from marvin_hue.colors import Color

   # Definir luzes padrão UMA vez
   STANDARD_LIGHTS = [
       'Lâmpada 1', 'Lâmpada 2', 'Lâmpada 4',
       'Hue Iris', 'Hue Play 1', 'Hue Play 2',
       'Fita Led', 'Led cima'
   ]

   class LightConfigBuilder:
       @staticmethod
       def from_dict(config: Dict) -> LightConfig:
           """Cria LightConfig a partir de dicionário."""
           settings = [
               LightSetting(light_name, Color(**color_data))
               for light_name, color_data in config['lights'].items()
           ]
           return LightConfig(
               name=config['name'],
               settings=settings,
               description=config.get('description', '')
           )

       @staticmethod
       def create_uniform(name: str, color: Tuple[int, int, int, int],
                         description: str = "") -> LightConfig:
           """Config com mesma cor para todas as luzes."""
           settings = [
               LightSetting(light, Color(*color))
               for light in STANDARD_LIGHTS
           ]
           return LightConfig(name, settings, description)
   ```

2. **Migrar para JSON (.res/setups.json)**
   ```json
   {
     "setups": [
       {
         "name": "concentration",
         "description": "Ambiente que estimula a concentração",
         "lights": {
           "Lâmpada 1": {"red": 255, "green": 244, "blue": 229, "brightness": 255},
           "Lâmpada 2": {"red": 255, "green": 244, "blue": 229, "brightness": 255},
           "Lâmpada 4": {"red": 255, "green": 244, "blue": 229, "brightness": 255}
         }
       }
     ]
   }
   ```

3. **Atualizar Factory (factories.py)**
   - Remover `LightConfigEnum` (50+ entradas)
   - Criar `LightConfigRegistry` que carrega dinamicamente do JSON
   - Manter compatibilidade com API existente

4. **Deprecar setups.py**
   - Adicionar aviso de deprecação no topo
   - Manter por uma versão para compatibilidade
   - Remover em versão futura

**Resultado Esperado:**
- 808 linhas → ~100 linhas (-87%)
- Configurações facilmente editáveis (JSON)
- Zero duplicação de código
- Novos setups não requerem código Python

---

### 2.2 Deduplicar Padrões no Controller

**Arquivos a Modificar:**
- `marvin_hue/controllers.py` (102 linhas)
- `marvin_hue/screen_mirror.py` (281 linhas)
- `marvin_hue/utils.py` (25 linhas)

**Mudanças:**

1. **Cache de Luzes (controllers.py)**
   ```python
   class HueController:
       def __init__(self, ip_address):
           self.bridge = Bridge(ip_address)
           self.bridge.connect()
           self._light_cache = {}  # Nome → Objeto
           self._refresh_cache()

       def _refresh_cache(self):
           lights = self.bridge.get_light_objects()
           self._light_cache = {light.name: light for light in lights}

       def _get_light_by_name(self, name: str):
           # O(1) lookup ao invés de O(n)
           return self._light_cache.get(name)
   ```

2. **Consolidar Conversão de Cores**
   - Criar classe `ColorConverter` em `utils.py`
   - Mover `rgb_to_xy()` de `RGBtoXYAdapter`
   - Mover `_xy_to_rgb()` de `controllers.py`
   - Ter ambas conversões em um só lugar

3. **Screen Mirror: Usar Controller**
   - Remover lógica duplicada de aplicação de cor
   - Usar `HueController.set_light_color()` diretamente

**Resultado Esperado:**
- Busca de luzes O(1) ao invés de O(n)
- Conversão de cores centralizada
- Menos código duplicado

---

## Fase 3: Organização e Qualidade (Semanas 5-6)

**IMPACTO: 🎯 Refatorar app.py de 604 linhas para ~100 linhas (-83%)**

### 3.1 Refatoração de app.py

**Arquivos a Criar:**
- `marvin_hue/api/__init__.py`
- `marvin_hue/api/routes/configurations.py`
- `marvin_hue/api/routes/positions.py`
- `marvin_hue/api/routes/mirror.py`
- `marvin_hue/api/routes/chat.py`
- `marvin_hue/api/routes/status.py`
- `marvin_hue/api/models.py` (Pydantic models)
- `marvin_hue/api/dependencies.py` (DI)
- `marvin_hue/api/websockets.py`

**Arquivos a Modificar:**
- `app.py` (604 linhas → ~100 linhas)

**Estrutura Nova:**

```
marvin_hue/api/
├── __init__.py
├── models.py              # Todos os Pydantic models
├── dependencies.py        # get_hue_controller(), etc.
├── websockets.py          # ConnectionManager, WS endpoints
└── routes/
    ├── configurations.py  # /configurations, /apply
    ├── positions.py       # /positions, /positions-config
    ├── mirror.py          # /mirror, /mirror/start, /mirror/stop
    ├── chat.py            # /chat (se relevante)
    └── status.py          # /api/bridge/status, /api/lights/status
```

**app.py novo (simplificado):**
```python
from fastapi import FastAPI
from marvin_hue.api.routes import (
    configurations, positions, mirror, status
)
from marvin_hue.api.websockets import setup_websockets

app = FastAPI(
    title="Marvin Hue API",
    description="API para controle de luzes Philips Hue",
    version="2.0.0"
)

# Registrar routers
app.include_router(configurations.router, prefix="/api/v1")
app.include_router(positions.router, prefix="/api/v1")
app.include_router(mirror.router, prefix="/api/v1")
app.include_router(status.router, prefix="/api/v1")

# Configurar WebSockets
setup_websockets(app)

# Página inicial (pode ficar aqui)
@app.get("/")
async def root():
    return FileResponse("templates/index.html")
```

**Benefícios:**
- Cada router: 50-100 linhas (gerenciável)
- Separação clara de responsabilidades
- Fácil adicionar autenticação por router
- Testes mais simples (testar routers isoladamente)
- Versionamento de API facilitado

**Resultado Esperado:**
- app.py: 604 → ~100 linhas (-83%)
- Código modular e organizado
- Fácil navegação e manutenção

---

### 3.2 Type Hints Completos

**Arquivos a Modificar:**
- `marvin_hue/colors.py` (31 linhas)
- `marvin_hue/utils.py` (25 linhas)
- `marvin_hue/basics.py` (95 linhas)
- `marvin_hue/controllers.py` (102 linhas)
- `marvin_hue/screen_mirror.py` (281 linhas)
- `pyproject.toml` (adicionar mypy)

**Mudanças:**

1. **Configurar mypy (pyproject.toml)**
   ```toml
   [tool.mypy]
   python_version = "3.10"
   warn_return_any = true
   warn_unused_configs = true
   disallow_untyped_defs = true

   [[tool.mypy.overrides]]
   module = "phue.*"
   ignore_missing_imports = true
   ```

2. **Adicionar Type Hints**
   - `colors.py`: Completar todos os métodos
   - `utils.py`: `def convert(red: int, green: int, blue: int) -> tuple[float, float]`
   - `basics.py`: Adicionar em `load()`, `save()`, `get_config()`
   - `controllers.py`: Completar missing return types
   - `screen_mirror.py`: Public methods

3. **Criar Type Stubs para phue**
   - `stubs/phue.pyi` com definições básicas

**Resultado Esperado:**
- `mypy marvin_hue/` sem erros
- Melhor autocomplete no IDE
- Menos erros de tipo em runtime

---

### 3.3 Documentação

**Arquivos a Criar:**
- `docs/API.md`
- `docs/ARCHITECTURE.md`
- `docs/CONFIGURATION.md`

**Arquivos a Modificar:**
- `readme.md` (atualizar e expandir)
- Todos os `.py` files (adicionar docstrings)

**Mudanças:**

1. **Adicionar Docstrings** (Google style)
   ```python
   class Color:
       """Representa uma cor RGBA para luzes Philips Hue.

       Attributes:
           red: Componente vermelho (0-255)
           green: Componente verde (0-255)
           blue: Componente azul (0-255)
           brightness: Brilho (0-254, limite da API Hue)

       Raises:
           ValueError: Se algum componente estiver fora do range válido

       Example:
           >>> color = Color(255, 100, 50, 200)
           >>> color.to_dict()
           {'red': 255, 'green': 100, 'blue': 50, 'brightness': 200}
       """
   ```

2. **Criar Documentação**
   - `API.md`: Todos os endpoints REST, protocolo WebSocket
   - `ARCHITECTURE.md`: Design do sistema, fluxo de dados
   - `CONFIGURATION.md`: Variáveis de ambiente, schemas JSON

3. **Atualizar README**
   - Adicionar badges (tests, coverage)
   - Expandir instalação e uso
   - Adicionar seção de troubleshooting
   - Linkar para docs detalhados

**Resultado Esperado:**
- APIs bem documentadas
- Novos desenvolvedores onboarding rápido
- Exemplos funcionais em docstrings

---

## Fase 4: Performance e Configuração (Semanas 7-8)

### 4.1 Otimizações de Performance

**Arquivos a Modificar:**
- `marvin_hue/basics.py` (95 linhas)
- `marvin_hue/controllers.py` (102 linhas)
- `marvin_hue/utils.py` (25 linhas)
- `marvin_hue/screen_mirror.py` (281 linhas)

**Mudanças:**

1. **Caching**
   - `@lru_cache` em `RGBtoXYAdapter.convert()` (função pura)
   - Cache de leitura de JSON com TTL em `LightSetupsManager`
   - Cache de light objects (já implementado na Fase 2)

2. **Async I/O**
   - Mover file I/O em `basics.py` para async
   - Usar `asyncio.gather()` para operações paralelas
   - Exemplo:
     ```python
     async def apply_multiple_configs(configs: List[str]):
         tasks = [apply_config(cfg) for cfg in configs]
         await asyncio.gather(*tasks)
     ```

3. **Screen Mirror**
   - Já otimizado (sampling, throttling, change detection)
   - Considerar: multiprocessing para screen capture
   - Benchmark diferentes resoluções de sampling

**Resultado Esperado:**
- Config loading < 100ms
- API response time < 200ms
- Uso eficiente de CPU/memória

---

### 4.2 Gestão Centralizada de Configuração

**Arquivos a Criar:**
- `marvin_hue/config.py`

**Arquivos a Modificar:**
- `app.py`
- `marvin_hue/controllers.py`
- Todos os arquivos que usam hardcoded values

**Mudanças:**

1. **Criar Settings com Pydantic**
   ```python
   from pydantic_settings import BaseSettings

   class Settings(BaseSettings):
       # Bridge
       bridge_ip: str
       bridge_timeout: int = 10

       # API
       api_key: str | None = None
       cors_origins: list[str] = ["*"]

       # Chat
       chat_provider: str = "openai"
       openai_api_key: str | None = None

       # Paths
       setups_file: str = ".res/setups.json"
       positions_file: str = ".res/light_positions.json"

       # Logging
       log_level: str = "INFO"
       log_file: str = "logs/marvin_hue.log"

       class Config:
           env_file = ".env"

   settings = Settings()
   ```

2. **Remover Hardcoded Values**
   - Nomes de luzes: carregar do config ou descobrir do bridge
   - Paths de arquivos: usar `settings.setups_file`
   - Timeouts e retry logic: configuráveis

3. **Light Discovery Dinâmico**
   - Não hardcodar "Lâmpada 1", "Hue Iris"
   - Query bridge na inicialização
   - Permitir usuário customizar nomes

**Resultado Esperado:**
- Configuração centralizada
- Fácil adaptar para diferentes setups
- Ambiente-specific configs (dev, prod)

---

## Verificação e Testes

### Após Fase 1
```bash
# Testes
uv run pytest --cov=marvin_hue --cov-report=html
# Deve ter 70%+ coverage

# Validação
uv run python -c "from marvin_hue.colors import Color; Color(-1, 0, 0)"
# Deve levantar ValueError

# Logs
tail -f logs/marvin_hue.log
# Não deve ter print statements
```

### Após Fase 2
```bash
# Verificar redução de linhas
wc -l marvin_hue/setups.py
# Deve ser ~100 linhas (era 808)

# Testes
uv run pytest tests/test_setup_builder.py
# Todos os setups devem carregar corretamente

# API
curl http://localhost:5081/configurations
# Deve retornar mesmas configs que antes
```

### Após Fase 3
```bash
# Type checking
uv run mypy marvin_hue/
# Sem erros

# Estrutura
ls marvin_hue/api/routes/
# Deve ter 5 arquivos de routers

# Docs
grep -r "def " marvin_hue/ | grep -v '"""'
# Todas as funções devem ter docstrings
```

### Após Fase 4
```bash
# Performance
time uv run python -c "from marvin_hue.basics import LightSetupsManager; LightSetupsManager('.res/setups.json').load()"
# Deve ser < 100ms

# Config
uv run python -c "from marvin_hue.config import settings; print(settings.bridge_ip)"
# Deve imprimir IP do .env
```

---

## Arquivos Críticos para Implementação

### Fase 1 (Segurança + Testes)
- `marvin_hue/colors.py` - Adicionar validação (31 linhas)
- `marvin_hue/utils.py` - Validar conversão (25 linhas)
- `marvin_hue/controllers.py` - Error handling (102 linhas)
- `marvin_hue/logging_config.py` - **CRIAR**
- `tests/` - **CRIAR diretório completo**
- `pyproject.toml` - Adicionar deps de teste

### Fase 2 (Deduplicação)
- `marvin_hue/setups.py` - Refatorar 808 → ~100 linhas
- `marvin_hue/setup_builder.py` - **CRIAR**
- `marvin_hue/factories.py` - Simplificar
- `.res/setups.json` - Expandir
- `marvin_hue/controllers.py` - Cache de luzes

### Fase 3 (Organização)
- `app.py` - Refatorar 604 → ~100 linhas
- `marvin_hue/api/` - **CRIAR toda estrutura**
- Todos `.py` - Adicionar type hints e docstrings
- `pyproject.toml` - Adicionar mypy
- `docs/` - **CRIAR documentação**

### Fase 4 (Performance)
- `marvin_hue/config.py` - **CRIAR**
- `marvin_hue/basics.py` - Async + cache
- `marvin_hue/utils.py` - lru_cache
- `marvin_hue/controllers.py` - Otimizações

---

## Cronograma Estimado

| Fase | Foco | Duração | Impacto |
|------|------|---------|---------|
| **Fase 1** | Segurança + Testes | 2 semanas | Fundação sólida |
| **Fase 2** | Deduplicação | 2 semanas | -700 linhas de código |
| **Fase 3** | Organização | 2 semanas | -500 linhas, melhor estrutura |
| **Fase 4** | Performance | 2 semanas | Sistema otimizado |
| **Total** | - | **8 semanas** | Codebase profissional |

---

## Métricas de Sucesso

### Fase 1
- ✅ 70%+ test coverage
- ✅ Todas as entradas validadas
- ✅ Zero print statements
- ✅ Logging operacional

### Fase 2
- ✅ setups.py: 808 → ~100 linhas (-87%)
- ✅ Duplicação < 5% (era ~60%)
- ✅ Configurações em JSON

### Fase 3
- ✅ app.py: 604 → ~100 linhas (-83%)
- ✅ 100% type hints (mypy clean)
- ✅ Documentação completa

### Fase 4
- ✅ Config loading < 100ms
- ✅ API response < 200ms
- ✅ Configuração centralizada

---

## Próximos Passos

1. **Criar branch de desenvolvimento**: `git checkout -b improvements/phase-1-security`
2. **Começar Fase 1.1**: Validação e segurança
3. **Commitar frequentemente**: Pequenos commits incrementais
4. **Executar testes**: Após cada mudança significativa
5. **Review**: Ao final de cada fase, fazer review completo

## Notas de Implementação

- **Compatibilidade**: Manter backward compatibility quando possível
- **Incremental**: Cada mudança deve deixar o sistema funcional
- **Testes First**: Escrever teste antes de refatorar (quando aplicável)
- **Documentar**: Atualizar docs conforme código muda
- **Git Tags**: Criar tag ao final de cada fase para rollback fácil
