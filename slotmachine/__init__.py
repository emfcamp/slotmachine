from collections import namedtuple
from dateutil import parser, relativedelta
import json
import time
import logging
import pulp


class Unsatisfiable(Exception):
    pass


class SlotMachine(object):
    Talk = namedtuple(
        "Talk",
        ("id", "duration", "venues", "speakers", "preferred_venues", "preferred_slots"),
    )
    # If preferred venues and/or slots are not specified, assume there are no preferences
    Talk.__new__.__defaults__ = ([], [])

    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.talks_by_id = {}
        self.talk_permissions = {}
        self.slots_available = set()
        self.var_cache = {}

    def start_var(self, slot, talk_id, venue):
        """A 0/1 variable that is 1 if talk with ID talk_id begins in this
        slot and venue"""
        name = "B_%d_%d_%d" % (slot, talk_id, venue)
        if name in self.var_cache:
            return self.var_cache[name]

        # Check if this talk doesn't span a period of no talks
        contiguous = True
        for slot_offset in range(0, self.talks_by_id[talk_id].duration):
            if slot + slot_offset not in self.slots_available:
                contiguous = False
                break

        # There isn't enough time left for the talk if it starts in this slot.
        if not contiguous:
            var = pulp.LpVariable(name, lowBound=0, upBound=0, cat="Integer")
        else:
            var = pulp.LpVariable(name, cat="Binary")

        self.var_cache[name] = var
        return var

    def active(self, slot, talk_id, venue):
        """A 0/1 variable that is 1 if talk with ID talk_id is active during
        this slot and venue"""
        name = "A_%d_%d_%d" % (slot, talk_id, venue)
        if name in self.var_cache:
            return self.var_cache[name]

        if (
            slot in self.talk_permissions[talk_id]["slots"]
            and venue in self.talk_permissions[talk_id]["venues"]
        ):
            variable = pulp.LpVariable(name, cat="Binary")
        else:
            variable = pulp.LpVariable(name, lowBound=0, upBound=0, cat="Integer")

        duration = self.talks_by_id[talk_id].duration
        definition = pulp.lpSum(
            self.start_var(s, talk_id, venue)
            for s in range(slot, max(-1, slot - duration), -1)
        )

        self.problem.addConstraint(variable == definition)
        self.var_cache[name] = variable
        return variable

    def get_problem(self, venues, talks, old_talks):
        # Reset problem and cached variables
        self.problem = pulp.LpProblem("Scheduler", pulp.LpMaximize)
        self.var_cache = {}

        self.talks_by_id = {talk.id: talk for talk in talks}

        # Every talk begins exactly once
        for talk in talks:
            self.problem.addConstraint(
                pulp.lpSum(
                    self.start_var(slot, talk.id, venue)
                    for venue in venues
                    for slot in self.slots_available
                )
                == 1
            )

        # At most one talk may be active in a given venue and slot.
        for v in venues:
            for slot in self.slots_available:
                self.problem.addConstraint(
                    pulp.lpSum(self.active(slot, talk.id, v) for talk in talks) <= 1
                )

        self.problem += (
            5
            * pulp.lpSum(
                # Maximise the number of things in their preferred venues (for putting big talks on big stages)
                self.active(slot, talk.id, venue)
                for talk in talks
                for venue in talk.preferred_venues
                for slot in self.slots_available
            )
            + 10
            * pulp.lpSum(
                # Try and keep everything inside its preferred time period (for packing things earlier in the day)
                self.active(slot, talk.id, venue)
                for talk in talks
                for slot in talk.preferred_slots
                for venue in venues
            )
            + 10
            * pulp.lpSum(
                # We'd like talks with a slot & venue to try and stay there if they can
                self.active(s, talk_id, venue)
                for (slot, talk_id, venue) in old_talks
                for s in range(slot, slot + self.talks_by_id[talk_id].duration)
            )
            + 5
            * pulp.lpSum(
                # And we'd prefer to just move stage rather than slot
                self.active(s, talk_id, v)
                for (slot, talk_id, _) in old_talks
                for s in range(slot, slot + self.talks_by_id[talk_id].duration)
                for v in self.talk_permissions[talk_id]["venues"]
            )
            + 1
            * pulp.lpSum(
                # But if they have to move slot, 60mins either way is ok
                self.active(s, talk_id, v)
                for (slot, talk_id, _) in old_talks
                for s in range(slot - 6, slot + self.talks_by_id[talk_id].duration + 6)
                for v in self.talk_permissions[talk_id]["venues"]
            )
        )

        talks_by_speaker = {}
        for talk in talks:
            for speaker in talk.speakers:
                talks_by_speaker.setdefault(speaker, []).append(talk.id)

        # For each talk by the same speaker it can only be active in at most one
        # talk slot at the same time.
        for conflicts in talks_by_speaker.values():
            if len(conflicts) > 1:
                for slot in self.slots_available:
                    self.problem.addConstraint(
                        pulp.lpSum(
                            self.active(slot, talk_id, venue)
                            for talk_id in conflicts
                            for venue in venues
                        )
                        <= 1
                    )
        return self.problem

    def schedule_talks(self, talks, old_talks=[]):
        start = time.time()

        self.log.info("Generating schedule problem...")

        venues = {v for talk in talks for v in talk.venues}
        problem = self.get_problem(venues, talks, old_talks)

        self.log.info(
            "Problem generated (%s variables) in %.2f seconds, attempting to solve...",
            len(self.var_cache),
            time.time() - start,
        )

        solve_start = time.time()
        # We use CBC's simplex solver rather than dual, as it is faster and the
        # accuracy difference is negligable for this problem
        # We use COIN_CMD() over COIN() as it allows us to run in parallel mode
        problem.solve(pulp.COIN_CMD(dual=0, threads=2, msg=1))

        if pulp.LpStatus[self.problem.status] != "Optimal":
            raise Unsatisfiable()

        self.log.info(
            "Problem solved in %.2f seconds. Total runtime %.2f seconds.",
            time.time() - solve_start,
            time.time() - start,
        )

        return [
            (slot, talk.id, venue)
            for slot in self.slots_available
            for talk in talks
            for venue in venues
            if pulp.value(self.start_var(slot, talk.id, venue))
        ]

    @classmethod
    def num_slots(self, start_time, end_time):
        return int((end_time - start_time).total_seconds() / 60 / 10)

    @classmethod
    def calculate_slots(self, event_start, range_start, range_end, spacing_slots=1):
        slot_start = int((range_start - event_start).total_seconds() / 60 / 10)
        # We add the number of slots that must be between events to the end to
        # allow events to finish in the last period of the schedule
        return range(
            slot_start,
            slot_start + SlotMachine.num_slots(range_start, range_end) + spacing_slots,
        )

    def calc_time(self, event_start, slots):
        return event_start + relativedelta.relativedelta(minutes=slots * 10)

    def calc_slot(self, event_start, time):
        return int((time - event_start).total_seconds() / 60 / 10)

    def schedule(self, schedule, spacing_slots=1):
        talks = []
        talk_data = {}
        old_slots = []

        event_start = min(
            parser.parse(r["start"]) for event in schedule for r in event["time_ranges"]
        )

        for event in schedule:
            talk_data[event["id"]] = event
            spacing_slots = event.get("spacing_slots", spacing_slots)
            slots = []
            preferred_slots = []

            for trange in event["time_ranges"]:
                event_slots = SlotMachine.calculate_slots(
                    event_start,
                    parser.parse(trange["start"]),
                    parser.parse(trange["end"]),
                    spacing_slots,
                )
                slots.extend(event_slots)

            for trange in event.get("preferred_time_ranges", []):
                event_slots = SlotMachine.calculate_slots(
                    event_start,
                    parser.parse(trange["start"]),
                    parser.parse(trange["end"]),
                    spacing_slots,
                )
                preferred_slots.extend(event_slots)

            self.slots_available = self.slots_available.union(set(slots))

            self.talk_permissions[event["id"]] = {
                "slots": slots,
                "venues": event["valid_venues"],
            }

            talks.append(
                self.Talk(
                    id=event["id"],
                    venues=event["valid_venues"],
                    speakers=event["speakers"],
                    # We add the number of spacing slots that must be between
                    # events to the duration
                    duration=int(event["duration"] / 10) + spacing_slots,
                    preferred_venues=event.get("preferred_venues", []),
                    preferred_slots=preferred_slots,
                )
            )

            if "time" in event and "venue" in event:
                old_slots.append(
                    (
                        self.calc_slot(event_start, parser.parse(event["time"])),
                        event["id"],
                        event["venue"],
                    )
                )

        solved = self.schedule_talks(talks, old_talks=old_slots)

        for slot_id, talk_id, venue_id in solved:
            talk_data[talk_id]["time"] = str(self.calc_time(event_start, slot_id))
            talk_data[talk_id]["venue"] = venue_id

        return list(talk_data.values())

    def schedule_from_file(self, infile, outfile):
        schedule = json.load(open(infile))

        result = self.schedule(schedule)

        with open(outfile, "w") as f:
            json.dump(result, f, sort_keys=True, indent=4, separators=(",", ": "))
