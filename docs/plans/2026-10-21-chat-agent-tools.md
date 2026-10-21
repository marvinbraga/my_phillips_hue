# Chat Agent Tools Expansion Plan

**Goal:** O Marvin (agente LangGraph do chat) passa a usar os serviços que o app já tem (cenas, desfazer, grupos, agendamentos, espelhamento, saúde), em vez de saber só mexer em lâmpadas.

**Princípio:** cada tool é um invólucro fino sobre um serviço existente. Nada de lógica de negócio nova dentro do chat. Os serviços chegam por um *container* de providers preguiçosos, e a tool nunca levanta exceção: devolve uma mensagem em português.

## Q&A socrático (validado contra o código)

### Rodada 1 — As premissas existem no código?

**P1. Os serviços têm a API que o plano supõe?**
Conferido:
- `ScheduleService.create_schedule(name, time_hhmm, action_type, enabled, days_of_week, action_payload)`, com `action_type ∈ {apply_config, power_on, power_off, apply_group}` e `days_of_week` em CSV de 0 (segunda) a 6 (domingo), onde vazio significa todo dia;
- `update_schedule(id, enabled=…)`;
- `GroupService.list_groups()` e `apply_config(group_id, config, hue)`;
- `MirrorControlService.start(mode, **kw)`, `stop()` (levanta `MirrorNotActiveError`) e `status()`;
- `SceneHistoryService.restore_last(hue)`;
- `collect_health(...)` em `services/health.py`;
- HITL em `react_agent.py:281` (`interrupt_on`).

**Decisão:** as premissas se confirmam, com as correções abaixo.

**P2. A rota de grupo tira snapshot, mas `GroupService.apply_config` não. O que a tool deve fazer?**
**Decisão:** `apply_config_to_group` tira o snapshot antes (fail-open), como `routes/groups.py:184`. Assim o Desfazer funciona.

**P3. Como o agente identifica grupo e agendamento, se os serviços usam UUID?**
**Decisão:** pelo **nome**, sem diferenciar maiúsculas. Se nada bater, devolve a lista. Se houver mais de um candidato, pede para desambiguar. O id também é aceito.

**P4. `create_schedule`: quais ações expor?**
**Decisão:** `apply_config`, `power_on` e `power_off`. `apply_group` exige o id do grupo e a cena, e fica para depois (YAGNI). O parâmetro `days` é uma lista de inteiros de 0 a 6, documentada como "0=segunda … 6=domingo; vazio = todo dia". O horário segue o formato `HH:MM`, que o domínio já valida.

### Rodada 2 — Design e riscos

**P5. Passar um parâmetro por serviço (favoritos, histórico, grupos…) ou outra coisa?**
São 7 serviços.
**Decisão:** um dataclass **`ChatServices`** com getters preguiçosos (`favorites`, `history`, `groups`, `schedules`, `mirror`, `lights_off`, `health`). Por padrão, cada getter resolve via `api.dependencies` e devolve `None` se o serviço não estiver pronto. Ele é passado de `create_hue_agent` → `HueLightAgent` → `build_*_tools`. O `favorites_provider` da etapa anterior é incorporado a esse container.

**P6. O `light_tools.py` já tem cerca de 730 linhas. Onde ficam as tools novas?**
A regra do gate limita arquivos a 1000 linhas.
**Decisão:** em módulos novos: `chat/tools/scene_tools.py` (search, describe, create, undo, favoritos), `chat/tools/automation_tools.py` (grupos e agendamentos) e `chat/tools/system_tools.py` (espelhamento, saúde, temperatura de cor). Um agregador `build_all_tools(...)` junta tudo.

**P7. Os serviços são assíncronos, mas existe o caminho síncrono `invoke`/`stream` (CLI). Como fica?**
**Decisão:** toda tool de serviço tem `coroutine=`. A versão síncrona **não** roda a coroutine: os serviços (aiosqlite, lock) ficam presos ao event loop do FastAPI, então ela devolve "disponível apenas no app" (ou "indisponível" sem serviço). É o mesmo critério das tools de favoritos. Tools só de controller (`set_color_temperature`) e de manager (`search/describe/create_config`) seguem síncronas.

**P8. Como garantir a segurança ocular nas tools novas que mexem em brilho?**
- `set_color_temperature` passa pelo `HueController.set_light_color`, que já é o ponto de controle autoritativo.
- `create_config` não aplica nada, então ela mesma limita o brilho com `effective_hue_brightness`.
- O `EyeSafetyMiddleware` só entende `light_name`. Nas tools com alvo de cômodo, a garantia fica no controller.

**Decisão:** dessa forma, sem mudar o middleware.

**P9. Quais tools mudam estado e entram no HITL quando `require_approval` está ligado?**
**Decisão:** `create_config` (approve/edit/reject), `apply_config_to_group`, `create_schedule`, `set_schedule_enabled`, `start_mirror`, `stop_mirror` e `undo_last_scene` (approve/reject). O padrão continua desligado, como hoje.

