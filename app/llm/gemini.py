"""Google Gemini via the free-tier API. Used for the public (LinkedIn) deployment.

GEMINI_MODEL may be a comma-separated fallback chain, e.g. "gemini-flash-latest,gemini-3.5-flash".
Overloaded (5xx) models are retried briefly; overloaded or rate-limited models fall through to the next one,
since each free-tier model has its own quota.
"""
import time

from google import genai
from google.genai import errors, types

from app.llm.base import LLMError, LLMProvider

RETRY_WAITS = (2, 5)  # seconds between attempts on the same model when it is overloaded


class QuotaExceeded(LLMError):
    """The free-tier rate or daily limit was hit; the UI shows a friendly message for this."""


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash,gemini-flash-latest,gemini-flash-lite-latest"):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey")
        # Our own retry/fallback loop is used instead of the SDK's, and every request is capped so the UI never hangs.
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=45_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.last_model: str | None = None

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
            temperature=0.4,
        )
        failures = []
        for model in self.models:
            for wait in (*RETRY_WAITS, None):
                try:
                    response = self.client.models.generate_content(model=model, contents=prompt, config=config)
                    self.last_model = model
                    return response.text or ""
                except errors.APIError as exc:
                    failures.append(f"{model}: {exc.code}")
                    # Only a quick 503 "overloaded" is worth retrying on the same model; a 504 already cost a timeout.
                    if exc.code != 503 or wait is None:
                        if (exc.code or 0) < 500 and exc.code not in (404, 429):
                            raise LLMError(f"Gemini error {exc.code}: {exc.message}") from exc
                        break  # quota hit, model retired, or still overloaded: try the next model
                    time.sleep(wait)
        if all(f.endswith("429") for f in failures):
            raise QuotaExceeded("The free Gemini allowance is used up for now. Try again later or add your own key.")
        raise LLMError(f"Gemini is busy right now, please try again shortly ({', '.join(failures)})")

    def list_models(self) -> list[str]:
        return [m.name for m in self.client.models.list() if "generateContent" in (m.supported_actions or [])]
