"""
Pydantic Models para API
Todos os modelos de validação de dados da API.
"""

import re
from pydantic import BaseModel, Field, field_validator


class ApplyConfigRequest(BaseModel):
    config_name: str = Field(
        ..., min_length=1, max_length=100, description="Nome da configuração"
    )
    transition_time_secs: float = Field(
        default=0, ge=0, le=60, description="Tempo de transição em segundos"
    )
    duration_minutes: float | None = Field(
        default=None, ge=0, le=1440, description="Duração em minutos"
    )

    @field_validator("config_name")
    @classmethod
    def sanitize_config_name(cls, v: str) -> str:
        """Remove caracteres potencialmente perigosos."""
        sanitized = re.sub(r"[^\w\s\-]", "", v)
        return sanitized.strip()


class LightPosition(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    position: str = Field(
        ...,
        pattern=r"^(none|left|right|top|bottom|top-left|top-right|bottom-left|bottom-right|center|ambient)$",
    )
    enabled: bool


class PositionsUpdate(BaseModel):
    lights: list[LightPosition] = Field(..., min_length=1, max_length=50)


class MirrorStartRequest(BaseModel):
    fps: int = Field(default=25, ge=1, le=60, description="FPS para espelhamento")
    brightness: int = Field(
        default=200, ge=0, le=254, description="Brilho das lâmpadas"
    )


class MirrorSettingsRequest(BaseModel):
    fps: int | None = Field(default=None, ge=1, le=60)
    brightness: int | None = Field(default=None, ge=0, le=254)
    saturation_boost: float | None = Field(default=None, ge=0, le=3)
    smoothing_factor: float | None = Field(default=None, ge=0, le=1)
    transition_time: float | None = Field(default=None, ge=0, le=10)


class ChatMessageRequest(BaseModel):
    message: str = Field(
        ..., min_length=1, max_length=1000, description="Mensagem para o agente"
    )
    session_id: str = Field(
        default="default",
        max_length=128,
        description=(
            "Id de sessão estável por cliente. É o ÚNICO mecanismo de isolamento "
            "de histórico (thread_id do checkpointer compartilhado). O cliente DEVE "
            "enviar um id único e estável; 'default' significa SEM isolamento."
        ),
    )

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        """Remove espaços extras e valida."""
        return v.strip()


class ChatClearRequest(BaseModel):
    session_id: str = Field(
        default="default",
        max_length=128,
        description="Id da sessão cujo histórico deve ser limpo (thread_id).",
    )


class ChatConfigRequest(BaseModel):
    # Espelha os providers registrados (config.chat_provider Literal). "ollama"
    # foi removido (sem provider registrado); xai/groq são de primeira classe.
    provider: str = Field(..., pattern=r"^(openai|anthropic|xai|groq)$")
    model: str = Field(..., min_length=1, max_length=100)
    temperature: float = Field(default=0.7, ge=0, le=2)


# --- Lights registry (SQLite catalog) ---


class LightCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    nickname: str | None = Field(default=None, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    bridge_light_id: str | None = Field(default=None, max_length=64)
    eye_safety_limit_pct: int | None = Field(default=None, ge=0, le=100)
    enabled_for_app: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class LightUpdateRequest(BaseModel):
    """Partial update. Omitted fields stay unchanged; explicit null clears nullables."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    nickname: str | None = Field(default=None, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    bridge_light_id: str | None = Field(default=None, max_length=64)
    eye_safety_limit_pct: int | None = Field(default=None, ge=0, le=100)
    enabled_for_app: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class LightResponse(BaseModel):
    id: str
    name: str
    nickname: str | None
    room: str | None
    notes: str | None
    bridge_light_id: str | None
    eye_safety_limit_pct: int | None
    enabled_for_app: bool
    deleted_at: str | None
    created_at: str
    updated_at: str


class LightsSyncResponse(BaseModel):
    created: int
    updated: int
    unchanged: int
    skipped_deleted: int = 0
    total_bridge: int

