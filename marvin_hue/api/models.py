"""
Pydantic Models para API
Todos os modelos de validação de dados da API.
"""
import re
from pydantic import BaseModel, Field, field_validator


class ApplyConfigRequest(BaseModel):
    config_name: str = Field(..., min_length=1, max_length=100, description="Nome da configuração")
    transition_time_secs: float = Field(default=0, ge=0, le=60, description="Tempo de transição em segundos")
    duration_minutes: float | None = Field(default=None, ge=0, le=1440, description="Duração em minutos")

    @field_validator('config_name')
    @classmethod
    def sanitize_config_name(cls, v: str) -> str:
        """Remove caracteres potencialmente perigosos."""
        sanitized = re.sub(r'[^\w\s\-]', '', v)
        return sanitized.strip()


class LightPosition(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    position: str = Field(..., pattern=r'^(none|left|right|top|bottom|top-left|top-right|bottom-left|bottom-right|center|ambient)$')
    enabled: bool


class PositionsUpdate(BaseModel):
    lights: list[LightPosition] = Field(..., min_length=1, max_length=50)


class MirrorStartRequest(BaseModel):
    fps: int = Field(default=25, ge=1, le=60, description="FPS para espelhamento")
    brightness: int = Field(default=200, ge=0, le=254, description="Brilho das lâmpadas")


class MirrorSettingsRequest(BaseModel):
    fps: int | None = Field(default=None, ge=1, le=60)
    brightness: int | None = Field(default=None, ge=0, le=254)
    saturation_boost: float | None = Field(default=None, ge=0, le=3)
    smoothing_factor: float | None = Field(default=None, ge=0, le=1)
    transition_time: float | None = Field(default=None, ge=0, le=10)


class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="Mensagem para o agente")

    @field_validator('message')
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        """Remove espaços extras e valida."""
        return v.strip()


class ChatConfigRequest(BaseModel):
    provider: str = Field(..., pattern=r'^(openai|anthropic|ollama)$')
    model: str = Field(..., min_length=1, max_length=100)
    temperature: float = Field(default=0.7, ge=0, le=2)
