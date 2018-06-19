from collections import namedtuple
from functools import wraps
from dateutil import parser, relativedelta
import json
import pulp


class Unsatisfiable(Exception):
    pass


def cached(function):
    cache = {}

    @wraps(function)
    def accept(*args):
        args = tuple(args)
        try:
            return cache[args]
        except KeyError:
            pass
        result = function(*args)
        cache[args] = result
        return result
    return accept


class SlotMachine(object):
    Talk = namedtuple('Talk', ('id', 'duration', 'venues', 'speakers'))

    def __init__(self):
        self.talks_by_id = {}
        self.talk_permissions = {}
        self.names_to_basics = {}
        self.slots_available = set()
        self.problem = pulp.LpProblem("Scheduler", pulp.LpMaximize)

    @cached
    def basic(self, slot, talk_id, venue):
        """A 0/1 variable that is 1 if talk with ID talk_id begins in this
        slot and venue"""
        name = "B_%d_%d_%d" % (slot, talk_id, venue)

        # Check if this talk doesn't span a period of no talks
        contiguous = True
        for slot_offset in range(0, self.talks_by_id[talk_id].duration):
            if slot + slot_offset not in self.slots_available:
                contiguous = False
                break

        # There isn't enough time left for the talk if it starts in this slot.
        if not contiguous:
            self.names_to_basics[name] = pulp.LpVariable(name, lowBound=0, upBound=0, cat='Integer')
        else:
            self.names_to_basics[name] = pulp.LpVariable(name, cat='Binary')

        return self.names_to_basics[name]

    @cached
    def active(self, slot, talk_id, venue):
        """A 0/1 variable that is 1 if talk with ID talk_id is active during
        this slot and venue"""
        name = "A_%d_%d_%d" % (slot, talk_id, venue)

        if (slot in self.talk_permissions[talk_id]['slots'] and
                venue in self.talk_permissions[talk_id]['venues']):
            variable = pulp.LpVariable(name, cat='Binary')
        else:
            variable = pulp.LpVariable(name, lowBound=0, upBound=0, cat='Integer')

        duration = self.talks_by_id[talk_id].duration
        definition = sum(
            self.basic(s, talk_id, venue)
            for s in range(slot, max(-1, slot - duration), -1)
        )

        self.problem.addConstraint(variable == definition)
        return variable

    def schedule_talks(self, talks, old_talks=[]):
        def allowed(slot, talk, venue):
            if (slot in self.talk_permissions[talk]['slots'] and
                    venue in self.talk_permissions[talk]['venues']):
                return True
            return False

        venues = {
            v for talk in talks for v in talk.venues
        }

        self.talks_by_id = {talk.id: talk for talk in talks}

        # Every talk begins exactly once
        for talk in talks:
            self.problem.addConstraint(
                pulp.lpSum(
                    self.basic(slot, talk.id, venue)
                    for venue in venues
                    for slot in self.slots_available
                ) == 1
            )

        # At most one talk may be active in a given venue and slot.
        for v in venues:
            for slot in self.slots_available:
                self.problem.addConstraint(
                    pulp.lpSum(
                        self.active(slot, talk.id, v)
                        for talk in talks
                    ) <= 1
                )

        # We'd like talks with a slot & venue to try and stay there if they can
        self.problem += (10 * pulp.lpSum(
            self.active(s, talk_id, venue)
            for (slot, talk_id, venue) in old_talks
            for s in range(slot, slot + self.talks_by_id[talk_id].duration)
            # And we'd prefer to just move stage rather than slot
        )) + (5 * pulp.lpSum(
            self.active(s, talk_id, v)
            for (slot, talk_id, _) in old_talks
            for s in range(slot, slot + self.talks_by_id[talk_id].duration)
            for v in self.talk_permissions[talk_id]['venues']
            # But if they have to move slot, 60mins either way is ok
        )) + pulp.lpSum(
            self.active(s, talk_id, v)
            for (slot, talk_id, _) in old_talks
            for s in range(slot - 6, slot + self.talks_by_id[talk_id].duration + 6)
            for v in self.talk_permissions[talk_id]['venues']
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
                        ) <= 1
                    )

        self.problem.solve(pulp.GLPK())

        if pulp.LpStatus[self.problem.status] != 'Optimal':
            raise Unsatisfiable()

        return [
            (slot, talk.id, venue)
            for slot in self.slots_available
            for talk in talks
            for venue in venues
            if pulp.value(self.basic(slot, talk.id, venue))
        ]

    @classmethod
    def num_slots(self, start_time, end_time):
        return int((parser.parse(end_time) - parser.parse(start_time)).total_seconds() / 60 / 10)

    @classmethod
    def calculate_slots(self, event_start, range_start, range_end):
        slot_start = int((parser.parse(range_start) - parser.parse(event_start)).total_seconds() / 60 / 10)
        # We add one to allow the talk to finish in the last slot of this period,
        # as we force a single-slot changeover
        return range(slot_start, slot_start + SlotMachine.num_slots(range_start, range_end) + 1)

    def calc_time(self, event_start, slots):
        return (parser.parse(event_start) + relativedelta.relativedelta(minutes=slots * 10))

    def calc_slot(self, event_start, time):
        return int((parser.parse(time) - parser.parse(event_start)).total_seconds() / 60 / 10)

    def schedule(self, event_start, schedule):
        talks = []
        talk_data = {}
        old_slots = []

        for event in schedule:
            talk_data[event['id']] = event
            slots = []

            for trange in event['time_ranges']:
                event_slots = SlotMachine.calculate_slots(event_start, trange['start'], trange['end'])
                slots.extend(event_slots)

            self.slots_available = self.slots_available.union(set(slots))

            self.talk_permissions[event['id']] = {
                'slots': slots,
                'venues': event['valid_venues']
            }

            talks.append(
                self.Talk(
                    id=event['id'],
                    venues=event['valid_venues'],
                    speakers=event['speakers'],
                    # We add one slot to allow for a single-slot changeover period
                    duration=int(event['duration'] / 10) + 1
                )
            )

            if 'time' in event and 'venue' in event:
                old_slots.append((self.calc_slot(event_start, event['time']), event['id'], event['venue']))

        solved = self.schedule_talks(talks, old_talks=old_slots)

        for slot_id, talk_id, venue_id in solved:
            talk_data[talk_id]['time'] = str(self.calc_time(event_start, slot_id))
            talk_data[talk_id]['venue'] = venue_id

        return talk_data.values()

    def schedule_from_file(self, event_start, infile, outfile):
        schedule = json.load(open(infile))

        result = self.schedule(event_start, schedule)

        with open(outfile, 'w') as f:
            json.dump(result, f, sort_keys=True, indent=4, separators=(',', ': '))
