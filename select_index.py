"""Select an evaluated local snapshot, or restore the untouched baseline."""
import argparse
from pathlib import Path
from src.index_selection import activate, rollback


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate", type=Path)
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        rollback()
        print("Original index selected; no index files deleted.")
    else:
        activate(args.candidate)
        print("Evaluated candidate selected; original index retained for rollback.")
