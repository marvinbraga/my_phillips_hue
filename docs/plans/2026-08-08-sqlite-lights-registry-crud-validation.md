# Validação → Plano READY (2026-08-08)

**Status:** READY (não READY_WITH_FIXES)  
**Plano:** [`2026-08-08-sqlite-lights-registry-crud.md`](./2026-08-08-sqlite-lights-registry-crud.md)

## O que mudou (resumo)

| Achado | Correção no plano |
|--------|-------------------|
| Sync por nome / reativa soft-delete | Identidade: `bridge_light_id` (preferir `uniqueid`) → depois `name`. Soft-delete **não** revive por padrão; `reactivate_deleted=true` opcional |
| Lookups ambíguos | `ORDER BY deleted_at IS NULL DESC, updated_at DESC LIMIT 1` + `get_by_bridge_light_id` |
| PATCH com `...` só em um campo | `_UNSET` uniforme em todos os campos opcionais; `model_dump(exclude_unset=True)`; `null` limpa anuláveis |
| Concorrência aiosqlite | Uma conexão + `asyncio.Lock`; WAL no `init_db` |
| Ordem de rotas | `status.router` primeiro; estáticos `/api/lights` e `/sync` antes de `/{light_id}` + testes de regressão |
| Task 11 dual recipe | Única receita: `asyncio.run` no conftest sync |
| Task 13 `svc._bridge` | Só `refresh_and_sync`; 503 genérico sem `str(exc)` em 5xx |
| Lifespan incompleto | Função completa com AsyncExitStack + try/finally do registry |
| Tasks grandes | Split: repo 4/5, service 7/9, DI 12 / lifespan 13 / conftest 14 |
| 400 vs 409 | `LightConflictError` → HTTP **409** |
| IntegrityError cru | Catch aiosqlite/sqlite3 → domínio |
| APP_DB_PATH | Validador: ≠ chat DB; proíbe basename `chat_memory.sqlite` |
| Controller tests | Classe real `TestHueControllerLightLookup` |
| Segurança | Nota LAN / sem API_KEY no v1 |
| DoD | 7 bullets |

## Lista de tasks (outline)

| # | Nome |
|---|------|
| 1 | aiosqlite + `app_db_path` + validação |
| 2 | Domain entity + `LightConflictError` |
| 3 | Schema + WAL |
| 4 | Repo create/get/list (+ lock, bridge id) |
| 5 | Repo update/soft-delete + lookups ordenados |
| 6 | Code review A |
| 7 | Service CRUD (`_UNSET`) |
| 8 | `HueController.list_bridge_lights` |
| 9 | Service sync (política soft-delete) |
| 10 | Code review B |
| 11 | Modelos Pydantic API |
| 12 | DI only |
| 13 | Lifespan completo |
| 14 | Conftest `asyncio.run` |
| 15 | Rotas CRUD + ordem |
| 16 | `POST /sync` + testes política |
| 17 | Code review C |
| 18 | Docs |
| 19 | Regressão + smoke |
| 20 | Code review D final |

## Decisões de design fixadas (sem forks)

1. **Match sync:** active by bridge_id → active by name → soft-deleted (só se `reactivate_deleted`) → create.
2. **Após soft-delete + create mesmo nome:** sync anexa `bridge_light_id` na linha **ativa** pelo nome.
3. **Rename na bridge:** match por `bridge_light_id` atualiza `name` (sem duplicar).
4. **Erro 5xx:** mensagem genérica; não vazar exceção bruta.
5. **Bootstrap testes:** apenas `asyncio.run` no fixture sync do TestClient.
