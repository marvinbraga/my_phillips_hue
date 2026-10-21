# Eval Report — seleção de tool do chat (hue.chat@2)

Triple (branch): `hue.chat.prompt@2` | `claude-haiku-5-5` | `hue.chat@2`
Triple (baseline): `hue.chat.prompt@1 (implícito)` | `claude-haiku-5-5` | `hue.chat@2`
Superfície de prompt (sha256): baseline `8c350612f380`, branch `ff41e68f04a9`
N = 3 execuções por caso; bridge e serviços mockados.

| Caso | Pré-existente | Tools esperadas | Baseline | Branch | Δ |
|---|---|---|---|---|---|
| `sel-turn-off-all` | sim | turn_off_lights | 100% | 100% | +0 pp |
| `sel-color-one-light` | sim | set_light_color | 100% | 100% | +0 pp |
| `sel-apply-scene` | sim | apply_config | 100% | 100% | +0 pp |
| `sel-status` | sim | get_light_status | 100% | 100% | +0 pp |
| `sel-room-brightness` | sim | set_room_brightness, set_brightness | 100% | 100% | +0 pp |
| `sel-save-current` | sim | save_current_config | 100% | 100% | +0 pp |
| `sel-add-favorite` | sim | add_favorite | 100% | 100% | +0 pp |
| `sel-search-theme` | não | search_configs | n/a | 100% | n/a |
| `sel-describe` | não | describe_config | n/a | 100% | n/a |
| `sel-create-spec` | não | create_config | n/a | 100% | n/a |
| `sel-undo` | não | undo_last_scene | n/a | 100% | n/a |
| `sel-group-apply` | não | apply_config_to_group | n/a | 100% | n/a |
| `sel-list-schedules` | não | list_schedules | n/a | 100% | n/a |
| `sel-create-schedule` | não | create_schedule | n/a | 100% | n/a |
| `sel-start-mirror` | não | start_mirror | n/a | 100% | n/a |
| `sel-kelvin` | não | set_color_temperature | n/a | 100% | n/a |
| `sel-health` | não | get_system_health | n/a | 100% | n/a |

| Métrica | Baseline | Branch | Δ | Limite | Status |
|---|---|---|---|---|---|
| Acerto intents pré-existentes | 100% | 100% | +0.0 pp | Δ ≥ 0 | OK |
| Acerto tools novas | n/a | 100% | n/a | ≥ 90% | OK |
| Tokens de entrada / execução | 15404 | 18937 | +23% | informativo | — |
| Tokens de saída / execução | 339 | 303 | -11% | informativo | — |

**Veredito: PASS**

## Falhas por execução (branch)

Nenhuma.

## Iterações

| # | Mudança na superfície | Pré-existentes (baseline → branch) | Tools novas | Veredito |
|---|---|---|---|---|
| 1 | `hue.chat.prompt@2` (Gate 8 #16: descrições com referências cruzadas, `list_configs` → `search_configs` para tema, salas por prefixo, `create_schedule` desativado por padrão, exemplo "aconchegante") | 100% → 100% | 100% | PASS |

Nenhuma iteração adicional foi necessária.

## Configuração e reprodução

- Golden set: `tests/eval/invariants.json` (`hue.chat@2`, dono: Marcus Vinicius Braga). 17 casos `level=prompt` (7 pré-existentes, 10 de tools novas); `test_no_golden_leakage_into_prompts_or_tool_descriptions` garante que nenhuma frase do golden set aparece em prompt, subagent ou descrição/schema de tool.
- Modelo: `claude-haiku-5-5` (Anthropic, via `LLMProviderFactory`; parâmetros de amostragem omitidos para Claude 5, então N=3 por caso).
- Baseline: `origin/master` (6c90e0a) em worktree, mesmo runner e mesmo golden set; casos de tools novas ficam `n/a` no baseline (a tool não existe lá).
- Branch: `feat/16-chat-agent-tools` com `ChatServices` de fakes (`tests/chat/fakes.py`).
- Bridge, controller e serviços mockados; o manager lê uma cópia temporária de `.res/setups.json`. Nada fala com a bridge ou com o app em `:5081`.
- Tokens: soma de `usage_metadata` de todas as chamadas de modelo da execução (orquestrador e subagents), via callback. O aumento de ~23% na entrada vem das 17 tools novas no schema. Em produção o `AnthropicPromptCachingMiddleware` pode cachear esse prefixo; o efeito do cache não foi medido aqui.
- Comandos: ver docstring de `tests/eval/run_tool_selection.py`. A superfície avaliada tem hash `ff41e68f04a9…`, fixado em `tests/eval/prompt_version.json` e conferido no CI (`test_prompt_surface_fingerprint_pinned`).
