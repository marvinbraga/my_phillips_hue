"""HTTP middlewares for the Marvin Hue FastAPI app."""

from marvin_hue.api.middleware.api_key import ApiKeyMiddleware

__all__ = ["ApiKeyMiddleware"]
