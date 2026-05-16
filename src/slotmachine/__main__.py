import argparse
import json
import logging
import sys

from slotmachine import SlotMachine
from slotmachine.data import SchedulingProblem


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Run slotmachine against a json schedule")
    ap.add_argument("infile", help="Input file")
    ap.add_argument("outfile", nargs="?", help="Output file (default: stdout)")
    ap.add_argument("-n", "--no-output", action="store_true", help="Suppress output")
    ap.add_argument("-d", "--debug", action="store_true", help="Show solver debug output")
    args = ap.parse_args()

    with open(args.infile) as f:
        problem = SchedulingProblem.from_dict(json.load(f))

    result = SlotMachine(problem).solve(debug=args.debug)

    if not args.no_output:
        if args.outfile:
            with open(args.outfile, "w") as f:
                json.dump(result.to_dict(), f, sort_keys=True, indent=4, separators=(",", ": "))
        else:
            json.dump(result.to_dict(), sys.stdout, sort_keys=True, indent=4, separators=(",", ": "))


if __name__ == "__main__":
    sys.exit(main())
