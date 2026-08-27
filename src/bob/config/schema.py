"""Typed settings schema.

Nothing in B.O.B. reads a magic number from code. Every knob lives here with a
default, is documented by its field description, and is overridable from TOML or
the environment. Secrets are *only* ever read from the environment / ``.env``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RiskName = Literal["low", "medium", "high"]
PolicyName = Literal["allow", "confirm", "deny"]


class AppSettings(BaseModel):
    name: str = "B.O.B."
    tagline: str = "Beyond Orbit Buddy"
    language: str = Field("el", description="Primary spoken language (ISO 639-1).")
    start_minimized: bool = False
    autostart_with_windows: bool = False


class LoggingSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    console: bool = True
    json_files: bool = Field(True, description="Write log files as JSON lines for machine parsing.")
    max_bytes: int = 5_000_000
    backup_count: int = 3


class AudioSettings(BaseModel):
    input_device: str | None = Field(None, description="None = system default.")
    output_device: str | None = None
    sample_rate: int = 16_000
    frame_ms: int = Field(20, description="Frame size fed to VAD / wake word.")
    channels: int = 1
    allow_barge_in: bool = Field(True, description="Let the user interrupt B.O.B. mid-sentence.")
    barge_in_threshold_ms: int = Field(
        250, description="Sustained speech needed before interrupting playback."
    )


class VADSettings(BaseModel):
    provider: str = "mock"
    aggressiveness: int = Field(2, ge=0, le=3)
    silence_timeout_ms: int = Field(800, description="Silence that ends an utterance.")
    max_utterance_s: float = 20.0


class WakeWordSettings(BaseModel):
    provider: str = "mock"
    enabled: bool = True
    keywords: list[str] = Field(default_factory=lambda: ["bob", "μπομπ"])
    threshold: float = Field(0.6, ge=0.0, le=1.0)
    cooldown_ms: int = 1500


class STTSettings(BaseModel):
    provider: str = "mock"
    model: str = "large-v3"
    language: str | None = Field("el", description="None = auto-detect.")
    compute_type: str = "int8"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    beam_size: int = 5


class TTSSettings(BaseModel):
    provider: str = "mock"
    voice: str = "el_GR-default"
    speed: float = Field(1.0, gt=0.1, le=3.0)
    volume: float = Field(1.0, ge=0.0, le=1.0)


class LLMSettings(BaseModel):
    provider: str = "mock"
    model: str = "qwen2.5:14b-instruct"
    host: str = "http://localhost:11434"
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = 1024
    context_window: int = 8192
    request_timeout_s: float = 120.0
    stream: bool = True


class VisionSettings(BaseModel):
    provider: str = "mock"
    model: str = "qwen2.5vl:7b"
    enabled: bool = Field(True, description="Screenshots are taken only on explicit request.")
    max_edge_px: int = Field(1280, description="Downscale before sending to the model.")
    redact_on_capture: bool = Field(
        False, description="Reserved: blur known-sensitive windows before analysis."
    )


class MemorySettings(BaseModel):
    provider: str = "mock"
    short_term_turns: int = Field(20, description="Conversation turns kept in the working context.")
    long_term_enabled: bool = True
    autosave_conversations: bool = Field(
        False,
        description="Off by design: long-term memory is deliberate, not a transcript dump.",
    )
    max_recall_items: int = 8


class PersonalitySettings(BaseModel):
    persona: str = Field("bob", description="File stem under config/personas/.")
    humor: float = Field(0.4, ge=0.0, le=1.0)
    formality: float = Field(0.2, ge=0.0, le=1.0)
    verbosity: Literal["terse", "normal", "chatty"] = "normal"


def _default_policy() -> dict[RiskName, PolicyName]:
    """Sensible starting point: act on trivia, ask about anything that bites."""
    return {"low": "allow", "medium": "confirm", "high": "confirm"}


class SecuritySettings(BaseModel):
    """How much B.O.B. is allowed to do without asking."""

    policy: dict[RiskName, PolicyName] = Field(default_factory=_default_policy)
    confirmation_timeout_s: float = Field(
        30.0, description="Unanswered confirmations are treated as a refusal."
    )
    audit_enabled: bool = True
    redact_keys: list[str] = Field(
        default_factory=lambda: ["password", "token", "secret", "api_key", "pin"]
    )
    tool_timeout_s: float = 30.0
    blocked_tools: list[str] = Field(default_factory=list)

    @field_validator("policy")
    @classmethod
    def _high_risk_always_asks(cls, value: dict[str, str]) -> dict[str, str]:
        """HIGH risk may never be silently auto-approved via config."""
        if value.get("high") == "allow":
            raise ValueError(
                "security.policy.high cannot be 'allow'; high-risk actions must "
                "be confirmed or denied"
            )
        return value


class UISettings(BaseModel):
    theme: str = "orbit-dark"
    accent: str = "#4FD9E8"
    show_system_panel: bool = True
    show_conversation: bool = True
    animation_fps: int = Field(60, ge=15, le=144)
    reduced_motion: bool = False
    always_on_top: bool = False


class Secrets(BaseSettings):
    """Populated from the environment / ``.env`` only. Never serialised to disk.

    Cloud keys are entirely optional — B.O.B. runs fully local without them.
    """

    model_config = SettingsConfigDict(
        env_prefix="BOB_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    weather_api_key: SecretStr | None = None


class Settings(BaseModel):
    """Root settings object handed to the kernel."""

    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    vad: VADSettings = Field(default_factory=VADSettings)
    wakeword: WakeWordSettings = Field(default_factory=WakeWordSettings)
    stt: STTSettings = Field(default_factory=STTSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    personality: PersonalitySettings = Field(default_factory=PersonalitySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    ui: UISettings = Field(default_factory=UISettings)
    secrets: Secrets = Field(default_factory=Secrets)

    model_config = {"extra": "forbid"}
