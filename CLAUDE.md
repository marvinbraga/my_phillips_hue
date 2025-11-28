# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Marvin Hue is a Python application for controlling Philips Hue smart lights. It provides predefined lighting configurations (setups) for different moods and activities, with both CLI and web interfaces. Now includes real-time screen mirroring (ambient lighting).

## Commands

```bash
# Install dependencies
uv sync

# Run CLI to apply lighting configuration
uv run python main.py

# Run FastAPI web server
uv run python app.py
# or with auto-reload
uv run uvicorn app:app --reload --port 5000
```

## Configuration

Copy `.env.example` to `.env` and set `bridge_ip` to your Philips Hue Bridge IP address.

## Architecture

### Core Package (`marvin_hue/`)

- **colors.py**: `Color` class representing RGBA colors (red, green, blue, brightness 0-254)
- **utils.py**: `RGBtoXYAdapter` converts RGB colors to XY coordinates used by Philips Hue API
- **basics.py**:
  - `LightSetting`: Associates a light name with a color
  - `LightConfig`: Groups multiple `LightSetting` objects into a named configuration
  - `LightSetupsManager`: Loads/saves configurations from JSON files
- **controllers.py**: `HueController` wraps the `phue` library to apply configurations to the bridge
- **setups.py**: Predefined `LightConfig` subclasses (50+ themes like `SetupConcentration`, `CyberpunkNight`, etc.)
- **factories.py**: `LightConfigEnum` maps setup classes to descriptions for easy access
- **screen_mirror.py**: `ScreenMirror` class for real-time screen color capture and application to lights

### Entry Points

- **main.py**: CLI script that applies a lighting configuration directly
- **app.py**: FastAPI web server (async) with REST API and WebSocket:
  - `GET /` - Web UI for light configurations
  - `GET /configurations` - List available configurations
  - `POST /apply` - Apply a configuration
  - `GET /positions-config` - Light positioning configuration page
  - `GET /positions` - Get light positions
  - `POST /positions` - Save light positions
  - `GET /mirror` - Screen mirroring control page
  - `POST /mirror/start` - Start screen mirroring
  - `POST /mirror/stop` - Stop screen mirroring
  - `GET /mirror/status` - Get mirroring status
  - `WS /ws/mirror` - WebSocket for real-time color updates

### Screen Mirroring

The screen mirroring feature captures screen regions and applies dominant colors to configured lights:

1. Configure light positions in `/positions-config` (which region each light should mirror)
2. Start mirroring in `/mirror` page
3. Colors update in real-time via WebSocket (10 FPS to browser, 25 FPS to lights)

Position mappings in `.res/light_positions.json`:
- `left`, `right`, `top`, `bottom` - Edge regions
- `top-left`, `top-right`, `bottom-left`, `bottom-right` - Corner regions
- `center` - Center of screen
- `ambient` - Average color of entire screen
- `none` - Light doesn't participate in mirroring

### Data Flow

1. User selects a configuration (via CLI enum or web API)
2. `LightConfigEnum.get_instance()` creates a `LightConfig` object with `LightSetting` list
3. `HueController.apply_light_config()` iterates through settings
4. For each setting, RGB is converted to XY via `RGBtoXYAdapter` and sent to the bridge

### Light Names

The code expects specific light names matching your Hue setup: `Lâmpada 1-4`, `Hue Iris`, `Hue Play 1-2`, `Fita Led`, `Led cima`.

## Adding New Lighting Configurations

1. Create a new class in `marvin_hue/setups.py` extending `LightConfig`
2. Add an entry to `LightConfigEnum` in `marvin_hue/factories.py`
3. Alternatively, add to `.res/setups.json` for dynamic configurations loaded by `LightSetupsManager`

## Dependencies

- **FastAPI** + **uvicorn**: Async web framework
- **phue**: Philips Hue bridge communication
- **mss** + **Pillow**: Screen capture for mirroring
- **aiofiles**: Async file operations
- **Jinja2**: HTML templating
