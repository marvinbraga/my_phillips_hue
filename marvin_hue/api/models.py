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
    mode: str = Field(
        default="screen",
        pattern=r"^(screen|audio)$",
        description="Modo: screen (tela) | audio (música)",
    )
    fps: int | None = Field(
        default=None, ge=1, le=60, description="FPS para espelhamento (sobrescreve profile)"
    )
    brightness: int | None = Field(
        default=None, ge=0, le=254, description="Brilho das lâmpadas (sobrescreve profile)"
    )
    profile: str | None = Field(
        default=None,
        pattern=(
            r"^(cinema|fps|ambient|party|chill|pulse|"
            r"subtle|moderate|high|extreme)$"
        ),
        description=(
            "Perfil: screen=cinema|fps|ambient; "
            "audio=party|chill|pulse|subtle|moderate|high|extreme"
        ),
    )
    area_id: str | None = Field(
        default=None,
        max_length=128,
        description="Entertainment area id (overrides ENTERTAINMENT_AREA_ID)",
    )
    transport_preference: str | None = Field(
        default=None,
        pattern=r"^(auto|rest|entertainment)$",
        description="Transporte: auto (default) | rest | entertainment",
    )
    config_name: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Nome da LightConfig cujas cores base o modo audio modula "
            "(omitir = free HSV; string vazia limpa)"
        ),
    )

    @field_validator("config_name")
    @classmethod
    def sanitize_mirror_start_config_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        sanitized = re.sub(r"[^\w\s\-]", "", v).strip()
        return sanitized or None


class MirrorSettingsRequest(BaseModel):
    mode: str | None = Field(
        default=None,
        pattern=r"^(screen|audio)$",
        description="Alvo das settings (padrão: modo ativo ou screen)",
    )
    fps: int | None = Field(default=None, ge=1, le=60)
    brightness: int | None = Field(default=None, ge=0, le=254)
    saturation_boost: float | None = Field(default=None, ge=0, le=3)
    smoothing_factor: float | None = Field(default=None, ge=0, le=1)
    transition_time: float | None = Field(default=None, ge=0, le=10)
    energy_gain: float | None = Field(
        default=None, ge=0.1, le=3.0, description="Ganho de energia (modo audio)"
    )
    profile: str | None = Field(
        default=None,
        pattern=(
            r"^(cinema|fps|ambient|party|chill|pulse|"
            r"subtle|moderate|high|extreme)$"
        ),
        description=(
            "Perfil: screen=cinema|fps|ambient; "
            "audio=party|chill|pulse|subtle|moderate|high|extreme"
        ),
    )
    entertainment_area_id: str | None = Field(
        default=None,
        max_length=128,
        description="Área Entertainment padrão para a próxima sessão",
    )
    transport_preference: str | None = Field(
        default=None,
        pattern=r"^(auto|rest|entertainment)$",
        description="Preferência de transporte (aplicada no próximo start)",
    )
    config_name: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Hot-swap da LightConfig base no modo audio "
            "(omitir = não alterar; string vazia limpa)"
        ),
    )

    @field_validator("config_name")
    @classmethod
    def sanitize_mirror_settings_config_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        sanitized = re.sub(r"[^\w\s\-]", "", v).strip()
        return sanitized or None


class MirrorProfileRequest(BaseModel):
    mode: str | None = Field(
        default=None,
        pattern=r"^(screen|audio)$",
        description="Modo do perfil (inferido pelo nome se omitido)",
    )
    profile: str = Field(
        ...,
        pattern=(
            r"^(cinema|fps|ambient|party|chill|pulse|"
            r"subtle|moderate|high|extreme)$"
        ),
        description="Perfil nomeado (screen ou audio/intensity)",
    )


class EntertainmentPairRequest(BaseModel):
    device_type: str | None = Field(
        default=None,
        max_length=64,
        description="devicetype registered with bridge (appname#devicename)",
    )


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


# --- Light groups ---


class GroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    light_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class GroupUpdateRequest(BaseModel):
    """Partial update. Omitted fields stay unchanged; explicit null clears nullables."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    light_ids: list[str] | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def strip_name_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class GroupResponse(BaseModel):
    id: str
    name: str
    room: str | None
    notes: str | None
    light_ids: list[str]
    deleted_at: str | None
    created_at: str
    updated_at: str


class GroupApplyRequest(BaseModel):
    config_name: str = Field(..., min_length=1, max_length=100)
    transition_time_secs: float = Field(default=0, ge=0, le=60)

    @field_validator("config_name")
    @classmethod
    def sanitize_config_name(cls, v: str) -> str:
        sanitized = re.sub(r"[^\w\s\-]", "", v)
        return sanitized.strip()


class GroupPowerRequest(BaseModel):
    on: bool


# --- Scene history ---


class HistorySnapshotRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    source: str = Field(default="manual", max_length=32)


class SceneSnapshotResponse(BaseModel):
    id: int | None
    label: str | None
    source: str
    created_at: str
    light_count: int


class HistoryUndoResponse(BaseModel):
    snapshot_id: int | None
    source: str
    label: str | None
    created_at: str
    restored_lights: list[str]
    restored_count: int


# --- Schedules ---


class ScheduleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    time_hhmm: str = Field(..., pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    action_type: str = Field(
        ...,
        pattern=r"^(apply_config|power_on|power_off|apply_group|turn_on|turn_off)$",
    )
    enabled: bool = True
    days_of_week: str = Field(default="", max_length=32)
    action_payload: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class ScheduleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    time_hhmm: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):([0-5]\d)$"
    )
    action_type: str | None = Field(
        default=None,
        pattern=r"^(apply_config|power_on|power_off|apply_group|turn_on|turn_off)$",
    )
    enabled: bool | None = None
    days_of_week: str | None = Field(default=None, max_length=32)
    action_payload: dict | None = None

    @field_validator("name")
    @classmethod
    def strip_name_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("name must be non-empty")
        return cleaned


class ScheduleResponse(BaseModel):
    id: str
    name: str
    enabled: bool
    time_hhmm: str
    days_of_week: str
    action_type: str
    action_payload: dict
    last_run_at: str | None
    created_at: str
    updated_at: str

