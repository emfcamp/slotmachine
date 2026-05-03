import argparse
import json
import logging
import sys
from datetime import datetime

from dateutil.parser import parse as parse_datetime

from slotmachine import SlotMachine
from slotmachine.data import SchedulingProblem, Talk


def parse_time_range(range: dict) -> tuple[datetime, datetime]:
    return (parse_datetime(range["start"]), parse_datetime(range["end"]))


def talk_from_json(talk: dict) -> Talk:
    return Talk(
        id=talk["id"],
        duration=talk["duration"],
        speakers=set(talk["speakers"]),
        allowed_venues=set(talk["valid_venues"]),
        preferred_venues=set(talk.get("preferred_venues", [])),
        allowed_times=[parse_time_range(r) for r in talk["time_ranges"]],
        preferred_times=[parse_time_range(r) for r in talk.get("preferred_times", [])],
        minutes_after=10,
        start_time=parse_datetime(talk.get("time", "")) if talk.get("time") else None,
        venue=talk.get("venue"),
    )


def problem_from_json(schedule: dict) -> SchedulingProblem:
    talks = []
    for talk_data in schedule:
        talks.append(talk_from_json(talk_data))
    return SchedulingProblem(talks=talks, slot_duration=10)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Run slotmachine against a json schedule")
    ap.add_argument("infile", help="Input file")
    ap.add_argument("outfile", nargs="?", help="Output file (default: stdout)")
    ap.add_argument("-n", "--no-output", action="store_true", help="Suppress output")
    ap.add_argument("-d", "--debug", action="store_true", help="Show solver debug output")
    args = ap.parse_args()

    with open(args.infile) as f:
        problem = problem_from_json(json.load(f))

    result = SlotMachine(problem).solve(debug=args.debug)

    if not args.no_output:
        if args.outfile:
            with open(args.outfile, "w") as f:
                json.dump(result.to_dict(), f, sort_keys=True, indent=4, separators=(",", ": "))
        else:
            json.dump(result.to_dict(), sys.stdout, sort_keys=True, indent=4, separators=(",", ": "))


if __name__ == "__main__":
    sys.exit(main())
