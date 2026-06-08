"""Configuration management — pydantic-settings with .env support."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file.

    All values have sensible defaults; secrets (api_key) must be provided
    via environment variable or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- LLM -----------------------------------------------------------
    api_key: str = ""
    base_url: str = "https://api.xiaomimimo.com/v1"
    model: str = "mimo-v2.5-pro"
    temperature: float = 0.7
    max_tokens: int = 4096

    # -- Agent ---------------------------------------------------------
    max_steps: int = 10

    # -- Context compression -------------------------------------------
    compression_enabled: bool = True
    compression_trigger_fraction: float = 0.7  # 70% of model max
    compression_keep_messages: int = 20        # keep recent N messages
    model_max_input_tokens: int = 32768        # MiMo v2.5 context window

    # -- Paths ---------------------------------------------------------
    data_dir: str = ""
    sessions_dir: str = ""
    logs_dir: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.data_dir:
            self.data_dir = str(
                Path(__file__).resolve().parent.parent / "data"
            )
        if not self.sessions_dir:
            self.sessions_dir = str(Path(self.data_dir) / "sessions")
        if not self.logs_dir:
            self.logs_dir = str(Path(self.data_dir) / "logs")
        # Ensure directories exist
        Path(self.sessions_dir).mkdir(parents=True, exist_ok=True)
        Path(self.logs_dir).mkdir(parents=True, exist_ok=True)

    @property
    def compression_trigger_tokens(self) -> int:
        """Token count at which compression should trigger."""
        return int(self.model_max_input_tokens * self.compression_trigger_fraction)


# ------------------------------------------------------------------
# singleton
# ------------------------------------------------------------------

_settings: Settings | None = None


def get_config() -> Settings:
    """Return the global Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
