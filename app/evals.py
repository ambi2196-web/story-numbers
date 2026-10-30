"""Prompt evaluation: 20 stories with expected driver ranges, run against one AI provider.

    python -m app.evals --provider claude_cli
    python -m app.evals --provider gemini --only maruti-70-ev,apple-services

Each story goes through Mode A (story -> drivers) exactly as in the app. A story passes when every expected
driver falls in its range, every number the story states is tagged 'stated', and any extra checks hold (a
product-mix share, a flat market share, at least one red flag). Results go to evals/results_<provider>.csv.
"""
import argparse
import json
import time

import pandas as pd

from app.config import ROOT
from app.data.collector import collect
from app.engine.defaults import status_quo
from app.llm import LLMError, get_provider
from app.story import story_numbers as sn
from app.story.profile import apply_industry, cached_profile

EVAL_DIR = ROOT / "evals"


def check(case: dict, d: sn.StoryDrivers) -> list[str]:
    """The failed checks for one story (empty = pass)."""
    fails = []
    for key, (lo, hi) in case.get("expect", {}).items():
        x = getattr(d, key).value
        if not lo <= x <= hi:
            fails.append(f"{key} {x:.4g} not in [{lo:g}, {hi:g}]")
    for key in case.get("stated", []):
        if getattr(d, key).source != "stated":
            fails.append(f"{key} not tagged stated")
    if rng := case.get("mix_share"):
        if not any(rng[0] <= m.share_of_units <= rng[1] for m in d.mix):
            fails.append(f"no mix item with share in {rng}")
    if case.get("share_flat") and abs(d.target_share.value - d.current_share.value) > 0.03:
        fails.append(f"share moved {d.current_share.value:.0%} -> {d.target_share.value:.0%}")
    if len(d.red_flags) < case.get("min_red_flags", 0):
        fails.append("no red flags")
    return fails


def run(provider: str, only: list[str] | None = None, pause: float = 0.0) -> pd.DataFrame:
    cases = json.loads((EVAL_DIR / "stories.json").read_text(encoding="utf-8"))
    cases = [c for c in cases if not only or c["id"] in only]
    llm = get_provider(provider)
    rows, companies = [], {}
    for case in cases:
        t = time.time()
        try:
            if case["symbol"] not in companies:
                company = collect(case["symbol"])
                if profile := cached_profile(case["symbol"], llm.name):
                    apply_industry(company, profile)
                companies[case["symbol"]] = (company, status_quo(company), profile)
            company, setup, profile = companies[case["symbol"]]
            d = sn.draft(company, setup, case["story"], llm, profile)
            fails = check(case, d)
            detail = "; ".join(fails) or "all checks pass"
        except (LLMError, ValueError) as exc:
            fails, detail = ["error"], f"{type(exc).__name__}: {str(exc)[:120]}"
        rows.append({"id": case["id"], "pass": not fails, "seconds": round(time.time() - t), "detail": detail})
        print(f"{'PASS' if not fails else 'FAIL'} {case['id']:20} {rows[-1]['seconds']:>4}s  {detail}", flush=True)
        if pause:
            time.sleep(pause)
    df = pd.DataFrame(rows)
    df.to_csv(EVAL_DIR / f"results_{llm.name}.csv", index=False)
    print(f"\n{llm.name}: {int(df['pass'].sum())}/{len(df)} stories pass")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds between stories (free-tier rate limits)")
    args = ap.parse_args()
    run(args.provider, [x for x in args.only.split(",") if x] or None, args.pause)
