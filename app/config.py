"""Central settings, read from environment variables and the local .env file."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    claude_model: str = os.getenv("CLAUDE_MODEL", "sonnet")
    claude_timeout: int = int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "180"))
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash,gemini-flash-latest,gemini-flash-lite-latest")


settings = Settings()
