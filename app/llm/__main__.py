"""Smoke test: python -m app.llm [--provider claude_cli|gemini] [--list-models] "prompt" """
import argparse

from pydantic import BaseModel

from app.llm import available_providers, get_provider


class Ping(BaseModel):
    company: str
    ticker: str
    country: str


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="?", default="Say hello in five words.")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--json", action="store_true", help="also run a structured-JSON test")
    parser.add_argument("--list-models", action="store_true", help="Gemini only: list usable models")
    args = parser.parse_args()

    print("available:", available_providers())
    llm = get_provider(args.provider)
    print("using:", llm.name)
    if args.list_models:
        print("\n".join(llm.list_models()))
        return
    print(llm.complete(args.prompt))
    if args.json:
        print(llm.complete_json("Identify the listed company 'Maruti Suzuki' and its Yahoo Finance ticker.", Ping))


if __name__ == "__main__":
    main()
