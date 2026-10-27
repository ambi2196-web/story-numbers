import pytest
from pydantic import BaseModel

from app.llm.base import LLMError, LLMProvider, extract_json


class Drivers(BaseModel):
    market_share: float
    ev_mix: float


class ScriptedLLM(LLMProvider):
    """Returns canned replies in order, so JSON handling is tested without any network call."""
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt, system=None, json_mode=False):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_extract_json_handles_fences_and_prose():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```\nDone.') == {"a": 1}
    assert extract_json("[1, 2]") == [1, 2]
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_complete_json_validates():
    llm = ScriptedLLM(['{"market_share": 0.7, "ev_mix": 0.8}'])
    assert llm.complete_json("story", Drivers) == Drivers(market_share=0.7, ev_mix=0.8)


def test_complete_json_retries_with_error_then_succeeds():
    llm = ScriptedLLM(['{"market_share": "lots"}', '{"market_share": 0.7, "ev_mix": 0.8}'])
    assert llm.complete_json("story", Drivers).ev_mix == 0.8
    assert "previous reply was invalid" in llm.prompts[1]


def test_complete_json_gives_up():
    llm = ScriptedLLM(["nope", "still nope"])
    with pytest.raises(LLMError):
        llm.complete_json("story", Drivers)
