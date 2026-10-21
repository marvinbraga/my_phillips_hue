# Home Scene Picker + Preview Implementation Plan

**Goal:** Na tela Controle (`/`), trocar o combobox "Escolha uma configuração" por uma lista completa e filtrável das configurações e mostrar, no card "Estado das Lâmpadas", uma **prévia** da cena escolhida sem enviá-la à bridge. A bridge só muda ao clicar em "Aplicar Configuração".

**Architecture:** O backend passa a expor, de forma opt-in, as cores de cada configuração já com o mesmo pipeline do apply real: RGB → XY → RGB com brilho limitado pelo eye safety e respeitando `enabled_for_app`. O frontend (jQuery, `web/static/index.js`) guarda o cache completo, filtra no cliente e renderiza a prévia por cima do estado real, sem pausar o polling.

**Stack:** FastAPI + Pydantic v2, Jinja2 + jQuery + Bootstrap (sem React), pytest. Não usar SQLAlchemy, Alembic nem Facade (`docs/PROJECT_RULES.md`).

## Q&A socrático (decisões fechadas)

### Rodada 1 — Dados

**P1. O navegador tem hoje o que precisa para a prévia?**
Não. `GET /configurations` (`marvin_hue/api/routes/configurations.py:91`) devolve só `name` e `description`.

**P2. Uma rota por nome ou um parâmetro na listagem?**
Há cerca de 70 temas × 9 lâmpadas (alguns KB). A prévia ao passar o mouse precisa de resposta instantânea, o que favorece trazer tudo de uma vez.
**Decisão:** `GET /configurations?include_settings=true`. Um booleano é mais simples de validar do que `include=settings`.

**P3. Mudar o formato padrão quebra alguém?**
Os consumidores atuais são `web/static/schedules.js:41`, `web/static/mirror.js:629`, `tests/test_api.py` e `tests/test_api_aliases.py` (paridade entre `/configurations` e `/api/configurations`).
**Decisão:** sem o parâmetro, a resposta continua byte a byte igual. O alias `/api/configurations` herda o parâmetro porque é a mesma rota (`app.py:58`).

**P4. As cores do JSON são as cores que a lâmpada realmente mostra?**
Não. O apply limita o brilho (`clamp_eye_safety(..., scale="hue")`, `controllers.py:82`), pula lâmpadas desabilitadas (`is_enabled_for_app`, `controllers.py:132`) e o estado real é exibido via `ColorConverter.xy_to_rgb(xy, brightness)` (`controllers.py:361`).
**Decisão:** o backend devolve, por lâmpada, a cor configurada (`color`) e um bloco `preview`:
- `{r, g, b}`, calculado por `ColorConverter.xy_to_rgb(ColorConverter.rgb_to_xy(r, g, b), brilho_efetivo)`;
- `brightness` efetivo;
- `enabled`.

Assim a prévia usa o mesmo espaço de cor do card real.

**P5. Onde fica essa lógica?**
Não deve ficar na rota nem em `setups.py`.
**Decisão:** criar uma função pura `build_scene_preview(config) -> list[...]` em `marvin_hue/services/scene_preview.py`. Ela é testável sem bridge e reutilizável pelo chat no futuro.

### Rodada 2 — Interação

**P6. A prévia aparece ao clicar ou ao passar o mouse?**
**Decisão:** nos dois casos.
- Clique ou Enter fixam a seleção e a prévia. As setas só mostram uma prévia temporária, que some quando o foco sai do filtro, e o Enter fixa (padrão de listbox, revisado depois do Gate 8).
- Hover mostra uma prévia temporária, com debounce de 80 ms, e ao sair volta para a seleção fixada (ou para o estado real).
- Em toque, só o clique conta.

**P7. Como ficam as lâmpadas que a cena não cobre?**
O apply não mexe nelas.
**Decisão:** aparecem com o estado atual, esmaecidas e com o rótulo "não alterada". Lâmpadas `enabled=false` aparecem como "desabilitada no app". Inacessíveis continuam marcadas como inacessíveis.

**P8. O polling de 3 s apaga a prévia?**
Hoje apagaria, porque `renderLights()` refaz tudo.
**Decisão:** o polling continua atualizando `lastLightsStatus`, e a renderização passa a ser `renderLights(lastLightsStatus, previewConfig)`. A prévia sobrevive e as lâmpadas não cobertas mostram o estado real atualizado.

**P9. Como o usuário sabe que está vendo uma prévia, e como sai dela?**
**Decisão:**
- selo "Prévia: <nome>" no cabeçalho do card, mais uma borda tracejada nas lâmpadas em prévia;
- botão "Ver estado real", e também Esc na lista;
- limpar o filtro não apaga a seleção.

**P10. O que acontece depois de Aplicar, Desligar ou Desfazer?**
**Decisão:** sair do modo prévia e chamar `loadLightsStatus()`. Em caso de erro no apply, a prévia continua.

### Rodada 3 — Lista e filtro

