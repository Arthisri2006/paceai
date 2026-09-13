"""Simple command-line backend check, independent of the future UI."""

from __future__ import annotations

import argparse
import json

from src.runtime import load_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the local PACE AI backend")
    parser.add_argument("question")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    response = load_pipeline().ask(args.question)
    print(response["answer"])
    if args.debug:
        print("\nDebug timing:")
        print(json.dumps(response["timing"], indent=2))


if __name__ == "__main__":
    main()
