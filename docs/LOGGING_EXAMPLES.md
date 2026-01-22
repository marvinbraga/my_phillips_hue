# Logging Examples - Before and After

This document shows the improvements made to error handling and logging in Phase 1.2.

## Before and After Comparisons

### Example 1: basics.py - File Load Error

**Before (with print):**
```python
except (IOError, JSONDecodeError) as e:
    print(f"An error occurred while reading the file: {str(e)}.")
```

**After (with logging):**
```python
except (IOError, JSONDecodeError) as e:
    logger.error(f"Error reading file {self._filename}: {str(e)}", exc_info=True)
```

**Benefits:**
- ✅ Includes full traceback with `exc_info=True`
- ✅ Includes filename context
- ✅ Structured timestamp
- ✅ Properly classified as ERROR level

---

### Example 2: controllers.py - Silent Exception

**Before (silent failure):**
```python
try:
    # ... get status code ...
except Exception:
    pass  # Ignora lâmpadas com erro
```

**After (with logging):**
```python
try:
    # ... get status code ...
except Exception as e:
    logger.warning(f"Error getting status for light '{light.name}': {str(e)}")
```

**Benefits:**
- ✅ No more silent failures
- ✅ Includes light name for debugging
- ✅ Error is logged but doesn't crash the application
- ✅ Easy to track problematic lights

---

### Example 3: screen_mirror.py - Color Application Error

**Before (silent failure):**
```python
try:
    xy = RGBtoXYAdapter.convert(smoothed[0], smoothed[1], smoothed[2])
    light = self.hue._get_light_by_name(light_name)
    if light:
        light.transitiontime = int(round(self.transition_time))
        light.xy = xy
        light.brightness = self.brightness
except Exception:
    pass  # Ignora erros de comunicação com lâmpadas individuais
```

**After (with logging):**
```python
try:
    xy = RGBtoXYAdapter.convert(smoothed[0], smoothed[1], smoothed[2])
    light = self.hue._get_light_by_name(light_name)
    if light:
        light.transitiontime = int(round(self.transition_time))
        light.xy = xy
        light.brightness = self.brightness
    else:
        logger.warning(f"Light '{light_name}' not found during screen mirroring")
except Exception as e:
    logger.debug(f"Error applying color to light '{light_name}': {str(e)}")
```

**Benefits:**
- ✅ Distinguishes between "light not found" and "communication error"
- ✅ Uses appropriate log levels (WARNING vs DEBUG)
- ✅ Includes light name in error message
- ✅ Communication errors at DEBUG level (expected in screen mirroring)

---

### Example 4: app.py - Application Startup

**Before (with print):**
```python
print(f"[Chat] Inicializando agente com provider='{chat_provider}', model='{chat_model}'")

try:
    chat_agent = create_hue_agent(...)
    print(f"[Chat] Agente inicializado com sucesso!")
except Exception as e:
    print(f"[Chat] Erro ao inicializar agente: {e}")
    chat_agent = None
```

**After (with logging):**
```python
logger.info(f"Initializing chat agent with provider='{chat_provider}', model='{chat_model}'")

try:
    chat_agent = create_hue_agent(...)
    logger.info("Chat agent initialized successfully")
except Exception as e:
    logger.error(f"Error initializing chat agent: {e}", exc_info=True)
    chat_agent = None
```

**Benefits:**
- ✅ Structured timestamps for all messages
- ✅ Full traceback on errors with `exc_info=True`
- ✅ Proper log level classification
- ✅ Module-specific logger for filtering

---

## Log Output Examples

### Successful Operation
```
2026-01-22 13:35:53 - marvin_hue.app - INFO - Starting Marvin Hue application
2026-01-22 13:35:53 - marvin_hue.controllers - INFO - Initializing Hue Controller with bridge IP: 192.168.5.160
2026-01-22 13:35:54 - marvin_hue.controllers - INFO - Connected to Hue Bridge. Found 9 lights
2026-01-22 13:35:54 - marvin_hue.basics - INFO - Successfully loaded 154 configurations from .res/setups.json
2026-01-22 13:35:54 - marvin_hue.app - INFO - Initializing chat agent with provider='openai', model='gpt-4o-mini'
2026-01-22 13:35:54 - marvin_hue.app - INFO - Chat agent initialized successfully
```