**P11. O que cada item mostra?**
**Decisão:** nome, descrição (truncada em 90 caracteres, com o texto completo no `title`) e uma faixa de bolinhas com as cores `preview`.

**P12. Como o filtro funciona?**
**Decisão:** reutilizar `normalizeFilterText`, sem diferenciar acentos nem maiúsculas, buscando no nome e na descrição. Um contador mostra "N de M". Se não houver resultados, aparece "Nenhum resultado para “…”". Se a seleção atual sumir do filtro, ela continua valendo e aparece acima da lista.

**P13. Altura e responsividade?**
**Decisão:** a lista ocupa a coluna da esquerda (`col-md-6`), com `max-height: 360px` e rolagem interna. No celular, ocupa a largura toda. Tempo de transição e botões continuam onde estão.

**P14. Acessibilidade?**
**Decisão:** `role="listbox"` com `aria-activedescendant`, itens `role="option"` com `aria-selected`, o filtro com `aria-controls` e a navegação por teclado a partir do filtro (↑ ↓ Enter Esc).

### Rodada 4 — Escopo e entrega

**P15. O que fica fora do escopo?**
- **Bug encontrado:** "Desligar Todas" envia `config_name: "all_off"`, que não existe em `.res/setups.json`, então o `POST /apply` dá 404. Vai virar uma issue separada, sem correção neste ciclo. (Resolvido na #9 com `POST /lights/off`.)
- `duration_minutes` continua ignorado.

**P16. E as mudanças locais que não são minhas?**
Hoje existem `.res/setups.json` modificado, `.res/light_physical_locations.json.bak` e `docs/jarvis-dev-cycle/`.
**Decisão:** não entram nos commits deste ciclo. Faço stage seletivo.

**P17. Quais testes?**
- `tests/test_scene_preview.py` (unit): clamp aplicado em Fita Led / Led cima, `enabled=false`, RGB de preview determinístico, brilho 0.
- `tests/test_api.py` / `tests/test_api_aliases.py`: formato padrão inalterado, `include_settings=true` com `settings` e `preview`, paridade com o alias.
- O JS não tem suíte, então a validação é manual no navegador (Etapa 5).

Não há mais dúvidas em aberto.

## Etapas

### 1. Backend
1. `marvin_hue/services/scene_preview.py`: `ScenePreviewLight` (dataclass) + `build_scene_preview(config: LightConfig)`.
2. `marvin_hue/api/models.py`: `ConfigurationPreviewColor`, `ConfigurationSetting`, `ConfigurationSummary` (com `settings` opcional).
3. `configurations.py`: `get_configurations(include_settings: bool = False)`. A resposta padrão continua `list[{name, description}]`.
4. Os testes da P17.

### 2. Frontend: lista
1. `web/templates/index.html`: trocar o bloco `.config-combobox` por `.config-picker` (filtro, contador, lista e selo da seleção). Adicionar o CSS no `<style>` da página.
2. `web/static/index.js`: `loadConfigurations()` passa a usar `?include_settings=true`. Remover as funções do combobox e criar `renderConfigList`, `selectConfiguration` e a navegação por teclado.

### 3. Frontend: prévia
1. Estado `lastLightsStatus`, `selectedConfig` e `hoverConfig`. A prévia efetiva é `hoverConfig || selectedConfig`.
2. `renderLights(lights, preview)`, com as classes `.preview`, `.untouched` e `.disabled-app`.
3. Selo e botão "Ver estado real" no cabeçalho. Limpar a prévia depois de Aplicar, Desligar ou Desfazer.
4. Cache-bust `index.js?v=picker-1`.

### 4. Documentação
Registrar `include_settings` em `docs/API.md`.

### 5. Validação
- `uv run pytest -q`
- `uv run ruff check marvin_hue tests`
- Manual em `http://localhost:5081/`: filtrar "lampada" deve casar com "lâmpada"; hover e clique mostram a prévia; as lâmpadas físicas não mudam; Aplicar faz voltar ao estado real; testar tema claro e escuro e largura de 375 px.

## Sequência Jarvis

| # | Comando | Saída |
|---|---|---|
| 1 | `/jarvis:scm-start` | Issue no GitHub, branch `feat/<ISSUE>-home-scene-preview` a partir de `master`. |
| 2 | `/jarvis:dev-python-fastapi` | Etapa 1 com TDD. |
| 3 | `/jarvis:dev-cycle` | Etapas 2 a 4 (frontend jQuery; `dev-cycle-frontend` é para Next.js). |
| 4 | `/jarvis:lint` | `ruff check marvin_hue tests`. |
| 5 | `/jarvis:codereview` | Os 8 revisores, com foco em consequences (consumidores de `/configurations`). |
| 6 | `/jarvis:dev-validation` | Critérios de aceite + aprovação do usuário. |
| 7 | `/jarvis:scm-ship` | `jarvis:commit` (atômico) + push + PR para `master` (o CI roda pytest + ruff). |
| 8 | `/jarvis:scm-merge` | Merge depois do CI verde; encadeia `jarvis:scm-finish`. |
