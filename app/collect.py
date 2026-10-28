"""Command line: python -m app.collect "Maruti Suzuki" [--refresh]  ->  output/<TICKER>_<date>.xlsx"""
import argparse
from datetime import date

from app.config import ROOT
from app.data.collector import collect
from app.excel.workbook import build
from app.llm import get_provider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("company")
    parser.add_argument("--refresh", action="store_true", help="ignore the 24h cache")
    args = parser.parse_args()

    # The LLM is only consulted when Yahoo search finds nothing (e.g. renamed companies: Zomato -> Eternal).
    company = collect(args.company, refresh=args.refresh, llm=get_provider())
    out = ROOT / "output" / f"{company.profile['symbol']}_{date.today():%Y-%m-%d}.xlsx"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(build(company))
    print(f"{company.profile['name']} ({company.profile['symbol']}): "
          f"{', '.join(company.financials.columns)} from {company.profile['source']}")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
