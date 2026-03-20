import argparse
import json
import sys

from slotmachine import SlotMachine

def main():
    ap = argparse.ArgumentParser(description="Run slotmachine against a json schedule")
    ap.add_argument("infile", help="Input file")
    ap.add_argument("outfile", nargs="?", help="Output file (default: stdout)")
    ap.add_argument("-n", "--no-output", action="store_true", help="Suppress output")
    args = ap.parse_args()

    with open(args.infile) as f:
        schedule = json.load(f)

    result = SlotMachine().schedule(schedule)

    if not args.no_output:
        f = sys.stdout
        if args.outfile:
            f = open(args.outfile, "w")
        json.dump(result, f, sort_keys=True, indent=4, separators=(",", ": "))
        f.close()

if __name__ == "__main__":
    sys.exit(main())
