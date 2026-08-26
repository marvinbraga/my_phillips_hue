# Marvin Hue test suite

Run the suite before you open a pull request. Tests mock the Hue bridge; you do not need hardware.

## Quick start

```bash
uv sync --extra dev
uv run pytest
```

Coverage HTML is written to `htmlcov/` (see `pyproject.toml` addopts). Open `htmlcov/index.html` after a run. Do not treat a percentage from an old document as current.

Quiet mode (same command CI uses):

```bash
uv run pytest -q
```

## Layout

Tests live under `tests/`:

- `conftest.py` — shared fixtures and Hue/API mocks
- `test_*.py` — unit and HTTP tests (colors, controller, apply result, registry, groups, schedules, health, mirror, …)
- `chat/` — chat agent, providers, tools, middleware
- `eval/` — deterministic golden-set (no live LLM)

CI runs this suite on every pull request and on push to `master`/`main`. There is no required pre-commit hook.

## Running a subset

```bash
# One file
uv run pytest tests/test_colors.py -v

# One class
uv run pytest tests/test_colors.py::TestColorValidation -v

# Name pattern
uv run pytest tests/ -k "apply" -v
```

## Writing tests

Hardware stays mocked. Use fixtures from `conftest.py`:

```python
def test_color_creation(sample_color):
    assert sample_color.red == 255
    assert sample_color.brightness == 200
```

Useful fixtures:

- `sample_color` — a `Color`
- `sample_light_config` — a `LightConfig`
- `mock_hue_controller` — no bridge
- `fastapi_test_client` — `TestClient` for HTTP

Chat is disabled on the test client path (not the production lifespan). Settings import needs `BRIDGE_IP`; CI sets `BRIDGE_IP=127.0.0.1`.

## Troubleshooting

**`ValueError: brightness 255`** — Hue brightness is 0–254. Use 254 in fixtures.

**`ModuleNotFoundError: No module named 'pytest'`** — run `uv sync --extra dev`.

**`AttributeError` on a mock** — check the fixture in `conftest.py` is passed into the test.

## Next steps

- [CONTRIBUTING.md](../CONTRIBUTING.md) — local workflow and PR expectations
- [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) — how the app is layered
- [pytest documentation](https://docs.pytest.org/)
