"""Pick an LLM backend: Claude CLI for personal/local use, Gemini for the public deployment."""
from app.config import settings
from app.llm.base import LLMError, LLMProvider, extract_json
from app.llm.claude_cli import ClaudeCLIProvider, claude_cli_path
from app.llm.gemini import GeminiProvider, QuotaExceeded

__all__ = ["LLMError", "LLMProvider", "QuotaExceeded", "extract_json", "get_provider", "available_providers"]


def available_providers() -> list[str]:
    found = []
    if claude_cli_path():
        found.append("claude_cli")
    if settings.gemini_api_key:
        found.append("gemini")
    return found


def get_provider(name: str | None = None, gemini_api_key: str | None = None, allow_web: bool = False) -> LLMProvider:
    """Build a provider. `gemini_api_key` lets a visitor bring their own key for one session."""
    name = (name or settings.llm_provider).lower()
    if name == "auto":
        name = "claude_cli" if claude_cli_path() else "gemini"
    if name == "claude_cli":
        return ClaudeCLIProvider(settings.claude_model, settings.claude_timeout, allow_web=allow_web)
    if name == "gemini":
        return GeminiProvider(gemini_api_key or settings.gemini_api_key, settings.gemini_model)
    raise LLMError(f"Unknown LLM_PROVIDER '{name}'. Use auto, claude_cli or gemini.")