### Configuration Application
```
2026-01-22 14:23:15 - marvin_hue.controllers - INFO - Applying configuration 'concentration' with 8 lights (transition: 2.0s)
2026-01-22 14:23:15 - marvin_hue.controllers - DEBUG - Setting light 'Lâmpada 1' to RGB(255, 244, 229), brightness=254
2026-01-22 14:23:15 - marvin_hue.controllers - DEBUG - Successfully applied color to 'Lâmpada 1'
2026-01-22 14:23:15 - marvin_hue.controllers - DEBUG - Setting light 'Lâmpada 2' to RGB(255, 244, 229), brightness=254
2026-01-22 14:23:15 - marvin_hue.controllers - DEBUG - Successfully applied color to 'Lâmpada 2'
2026-01-22 14:23:16 - marvin_hue.controllers - INFO - Configuration 'concentration' applied successfully
```

### Error Handling
```
2026-01-22 14:25:30 - marvin_hue.controllers - WARNING - Light 'Invalid Light' not found
2026-01-22 14:25:30 - marvin_hue.controllers - WARNING - Error getting status for light 'Unreachable Light': connection timeout
2026-01-22 14:25:31 - marvin_hue.basics - ERROR - Error reading file .res/missing.json: [Errno 2] No such file or directory
Traceback (most recent call last):
  File "marvin_hue/basics.py", line 71, in load
    with open(self._filename, "r", encoding="utf-8") as f:
FileNotFoundError: [Errno 2] No such file or directory: '.res/missing.json'
```

### Screen Mirroring
```
2026-01-22 14:30:00 - marvin_hue.screen_mirror - INFO - Starting screen mirroring (FPS: 25, brightness: 200)
2026-01-22 14:30:00 - marvin_hue.screen_mirror - DEBUG - Loaded 6 active lights from positions file
2026-01-22 14:30:15 - marvin_hue.screen_mirror - DEBUG - Error applying color to light 'Hue Play 1': connection refused
2026-01-22 14:31:45 - marvin_hue.screen_mirror - INFO - Stopping screen mirroring
2026-01-22 14:31:47 - marvin_hue.screen_mirror - INFO - Screen mirroring stopped successfully
```

---

## Log Levels Usage Guide

| Level | Usage | Example |
|-------|-------|---------|
| **DEBUG** | Detailed diagnostic information | RGB values, XY coordinates, per-light operations |
| **INFO** | General informational messages | Startup, configuration applied, connection established |
| **WARNING** | Warning messages for recoverable issues | Light not found, unreachable light, invalid config |
| **ERROR** | Error messages for serious problems | File read errors, connection failures, initialization errors |
| **CRITICAL** | Critical issues (not currently used) | Reserved for system-critical failures |

---

## Filtering Logs by Module

You can easily filter logs by module using grep:

```bash
# View only controller logs
grep "marvin_hue.controllers" logs/marvin_hue.log

# View only errors
grep "ERROR" logs/marvin_hue.log

# View screen mirroring activity
grep "marvin_hue.screen_mirror" logs/marvin_hue.log

# View application lifecycle
grep "marvin_hue.app" logs/marvin_hue.log

# View only warnings and errors
grep -E "WARNING|ERROR" logs/marvin_hue.log
```

---

## Log Rotation

The logging system automatically rotates log files when they reach 10MB:

```
logs/
├── marvin_hue.log       # Current log file
├── marvin_hue.log.1     # Previous log (most recent)
├── marvin_hue.log.2
├── marvin_hue.log.3
├── marvin_hue.log.4
└── marvin_hue.log.5     # Oldest backup
```

After 5 backups, the oldest log is deleted when a new rotation occurs.

---

## Summary of Improvements

| Aspect | Before | After |
|--------|--------|-------|
| **Error Visibility** | Silent failures | All errors logged with context |
| **Debugging** | No timestamps, scattered prints | Structured logs with timestamps |
| **Context** | Minimal context | Rich context (light names, RGB values, etc.) |
| **Tracebacks** | Not captured | Full tracebacks with `exc_info=True` |
| **Log Levels** | All at same level (print) | Proper classification (DEBUG/INFO/WARNING/ERROR) |
| **Filtering** | Impossible | Easy filtering by module/level |
| **Rotation** | N/A | Automatic rotation at 10MB |
| **Production Ready** | No | Yes |
