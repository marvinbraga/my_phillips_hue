# Setup Hue Entertainment (checklist)

Streaming DTLS (HueStream) para música/tela — **opcional**. Com
`ENTERTAINMENT_ENABLED=false` (padrão) o comportamento continua só REST/`phue`.

## Pré-requisitos

- Bridge Philips Hue na rede local (IP conhecido)
- Lâmpadas compatíveis com Entertainment (Hue Play, Iris, gradient, etc.)
- Host do Marvin Hue na mesma LAN (UDP DTLS até a bridge)

## Checklist

### 1. Criar Entertainment area no app oficial

1. Abra o app **Philips Hue**
2. Vá em **Configurações → Entertainment areas** (ou similar)
3. Crie uma área e posicione as lâmpadas desejadas
4. Salve

Sem área, o smoke e o stream não avançam (exit code 3).

### 2. Emparelhar (botão da bridge)

1. **Pressione o botão de link** na bridge (fica ~30 s aberto)
2. Rode **um** dos caminhos:

```bash
# Script PoC (salva credenciais em .res/hue_entertainment_creds.json)
PAIR=1 BRIDGE_IP=<ip-da-bridge> uv run python scripts/entertainment_poc.py
```

Ou com a API no ar:

```bash
curl -X POST http://localhost:5081/mirror/entertainment/pair \
  -H 'Content-Type: application/json' \
  -d '{"device_type":"marvin_hue#entertainment"}'
```

Credenciais ficam em `.res/hue_entertainment_creds.json` (gitignored) **ou** em
`HUE_APP_KEY` + `HUE_CLIENT_KEY`. **Nunca** no SQLite do chat.

### 3. Habilitar no `.env`

```bash
ENTERTAINMENT_ENABLED=true
# Opcional — senão usa a primeira área listada:
# ENTERTAINMENT_AREA_ID=<uuid>
# ENTERTAINMENT_CREDS_FILE=.res/hue_entertainment_creds.json
# ENTERTAINMENT_FPS=40
```

Reinicie o servidor (`uv run python app.py` ou uvicorn).

### 4. Verificar (smoke)

```bash
# Readiness: IP, HTTP, credenciais, áreas (não inicia stream)
uv run python scripts/entertainment_smoke.py

# Opcional: flash branco ~2s na área
SMOKE_STREAM=1 uv run python scripts/entertainment_smoke.py
```

| Exit | Significado |
|------|-------------|
| 0 | Pronto (credenciais + áreas; stream OK se `SMOKE_STREAM=1`) |
| 2 | Config (BRIDGE_IP / credenciais) |
| 3 | Sem entertainment areas |
| 4 | Falha no stream |
| 5 | Bridge inacessível |

### 5. Confirmar transporte no app

1. Inicie espelhamento de **música** ou **tela**
2. Consulte status:

```bash
curl -s http://localhost:5081/mirror/status | jq '{transport, entertainment_enabled, entertainment_ready}'
```

Esperado com setup completo: `transport=entertainment`,
`entertainment_enabled=true`, `entertainment_ready=true`.

Se `transport=rest`, confira flag, credenciais, área e logs de fallback DTLS.

## Firewall / rede

- A bridge precisa aceitar **UDP DTLS** (Entertainment) a partir do host
- HTTPS local da bridge usa certificado self-signed (smoke ignora verify)

## Referências

- Config detalhada: [`CONFIGURATION.md`](CONFIGURATION.md) (seção Hue Entertainment)
- API: [`API.md`](API.md) — `/mirror/entertainment/*`
- Arquitetura: [`ARCHITECTURE.md`](ARCHITECTURE.md)
)
