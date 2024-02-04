import unittest
from collections import defaultdict
from dateutil import parser
from functools import partial
from slotmachine import (
    SlotMachine,
    Unsatisfiable,
    Talk,
    TalkID,
    Slot,
    SlotCount,
    VenueID,
)
from typing import Iterable


def unzip(l):
    return zip(*l)


def talk(
    id: int,
    duration: int,
    venues: list[int],
    speakers: list[str],
    slots: Iterable[Slot] | Iterable[int],
) -> Talk:
    return Talk(
        id=TalkID(id),
        duration=SlotCount(duration),
        venues={VenueID(vid) for vid in venues},
        speakers=speakers,
        allowed_slots={Slot(s) for s in slots},
    )


class UtilTestCase(unittest.TestCase):
    def test_calculate_slots(self):
        event_start = parser.parse("2016-08-05 13:00")
        slots_minimal = SlotMachine.calculate_slots(
            event_start,
            parser.parse("2016-08-05 13:00"),
            parser.parse("2016-08-05 14:00"),
        )
        # the final slot is because all talks are made one slot longer for changeover
        self.assertCountEqual(slots_minimal, range(0, 6 + 1))
        slots_sat_13_16 = SlotMachine.calculate_slots(
            event_start,
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 16:00"),
        )
        self.assertCountEqual(slots_sat_13_16, range(144, 144 + 18 + 1))


class ScheduleTalksTestCase(unittest.TestCase):
    def schedule_and_basic_asserts(self, talk_defs, avail_slots, old_talks=None):
        if old_talks is None:
            old_talks = []

        talk_ids: list[TalkID] = [t.id for t in talk_defs]
        talk_defs_by_id: dict[TalkID, Talk] = {t.id: t for t in talk_defs}

        sm = SlotMachine()
        sm.slots_available = avail_slots

        solved = sm.schedule_talks(talk_defs, old_talks=old_talks)
        slots, talks, venues = unzip(solved)

        # All talks must be represented
        self.assertEqual(sorted(talks), sorted(talk_ids))
        # All slots/venue tuples must be different
        slot_venues = list(zip(slots, venues))
        self.assertEqual(sorted(set(slot_venues)), sorted(slot_venues))
        # Check slots are valid
        self.assertTrue(all(s in avail_slots for s in slots))

        used_slots = defaultdict(set)
        for slot, talk, venue in solved:
            talk_def = talk_defs_by_id[talk]

            self.assertIn(venue, talk_def.venues)
            self.assertIn(slot, talk_def.allowed_slots)

            for i in range(talk_def.duration):
                self.assertNotIn(slot + i, used_slots[venue])
                used_slots[venue].add(slot + i)

        return solved

    def schedule_and_assert_fails(self, talk_defs, avail_slots, old_talks=None):
        if old_talks is None:
            old_talks = []

        sm = SlotMachine()
        sm.slots_available = avail_slots

        with self.assertRaises(Unsatisfiable):
            solved = sm.schedule_talks(talk_defs, old_talks=old_talks)
            print(solved)

    def test_simple(self):
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 15:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=3 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=3 + 1, venues=[101], speakers=["Speaker 2"]),
            _talk(id=3, duration=3 + 1, venues=[101], speakers=["Speaker 3"]),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs, avail_slots)

        # Solution should be stable
        solved_second = self.schedule_and_basic_asserts(
            talk_defs, avail_slots, old_talks=solved
        )
        self.assertEqual(solved, solved_second)

    def test_too_many_talks(self):
        # This should just exceed the number of available slots (12 + 1)
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 15:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=4 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=4 + 1, venues=[101], speakers=["Speaker 2"]),
            _talk(id=3, duration=3 + 1, venues=[101], speakers=["Speaker 3"]),
        ]

        self.schedule_and_assert_fails(talk_defs, avail_slots)

    def test_two_venues(self):
        # talk 3 should end up in venue 102
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 14:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=5 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=2 + 1, venues=[102], speakers=["Speaker 2"]),
            _talk(id=3, duration=2 + 1, venues=[101, 102], speakers=["Speaker 3"]),
        ]

        solved = self.schedule_and_basic_asserts(talk_defs, avail_slots)

        talk_venues = dict([(t, v) for s, t, v in solved])
        self.assertEqual(talk_venues[TalkID(3)], 102)

    def test_venue_too_full(self):
        # Talks 1 and 3 won't fit into 101 together, and 3 and 4 won't fit in 102 together
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 15:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=7 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=4 + 1, venues=[101, 102], speakers=["Speaker 2"]),
            _talk(id=3, duration=5 + 1, venues=[101, 102], speakers=["Speaker 3"]),
            _talk(id=4, duration=7 + 1, venues=[102], speakers=["Speaker 4"]),
        ]

        self.schedule_and_assert_fails(talk_defs, avail_slots)

    def test_venue_clash(self):
        # Talks 2 and 3 must move to accommodate talk 4
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 15:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=7 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=4 + 1, venues=[101, 102], speakers=["Speaker 2"]),
            _talk(id=3, duration=4 + 1, venues=[101, 102], speakers=["Speaker 3"]),
            _talk(id=4, duration=7 + 1, venues=[102], speakers=["Speaker 4"]),
        ]

        old_talks = [(0, 1, 101), (2, 2, 102), (7, 3, 102)]
        solved = self.schedule_and_basic_asserts(
            talk_defs, avail_slots, old_talks=old_talks
        )

        # Talk 1 shouldn't move
        self.assertIn((0, 1, 101), solved)

    def test_speaker_clash(self):
        # Talk 4 is by Speaker 1
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 15:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=7 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=7 + 1, venues=[102], speakers=["Speaker 2"]),
            _talk(id=3, duration=4 + 1, venues=[101, 102], speakers=["Speaker 3"]),
            _talk(id=4, duration=4 + 1, venues=[101, 102], speakers=["Speaker 1"]),
        ]

        # Either talk 2 or 3 will have to move
        old_talks = [(0, 1, 101), (5, 2, 102), (8, 3, 101)]
        solved = self.schedule_and_basic_asserts(
            talk_defs, avail_slots, old_talks=old_talks
        )

        slots, talks, venues = unzip(solved)
        talks_slots = dict(zip(talks, slots))

        # There's no reason to move talk 1, so the speaker's only available afterwards
        self.assertTrue(talks_slots[4] >= 8)

    def test_talk_clash(self):
        # Talk 4 now has to precede talk 1. Talks 2 and 3 must remain in 102
        avail_slots = SlotMachine.calculate_slots(
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 13:00"),
            parser.parse("2016-08-06 15:00"),
        )
        _talk = partial(talk, slots=avail_slots[:])
        talk_defs = [
            _talk(id=1, duration=7 + 1, venues=[101], speakers=["Speaker 1"]),
            _talk(id=2, duration=5 + 1, venues=[101, 102], speakers=["Speaker 2"]),
            _talk(id=3, duration=5 + 1, venues=[101, 102], speakers=["Speaker 3"]),
            _talk(
                id=4,
                duration=2 + 1,
                venues=[101, 102],
                speakers=["Speaker 4"],
                slots={0, 1, 2},
            ),
        ]

        # Talk 4 was previously scheduled after talk 1
        old_talks = [(0, 1, 101), (0, 2, 102), (6, 3, 102), (8, 4, 101)]
        solved = self.schedule_and_basic_asserts(
            talk_defs, avail_slots, old_talks=old_talks
        )

        slots, talks, venues = unzip(solved)
        talks_slots = dict(zip(talks, slots))

        # Talk 1 must now be in slot 3 or 4
        self.assertIn(talks_slots[1], [3, 4])
