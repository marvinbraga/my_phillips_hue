# Scene Favorites Implementation Plan

**Goal:** Marcar cenas como favoritas na lista da tela Controle (`/`), guardar os favoritos no SQLite do app, mostrar as favoritas no topo da lista e oferecer um filtro "★ Favoritos".

**Architecture:** O padrão segue ports & adapters do catálogo: migração v5, depois `SceneFavoritesRepository` (Protocol + `SqliteSceneFavoritesRepository`), depois `SceneFavoritesService`, depois as rotas. A ligação com as cenas é pelo nome da cena (`setups.json`), o mesmo join key do apply. O frontend continua em jQuery (`web/static/index.js`).

## Decisões (Q&A)

| # | Pergunta | Decisão |
|---|---|---|
| D1 | Onde persistir? | SQLite do app (`.res/marvin_hue.sqlite`), migração **v5**: `scene_favorites(config_name TEXT PRIMARY KEY NOT NULL, created_at TEXT NOT NULL)`. |
| D2 | Mudar `GET /configurations`? | **Não.** O formato atual fica intacto (é usado por schedules.js, groups.js e por testes). Os favoritos têm rota própria e o front busca as duas em paralelo. |
| D3 | Quais rotas? | Sem API key, como `/configurations` (UI da LAN). `GET /configurations/favorites` → `{"favorites": [nomes]}`. `PUT /configurations/favorites/{name}` → 200, ou 404 se a cena não existir no manager (idempotente). `DELETE /configurations/favorites/{name}` → 204, idempotente. O alias `/api/...` é automático. |
| D4 | O que fazer com favoritos órfãos (cena renomeada ou removida)? | Ficam no banco. O `GET` devolve só os nomes que existem no manager naquele momento. Se a cena voltar, o favorito volta junto. |
| D5 | Entra no backup? | Sim: um novo membro `favorites.json` na exportação. Na importação, `merge` faz a união e `replace` substitui. A ausência do membro é tolerada, para aceitar bundles antigos. |
| D6 | Onde fica a estrela? | No canto direito de cada item: ☆ ou ★ (`bi-star` / `bi-star-fill`). O clique não seleciona a cena nem dispara prévia (`stopPropagation`). A atualização é otimista e é revertida, com aviso discreto, se o servidor falhar. |
| D7 | E pelo teclado? | Com o filtro em foco, **Ctrl+D** alterna o favorito do item ativo (mesma convenção de "favoritar" dos navegadores; `preventDefault`). A estrela tem `tabindex="-1"`, porque não se coloca um controle interativo dentro de um `option`. A dica abaixo da lista menciona o atalho. |
| D8 | Como ordenar? | Com o filtro desligado, a seção "Favoritas" vem primeiro (ordem pt-BR), depois "Todas as cenas", sem repetir as favoritas. Com o filtro ligado, aparecem só as favoritas. O filtro de texto vale para as duas seções. |
| D9 | O estado do botão de filtro persiste? | Por navegador, em `localStorage` (é uma conveniência de quem está vendo), com try/catch. |
| D10 | Contador e estado vazio? | O contador mostra "N de M" ou, com o filtro ligado, "N de K favoritas". Sem nenhuma favorita e com o filtro ligado: "Nenhuma favorita ainda — clique na ☆ de uma cena". |
| D11 | E o chat? | Fora de escopo. Pode virar uma tool depois ("aplica minha favorita…"). |

## Sequência Jarvis
`scm-start` → `dev-python-fastapi` (Gate 0: backend e frontend em paralelo, com o contrato da D3) → `lint` → `codereview` → validação no navegador + `dev-validation` → `scm-ship` → `scm-merge`.
