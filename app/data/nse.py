"""NSE's official list of listed equities, used for search suggestions with the names NSE itself uses.

NSE's live search API blocks scripts, but its equity master file (EQUITY_L.csv) is public. It is downloaded
once a week and searched locally, so suggestions are instant.
"""
import difflib
import re
import time
from io import StringIO

import httpx
import pandas as pd

from app.config import DATA_DIR

URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
PATH = DATA_DIR / "cache" / "nse_equity.csv"
SEED = DATA_DIR / "nse_equity_seed.csv"  # committed copy: NSE often blocks servers outside India (cloud hosts)
MAX_AGE_DAYS = 7
_NOISE = {"limited", "ltd", "ltd.", "india", "the", "of", "and", "&"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def equities() -> pd.DataFrame:
    """SYMBOL, NAME columns for every NSE-listed equity (refreshed weekly; a stale copy is used if NSE is down)."""
    fresh = PATH.exists() and time.time() - PATH.stat().st_mtime < MAX_AGE_DAYS * 86400
    if not fresh:
        try:
            r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            pd.read_csv(StringIO(r.text))  # make sure it parses before replacing the cached copy
            PATH.parent.mkdir(parents=True, exist_ok=True)
            PATH.write_text(r.text, encoding="utf-8")
        except (httpx.HTTPError, pd.errors.ParserError):
            if not PATH.exists() and not SEED.exists():
                return pd.DataFrame(columns=["SYMBOL", "NAME"])
    df = pd.read_csv(PATH if PATH.exists() else SEED)
    df.columns = [c.strip() for c in df.columns]
    return df.rename(columns={"NAME OF COMPANY": "NAME"})[["SYMBOL", "NAME"]]


def search(query: str, limit: int = 6) -> list[dict]:
    """NSE equities matching a name or symbol, best first: exact symbol, name prefix, all words, then fuzzy."""
    q = query.strip().removesuffix(".NS").removesuffix(".ns")
    if not q:
        return []
    qwords = [w for w in _words(q) if w not in _NOISE] or _words(q)
    scored = []
    for symbol, name in equities().itertuples(index=False):
        words = _words(name)
        if symbol.upper() == q.upper().replace(" ", ""):
            score = 0
        elif name.lower().startswith(q.lower()):
            score = 1
        elif all(any(w.startswith(qw) for w in words) for qw in qwords):
            score = 2
        elif symbol.upper().startswith(q.upper().replace(" ", "")):
            score = 3
        else:
            continue
        scored.append((score, len(name), symbol, name))
    if not scored:  # typos: "Marti Suzki"
        names = equities()
        close = set(difflib.get_close_matches(q.lower(), names["NAME"].str.lower(), n=limit, cutoff=0.6))
        scored = [(4, len(n), s, n) for s, n in names.itertuples(index=False) if n.lower() in close]
    return [{"symbol": f"{s}.NS", "name": n, "exchange": "NSE"} for *_, s, n in sorted(scored)[:limit]]