**P10. "Desligar tudo" pelo chat**
**Decisão:** `turn_off_lights` com `"all"` passa a usar o `LightsOffService` da #9: para o espelhamento, tira snapshot idempotente e grava em uma única leitura. Desligar uma lâmpada só continua como hoje.

**P11. 15 tools a mais aumentam o custo por chamada?**
Os schemas são enviados em toda chamada. Com o Haiku 5.5 a US$ 0,10/MTok, o `AnthropicPromptCachingMiddleware` já ativo e descrições curtas (uma frase cada), o custo extra é desprezível.
**Decisão:** descrições curtas.

**P12. `create_config` versus `save_current_config`: quando usar cada uma?**
**Decisão:**
- `create_config` grava pela especificação, sem perda: inclui lâmpadas inacessíveis e não passa pela conversão xy→rgb. Recusa nome duplicado e lâmpada inexistente.
- `save_current_config` fica para "salve como está agora".

O prompt de sistema explica a diferença em uma linha.

### Rodada 3 — Fechamento

**P13. A temperatura de cor precisa de suporte a `ct` no controller?**
**Decisão:** não. Kelvin vira RGB pela aproximação de Tanner Helland, numa função pura e testada, com limites de 2000 a 6500 K. Assim todo o caminho de cor e de eye safety é reaproveitado.

**P14. Saúde: o `collect_health` pede `chat_agent`. Isso cria dependência circular?**
**Decisão:** o getter resolve `dependencies.get_chat_agent()` na hora da chamada, sem import circular no módulo, porque o import fica dentro da função.

**P15. O espelhamento de tela precisa de posições e de perfil?**
**Decisão:** `start_mirror(mode="screen"|"audio", profile=None)`, com perfil validado contra `cinema`/`fps`/`ambient`. Os erros de validação do serviço viram mensagem. `get_mirror_status` devolve um resumo, sem o dict bruto.

**P16. Subagentes**
**Decisão:**
- `config-librarian` ganha `search_configs`, `describe_config`, `create_config`, `list_favorites`, `add_favorite` e `remove_favorite`;
- `scene-designer` ganha `set_color_temperature`, `describe_config` e `create_config`;
- `general-purpose` ganha `get_system_health`, `get_mirror_status`, `list_groups` e `list_schedules`.

O teste anti-typo de `test_subagent_definitions.py` cobre isso.

**P17. O bug de conteúdo em blocos também aparece nos subagentes?**
**Decisão:** sim. `task.py:_last_ai_text` passa a usar `_message_text`, que vai para um módulo comum `chat/messages.py` para evitar import circular.

**P18. Como testar sem a bridge?**
**Decisão:**
- testes unitários por tool, com serviços falsos e um `ChatServices` injetado;
- o agregador expõe todos os nomes, sem duplicatas;
- os subconjuntos dos subagentes estão válidos;
- `interrupt_on` cobre todas as tools de mutação;
- a validação manual no Chrome usa apenas consultas, mais uma criação explícita de agendamento **desabilitado**.

Não há dúvidas em aberto.

## Tools finais (16)

| Tool | Serviço | Muda estado? |
|---|---|---|
| `search_configs(query, limit=10)` | manager + preview | não |
| `describe_config(name)` | `build_scene_preview` | não |
| `create_config(name, description, settings[])` | manager.save | sim (HITL) |
| `undo_last_scene()` | SceneHistoryService | sim (HITL) |
| `list_groups()` | GroupService | não |
| `apply_config_to_group(group, config_name)` | GroupService + snapshot | sim (HITL) |
| `list_schedules()` | ScheduleService | não |
| `create_schedule(name, time_hhmm, action, config_name?, days?, enabled=True)` | ScheduleService | sim (HITL) |
| `set_schedule_enabled(schedule, enabled)` | ScheduleService | sim (HITL) |
| `get_mirror_status()` | MirrorControlService | não |
| `start_mirror(mode, profile?)` | MirrorControlService | sim (HITL) |
| `stop_mirror()` | MirrorControlService | sim (HITL) |
| `set_color_temperature(target, kelvin, brightness_pct?)` | controller | sim |
| `get_system_health()` | collect_health | não |
| `turn_off_lights("all")` | LightsOffService (alterada) | sim |
| `list_favorites` / `add_favorite` / `remove_favorite` | SceneFavoritesService (etapa anterior) | add/remove |

## Fora de escopo
Apagar cenas e agendamentos, ação `apply_group` em agendamento, backup e import, edição do registry.

## Sequência Jarvis
`dev-python-fastapi` (Gate 0, TDD), depois `lint`, `codereview`, validação no Chrome (chrome-devtools; só consultas, mais um agendamento criado desabilitado e removido em seguida), `scm-ship` e `scm-merge`.
