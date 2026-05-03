import unittest
from datetime import timedelta
from itertools import permutations

from dateutil.parser import parse as ts

from slotmachine import SlotMachine, Talk, Unsatisfiable
from slotmachine.data import SchedulingProblem, SchedulingSolution, TimeRange


def time_overlaps(range1: TimeRange, range2: TimeRange) -> bool:
    latest_start = max(range1[0], range2[0])
    earliest_end = min(range1[1], range2[1])
    delta = (earliest_end - latest_start).total_seconds()
    return delta > 0


class ScheduleTalksTestCase(unittest.TestCase):
    def schedule_and_basic_asserts(self, talks: list[Talk]) -> SchedulingSolution:
        sm = SlotMachine(SchedulingProblem(talks=talks, slot_duration=10))
        solution = sm.solve()

        # All talks must be represented
        self.assertEqual(set(talk.id for talk in talks), set(talk.id for talk in solution.talks))

        # All time/venue tuples must be different
        slot_venues = [(talk.venue, talk.start_time) for talk in solution.talks]
        self.assertEqual(sorted(set(slot_venues)), sorted(slot_venues))

        # Venue must be allowed
        for talk in solution.talks:
            assert talk.venue in talk.allowed_venues

        # Talks must not overlap
        for a, b in permutations(solution.talks, 2):
            assert a.start_time
            assert b.start_time
            if a.venue == b.venue:
                assert not time_overlaps(
                    (a.start_time, a.start_time + timedelta(minutes=a.duration)),
                    (b.start_time, b.start_time + timedelta(minutes=b.duration)),
                )

        return solution

    def schedule_and_assert_fails(self, talks: list[Talk]):
        sm = SlotMachine(SchedulingProblem(talks=talks, slot_duration=10))

        with self.assertRaises(Unsatisfiable):
            sm.solve()

    def test_simple(self):
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
        talk_defs = [
            Talk(
                id=1,
                duration=30,
                allowed_venues={101},
                speakers={1},
                allowed_times=allowed_times,
            ),
            Talk(
                id=2,
                duration=30,
                allowed_venues={101},
                speakers={2},
                allowed_times=allowed_times,
            ),
            Talk(
                id=3,
                duration=30,
                allowed_venues={101},
                speakers={3},
                allowed_times=allowed_times,
            ),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs)

        # Solution should be stable
        solved_second = self.schedule_and_basic_asserts(solved.talks)
        self.assertEqual(solved, solved_second)

    def test_too_many_talks(self):
        # This should just exceed the number of available slots (12 + 1)
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
        talk_defs = [
            Talk(id=1, duration=40, allowed_venues={101}, speakers={1}, allowed_times=allowed_times),
            Talk(id=2, duration=40, allowed_venues={101}, speakers={2}, allowed_times=allowed_times),
            Talk(id=3, duration=30, allowed_venues={101}, speakers={3}, allowed_times=allowed_times),
        ]

        self.schedule_and_assert_fails(talk_defs)

    def test_two_venues(self):
        # talk 3 should end up in venue 102
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 14:00"))]
        talk_defs = [
            Talk(id=1, duration=50, allowed_venues={101}, speakers={1}, allowed_times=allowed_times),
            Talk(id=2, duration=20, allowed_venues={102}, speakers={2}, allowed_times=allowed_times),
            Talk(id=3, duration=20, allowed_venues={101, 102}, speakers={3}, allowed_times=allowed_times),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs)

        for talk in solved.talks:
            if talk.id == 3:
                assert talk.venue == 102

    def test_venue_too_full(self):
        # Talks 1 and 3 won't fit into 101 together, and 3 and 4 won't fit in 102 together
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
        talk_defs = [
            Talk(id=1, duration=70, allowed_venues={101}, speakers={1}, allowed_times=allowed_times),
            Talk(id=2, duration=40, allowed_venues={101, 102}, speakers={2}, allowed_times=allowed_times),
            Talk(id=3, duration=50, allowed_venues={101, 102}, speakers={3}, allowed_times=allowed_times),
            Talk(id=4, duration=70, allowed_venues={102}, speakers={4}, allowed_times=allowed_times),
        ]

        self.schedule_and_assert_fails(talk_defs)

    def test_venue_clash(self):
        # Talks 2 and 3 must move to accommodate talk 4
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
        talk_defs = [
            Talk(
                id=1,
                duration=70,
                allowed_venues={101},
                speakers={1},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 13:00"),
                venue=101,
            ),
            Talk(
                id=2,
                duration=40,
                allowed_venues={101, 102},
                speakers={2},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 13:20"),
                venue=102,
            ),
            Talk(
                id=3,
                duration=40,
                allowed_venues={101, 102},
                speakers={3},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 14:10"),
                venue=102,
            ),
            Talk(id=4, duration=70, allowed_venues={102}, speakers={4}, allowed_times=allowed_times),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs)

        for talk in solved.talks:
            if talk.id == 1:
                # Talk 1 shouldn't move
                assert talk.venue == 101
                assert talk.start_time == ts("2016-08-06 13:00")

    def test_speaker_clash(self):
        # Talk 4 is by Speaker 1
        # Either talk 2 or 3 will have to move
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
        talk_defs = [
            Talk(
                id=1,
                duration=70,
                allowed_venues={101},
                speakers={1},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 13:00"),
                venue=101,
            ),
            Talk(
                id=2,
                duration=70,
                allowed_venues={102},
                speakers={2},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 13:50"),
                venue=102,
            ),
            Talk(
                id=3,
                duration=40,
                allowed_venues={101, 102},
                speakers={3},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 14:20"),
                venue=101,
            ),
            Talk(id=4, duration=40, allowed_venues={101, 102}, speakers={1}, allowed_times=allowed_times),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs)

        for talk in solved.talks:
            if talk.id == 1:
                # There's no reason to move talk 1, so the speaker's only available afterwards
                assert talk.venue == 101
                assert talk.start_time == ts("2016-08-06 13:00")

    def test_talk_clash(self):
        # Talk 4 now has to precede talk 1. Talks 2 and 3 must remain in 102
        allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
        talk_defs = [
            Talk(
                id=1,
                duration=70,
                allowed_venues={101},
                speakers={1},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 13:00"),
            ),
            Talk(
                id=2,
                duration=50,
                allowed_venues={101, 102},
                speakers={2},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 13:00"),
            ),
            Talk(
                id=3,
                duration=50,
                allowed_venues={101, 102},
                speakers={3},
                allowed_times=allowed_times,
                start_time=ts("2016-08-06 14:20"),
            ),
            Talk(
                id=4,
                duration=20,
                allowed_venues={101, 102},
                speakers={4},
                allowed_times=[(ts("2016-08-06 13:00"), ts("2016-08-06 13:20"))],
                start_time=ts("2016-08-06 15:00"),
            ),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs)

        solved_talks = {talk.id: talk for talk in solved.talks}
        assert (
            solved_talks[4].start_time
            and solved_talks[1].start_time
            and solved_talks[4].start_time < solved_talks[1].start_time
        )

        for talk in solved.talks:
            if talk.id in (2, 3):
                assert talk.venue == 102
