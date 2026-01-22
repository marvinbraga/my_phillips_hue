# Marvin Hue Test Suite

Comprehensive test suite for the Marvin Hue Philips Hue controller application.

## Quick Start

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest tests/

# Run with coverage report
uv run pytest tests/ --cov=marvin_hue --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Test Structure

```
tests/
├── conftest.py              # Pytest fixtures and mocks
├── test_colors.py           # Color class tests (24 tests)
├── test_utils.py            # RGB/XY conversion tests (22 tests)
├── test_basics.py           # Configuration management tests (23 tests)
├── test_controllers.py     # Hue controller tests (33 tests)
└── test_api.py              # FastAPI endpoint tests (40 tests)
```

## Test Coverage

- **Overall:** 39% (target: 70%+ on critical modules)
- **Critical modules:** 77-97% ✅
  - `basics.py`: 97%
  - `logging_config.py`: 97%
  - `utils.py`: 90%
  - `colors.py`: 85%
  - `controllers.py`: 77%

## Running Specific Tests

```bash
# Single test file
uv run pytest tests/test_colors.py -v

# Single test class
uv run pytest tests/test_colors.py::TestColorValidation -v

# Single test function
uv run pytest tests/test_colors.py::TestColorValidation::test_valid_rgb_values -v

# Tests matching pattern
uv run pytest tests/ -k "color" -v
```

## Writing Tests

### Using Fixtures

```python
def test_color_creation(sample_color):
    """Test using the sample_color fixture."""
    assert sample_color.red == 255
    assert sample_color.brightness == 200
```

### Available Fixtures

- `sample_color` - Single Color instance
- `sample_light_config` - Complete LightConfig
- `mock_hue_controller` - Mocked HueController (no hardware)
- `fastapi_test_client` - TestClient for API testing
- See `conftest.py` for complete list

### Testing with Mocks

All hardware interactions are mocked to enable fast, reliable tests:

```python
def test_set_light_color(mock_hue_controller):
    """Tests run without real Hue Bridge."""
    color = Color(255, 100, 50, 200)
    light = mock_hue_controller.set_light_color("Test Light", color)
    assert light is not None
```

## Test Categories

### Unit Tests (98 tests)
- Colors: Validation, serialization, edge cases
- Utils: RGB/XY conversion, gamma correction
- Basics: Configuration loading, JSON operations
- Controllers: Light control, status, conversions

### API Tests (40 tests)
- Endpoints: GET/POST operations
- Validation: Request/response formats
- Errors: 404, 405, 422 handling
- Integration: Full workflows

## Development Workflow

1. **Before coding:** Check existing tests understand expected behavior
2. **While coding:** Run relevant test file: `uv run pytest tests/test_<module>.py`
3. **After coding:** Run full suite: `uv run pytest tests/`
4. **Before commit:** Ensure all tests pass and coverage is maintained

## Continuous Integration

Tests automatically run on:
- Every commit (local pre-commit hook)
- Every pull request (GitHub Actions)
- Before deployment (CI/CD pipeline)

## Troubleshooting

### Tests fail with "ValueError: brightness 255"
- Brightness must be 0-254 (Hue API limit)
- Update test data to use 254, not 255

### "ModuleNotFoundError: No module named 'pytest'"
- Run: `uv sync --extra dev`

### "AttributeError: 'NoneType' object has no attribute..."
- Check that mocks are properly configured in `conftest.py`
- Ensure fixture is passed to test function

## More Information

- [Test Foundation Summary](../docs/TEST_FOUNDATION_SUMMARY.md) - Detailed implementation notes
- [Improvement Plan](../docs/IMPROVEMENT_PLAN.md) - Overall project roadmap
- [pytest documentation](https://docs.pytest.org/) - Official pytest guide
