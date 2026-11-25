# Search queries, target cities, blocked keywords, env loader
from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Multi-tier LLM API Keys
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None

    # Pipeline Behavior
    DB_PATH: str = "data/jobs.db"
    RESUME_PATH: str = "config/resume.txt"
    MAX_JOB_AGE_HOURS: int = 24
    MIN_NOTIFY_SCORE: int = 75
    MAX_JD_TOKENS: int = 3000  # Prevents 413 Payload Too Large errors

    # Optional Notifications (Telegram / Discord / Email)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None

    def load_resume(self) -> str:
        path = Path(self.RESUME_PATH)
        if not path.exists():
            raise FileNotFoundError(f"Resume file not found at {self.RESUME_PATH}")
        return path.read_text(encoding="utf-8").strip()


@lru_cache()
def get_settings() -> Settings:
    return Settings()