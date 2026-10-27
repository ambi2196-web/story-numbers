"""Provider-agnostic LLM interface.

The LLM is only ever asked for language work (story -> assumptions, numbers -> narrative).
All valuation math lives in app.engine, never in a prompt.
"""
import json
import re
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when a provider fails or cannot return valid output."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        """Return the model's raw text reply."""

    def complete_json(self, prompt: str, schema: type[T], system: str | None = None, retries: int = 1) -> T:
        """Ask for JSON matching `schema`, validate it, and retry once with the error if it does not fit."""
        schema_text = json.dumps(schema.model_json_schema(), indent=2)
        request = (
            f"{prompt}\n\nReply with ONLY a JSON object that matches this JSON schema. "
            f"No prose, no markdown fences.\n{schema_text}"
        )
        last_error = ""
        for _ in range(retries + 1):
            text = self.complete(request if not last_error else f"{request}\n\nYour previous reply was invalid: {last_error}",
                                 system=system, json_mode=True)
            try:
                return schema.model_validate(extract_json(text))
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:1000]
        raise LLMError(f"{self.name} did not return valid {schema.__name__} JSON: {last_error}")


def extract_json(text: str):
    """Parse the first JSON object or array in `text`, tolerating markdown fences and surrounding prose."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in reply")
    start = min(starts)
    end = text.rfind("}" if text[start] == "{" else "]")
    if end < start:
        raise ValueError("unterminated JSON in reply")
    return json.loads(text[start : end + 1])
