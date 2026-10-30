"""Featured companies: AI business profiles built ahead of time and committed to the repo, so on the public
app the first click on a featured company is instant and costs no AI call (section 3.2.1 of the roadmap).

    python -m app.featured build      # (re)build every featured profile with the configured AI
    python -m app.featured list
"""
import json
import sys

from app.config import DATA_DIR

FEATURED_DIR = DATA_DIR / "featured"
FEATURED = {"MARUTI.NS": "Maruti Suzuki", "TMPV.NS": "Tata Motors Passenger Vehicles", "ETERNAL.NS": "Eternal",
            "PAYTM.NS": "Paytm", "INFY.NS": "Infosys", "AAPL": "Apple", "NESTLEIND.NS": "Nestlé India",
            "TSLA": "Tesla"}


def _path(symbol: str):
    return FEATURED_DIR / f"{symbol.replace('.', '_')}.json"


def featured_profile(symbol: str) -> dict | None:
    path = _path(symbol)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build(refresh: bool = False) -> None:
    from app.data.collector import collect
    from app.llm import get_provider
    from app.story.profile import build_profile

    llm = get_provider()
    FEATURED_DIR.mkdir(parents=True, exist_ok=True)
    for symbol, name in FEATURED.items():
        if _path(symbol).exists() and not refresh:
            print(f"skip  {name} (already built)")
            continue
        try:
            profile = build_profile(collect(symbol), llm, refresh=refresh)
        except Exception as exc:  # one bad company should not stop the rest
            print(f"FAIL  {name}: {exc}")
            continue
        _path(symbol).write_text(json.dumps(profile.model_dump(), indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"built {name} -> {profile.damodaran_industry}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["build"]:
        build(refresh="--refresh" in sys.argv)
    else:
        for symbol, name in FEATURED.items():
            print(f"{'✓' if _path(symbol).exists() else ' '} {symbol:14} {name}")
