"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All settings via environment variables; same image for dev/prod."""

    LOG_LEVEL: str = "INFO"
    TZ: str = "America/Chicago"  # used for quiet-hours evaluation and {time} placeholder

    DATABASE_URL: str = "sqlite:///./data/watchdog.db"

    # AMP ADS panel + read-only service account
    AMP_BASE_URL: str = "http://10.0.1.52:8080"
    AMP_USERNAME: str = "status-reader"
    AMP_PASSWORD: str = ""

    # Seconds between due-watch sweeps; per-watch intervals live in the DB
    SCHEDULER_TICK: int = 5
    DEFAULT_CHECK_INTERVAL: int = 60

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
