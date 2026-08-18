"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base Paths
    BASE_DIR: Path = Path(__file__).resolve().parent
    DATA_DIR: Path = BASE_DIR / "data"
    PROFILE_DIR: Path = BASE_DIR / "profile"
    USER_PROFILE_PATH: Path = BASE_DIR / "user_profile.yaml"
    DATABASE_PATH: Path = BASE_DIR / "data" / "outreach.db"
    BACKUP_DIR: Path = BASE_DIR / "data" / "backups"
    LOGS_DIR: Path = BASE_DIR / "data" / "logs"
    LOG_FILE_PATH: Path = BASE_DIR / "data" / "logs" / "outreach.log"

    # LLM Provider Toggle ('openrouter' or 'groq')
    LLM_PROVIDER: str = Field(
        default="openrouter", description="LLM Provider: 'openrouter' or 'groq'"
    )

    # OpenRouter AI Gateway
    OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API Key")
    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1", description="OpenRouter Base URL"
    )
    OPENROUTER_FAST_MODEL: str = Field(
        default="deepseek/deepseek-chat", description="Fast extraction/parsing model"
    )
    OPENROUTER_SMART_MODEL: str = Field(
        default="deepseek/deepseek-chat",
        description="Smart reasoning & drafting model",
    )

    # Groq AI Gateway
    GROQ_API_KEY: Optional[str] = Field(default=None, description="Groq API Key")
    GROQ_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1", description="Groq Base URL"
    )
    GROQ_FAST_MODEL: str = Field(
        default="llama-3.1-8b-instant", description="Groq fast model"
    )
    GROQ_SMART_MODEL: str = Field(
        default="llama-3.3-70b-versatile", description="Groq smart model"
    )

    # Search & Enrichment APIs
    TAVILY_API_KEY: str = Field(default="", description="Tavily Search API Key")
    HUNTER_API_KEY: Optional[str] = Field(default=None, description="Hunter.io API Key")
    APOLLO_API_KEY: Optional[str] = Field(default=None, description="Apollo API Key")

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot Token")
    TELEGRAM_CHAT_ID: str = Field(
        default="", description="Authorized Telegram Chat ID"
    )

    # Email & SMTP
    GMAIL_USER: str = Field(default="", description="Sender Gmail address")
    GMAIL_APP_PASSWORD: str = Field(
        default="", description="16-character Google App Password"
    )
    SMTP_HOST: str = Field(default="smtp.gmail.com", description="SMTP server host")
    SMTP_PORT: int = Field(default=587, description="SMTP server port (587 for TLS)")

    # System Controls
    MIN_FIT_SCORE: int = Field(
        default=75, ge=0, le=100, description="Minimum score to trigger drafting"
    )
    MAX_ALERTS_PER_DAY: int = Field(
        default=10, ge=1, le=50, description="Daily limit for Telegram cards"
    )
    DRY_RUN: bool = Field(
        default=True,
        description="If True, simulates email delivery without dispatching real emails",
    )

    # Oracle Cloud Anti-Idle Heartbeat
    ORACLE_HEARTBEAT_ENABLED: bool = Field(
        default=True, description="Enable periodic anti-idle compute pulse"
    )
    HEARTBEAT_INTERVAL_HOURS: int = Field(
        default=4, ge=1, le=24, description="Hours between heartbeat pulses"
    )

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    def ensure_directories(self) -> None:
        """Ensure all required runtime directories exist."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self.BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# Global settings singleton
settings = Settings()
settings.ensure_directories()
