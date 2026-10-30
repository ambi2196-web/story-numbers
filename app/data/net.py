"""Polite retries for free data sources: Yahoo and others rate-limit bursts (a LinkedIn post sends many at once)."""
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
WAITS = (1.0, 3.0, 8.0)  # seconds before each retry


class SourceUnavailable(RuntimeError):
    """A data source kept failing after the retries; the UI says 'try again in a minute'."""


def retry(fn: Callable[[], T], what: str, waits: tuple[float, ...] = WAITS, sleep=time.sleep) -> T:
    """Call fn, backing off on errors (rate limits, timeouts). Raises SourceUnavailable after the last attempt."""
    for wait in (*waits, None):
        try:
            return fn()
        except Exception as exc:  # yfinance raises many types (rate limit, JSON, HTTP); all are worth one more try
            if wait is None:
                raise SourceUnavailable(f"{what} is not responding right now ({type(exc).__name__}). "
                                        "Please try again in a minute.") from exc
            sleep(wait)
    raise AssertionError("unreachable")
