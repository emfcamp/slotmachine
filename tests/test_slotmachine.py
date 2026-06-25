from datetime import datetime, timedelta
from itertools import permutations

import pytest
from dateutil.parser import parse as ts
from hypothesis import assume, given
from hypothesis import strategies as st

from slotmachine import SlotMachine, Talk, Unsatisfiable
from slotmachine.data import SchedulingProblem, SchedulingSolution, TimeRange

SLOT_DURATION = 10


@st.composite
def durations(draw: st.DrawFn, min_duration: int = 10, max_duration: int = 120) -> int:
    """Hypothesis strategy to generate a talk duration which is a multiple of the slot duration."""
    return (
        draw(st.integers(min_value=min_duration // SLOT_DURATION, max_value=max_duration // SLOT_DURATION))
        * SLOT_DURATION
    )


@st.composite
def time_ranges(
    draw: st.DrawFn, min_duration: int = 10, max_duration: int = 600, within: TimeRange | None = None
) -> TimeRange:
    if within is None:
        within = (datetime(2000, 1, 1), datetime(2060, 1, 1))

    start = draw(st.datetimes(min_value=within[0], max_value=within[1]))
    duration = draw(durations(min_duration=min_duration, max_duration=max_duration))
    return (start, start + timedelta(minutes=duration))


def total_duration(talks: list[Talk]) -> timedelta:
    """Return the total duration of a list of talks, including changeover time."""
    return timedelta(minutes=sum(talk.duration + talk.minutes_after for talk in talks))


def time_overlaps(range1: TimeRange, range2: TimeRange) -> bool:
    latest_start = max(range1[0], range2[0])
    earliest_end = min(range1[1], range2[1])
    delta = (earliest_end - latest_start).total_seconds()
    return delta > 0


def schedule_assert_solvable(talks: list[Talk]) -> SchedulingSolution:
    """Run the scheduler on a list of talks, asserting that it's solveable and the result looks valid."""
    problem = SchedulingProblem(talks=talks, slot_duration=SLOT_DURATION)
    sm = SlotMachine(problem)
    solution = sm.solve()

    assert_solution_looks_reasonable(problem, solution)

    return solution


def assert_solution_looks_reasonable(problem: SchedulingProblem, solution: SchedulingSolution) -> None:
    # All talks must be represented
    assert set(talk.id for talk in problem.talks) == set(talk.id for talk in solution.talks)

    # All time/venue tuples must be different
    slot_venues = [(talk.venue, talk.start_time) for talk in solution.talks]
    assert sorted(set(slot_venues)) == sorted(slot_venues)

    for talk in solution.talks:
        # Venue must be allowed
        assert talk.venue in talk.allowed_venues

        # Talk must be assigned a start time
        assert talk.start_time
        assert any(start <= talk.start_time < end for (start, end) in talk.allowed_times)

        # End time should be calculated correctly
        assert talk.end_time
        assert talk.end_time > talk.start_time
        # Talk should end in allowed times
        assert any(start < talk.end_time <= end for (start, end) in talk.allowed_times)

    # Talks must not overlap
    for a, b in permutations(solution.talks, 2):
        assert a.start_time and a.end_time
        assert b.start_time and b.end_time
        if a.venue == b.venue:
            assert not time_overlaps(
                (a.start_time, a.end_time),
                (b.start_time, b.end_time),
            )


def schedule_assert_fail(talks: list[Talk]) -> None:
    sm = SlotMachine(SchedulingProblem(talks=talks, slot_duration=10))

    with pytest.raises(Unsatisfiable):
        sm.solve()


@given(st.lists(durations(), min_size=1), durations(), time_ranges())
def test_simple(durations, minutes_after, allowed_times):
    """Test scheduling of talks in a single venue"""
    talk_defs = [
        Talk(
            id=i,
            duration=durations[i],
            allowed_venues={101},
            speakers={1},
            allowed_times=[allowed_times],
            minutes_after=minutes_after,
        )
        for i in range(0, len(durations))
    ]

    assume(
        total_duration(talk_defs) <= (allowed_times[1] - allowed_times[0]) + timedelta(minutes=minutes_after)
    )

    solved = schedule_assert_solvable(talk_defs)

    # Solution should be stable
    solved_second = schedule_assert_solvable(solved.talks)
    assert solved == solved_second


@given(st.lists(durations(), min_size=1), durations(max_duration=60), time_ranges(min_duration=120))
def test_too_many_talks(durations, minutes_after, allowed_times):
    talk_defs = [
        Talk(
            id=i,
            duration=durations[i],
            allowed_venues={101},
            speakers={1},
            allowed_times=[allowed_times],
            minutes_after=minutes_after,
        )
        for i in range(0, len(durations))
    ]
    assume(
        total_duration(talk_defs) > (allowed_times[1] - allowed_times[0]) + timedelta(minutes=minutes_after)
    )

    schedule_assert_fail(talk_defs)


@given(durations(), durations(), st.lists(time_ranges(), min_size=1, max_size=5))
def test_invalid_allowed_times(duration, minutes_after, allowed_times):
    """Talk with a duration longer than any of its allowed_times slots"""
    assume(all((r[1] - r[0]) < timedelta(minutes=duration) for r in allowed_times))
    talk = Talk(
        id=1,
        duration=duration,
        allowed_venues={101},
        speakers={1},
        allowed_times=allowed_times,
        minutes_after=minutes_after,
    )

    with pytest.raises(ValueError):
        talk.validate(10)


def test_two_venues():
    # talk 3 should end up in venue 102
    allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 14:00"))]
    talk_defs = [
        Talk(id=1, duration=50, allowed_venues={101}, speakers={1}, allowed_times=allowed_times),
        Talk(id=2, duration=20, allowed_venues={102}, speakers={2}, allowed_times=allowed_times),
        Talk(id=3, duration=20, allowed_venues={101, 102}, speakers={3}, allowed_times=allowed_times),
    ]

    solved = schedule_assert_solvable(talk_defs)

    for talk in solved.talks:
        if talk.id == 3:
            assert talk.venue == 102


def test_venue_too_full():
    # Talks 1 and 3 won't fit into 101 together, and 3 and 4 won't fit in 102 together
    allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 15:00"))]
    talk_defs = [
        Talk(id=1, duration=70, allowed_venues={101}, speakers={1}, allowed_times=allowed_times),
        Talk(id=2, duration=40, allowed_venues={101, 102}, speakers={2}, allowed_times=allowed_times),
        Talk(id=3, duration=50, allowed_venues={101, 102}, speakers={3}, allowed_times=allowed_times),
        Talk(id=4, duration=70, allowed_venues={102}, speakers={4}, allowed_times=allowed_times),
    ]

    schedule_assert_fail(talk_defs)


def test_venue_clash():
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

    solved = schedule_assert_solvable(talk_defs)

    for talk in solved.talks:
        if talk.id == 1:
            # Talk 1 shouldn't move
            assert talk.venue == 101
            assert talk.start_time == ts("2016-08-06 13:00")


def test_speaker_clash():
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

    solved = schedule_assert_solvable(talk_defs)

    for talk in solved.talks:
        assert talk.start_time is not None
        match talk.id:
            case 1:
                # There's no reason to move talk 1
                assert talk.venue == 101
                assert talk.start_time == ts("2016-08-06 13:00")
            case 4:
                # Talk 4 needs to be scheduled after talk 1 has finished
                assert talk.venue in {101, 102}
                assert talk.start_time > ts("2016-08-06 14:10")


def test_talk_clash():
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

    solved = schedule_assert_solvable(talk_defs)

    solved_talks = {talk.id: talk for talk in solved.talks}
    assert (
        solved_talks[4].start_time
        and solved_talks[1].start_time
        and solved_talks[4].start_time < solved_talks[1].start_time
    )

    for talk in solved.talks:
        if talk.id in (2, 3):
            assert talk.venue == 102


def test_preferred_venues():
    allowed_times = [(ts("2016-08-06 13:00"), ts("2016-08-06 19:00"))]
    venues = {101, 102, 103}

    talks = [
        Talk(
            id=1,
            duration=60,
            allowed_venues=venues,
            preferred_venues={102},
            speakers={1},
            allowed_times=allowed_times,
        ),
        Talk(
            id=2,
            duration=60,
            allowed_venues=venues,
            preferred_venues={103},
            speakers={2},
            allowed_times=allowed_times,
        ),
        Talk(
            id=3,
            duration=60,
            allowed_venues=venues,
            preferred_venues={103},
            speakers={3},
            allowed_times=allowed_times,
        ),
    ]

    solved = schedule_assert_solvable(talks)

    for talk in solved.talks:
        match talk.id:
            case 1:
                assert talk.venue == 102
            case 2 | 3:
                assert talk.venue == 103


def test_large_1():
    # A larger (but still straightforward) test set:
    # 4 days, 3 venues. All unique speakers and all talks allowed in all venues.
    allowed_times = [
        (ts("2016-08-05 10:00"), ts("2016-08-05 19:00")),
        (ts("2016-08-06 10:00"), ts("2016-08-06 19:00")),
        (ts("2016-08-07 10:00"), ts("2016-08-07 19:00")),
        (ts("2016-08-08 10:00"), ts("2016-08-08 19:00")),
    ]
    venues = {101, 102, 103}
    available_time = sum((day[1] - day[0]).total_seconds() for day in allowed_times) * len(venues)
    talk_length = 40
    num_talks = int(available_time / 60 / (talk_length + SLOT_DURATION))

    talks = []
    for i in range(0, num_talks):
        talks.append(
            Talk(id=i, duration=talk_length, allowed_venues=venues, speakers={i}, allowed_times=allowed_times)
        )

    schedule_assert_solvable(talks)

    # The EMF 2022 issue: we scheduled the opening session, and added two fake talks to prevent
    # anything being scheduled in the other venues while that was happening. Unfortunately
    # those talks had the same speaker ID and were constrained for their allowed_times,
    # so the schedule was unsolvable.

    # Remove 3 talks to replace them
    talks = talks[:-3]

    for venue in venues:
        talks.append(
            Talk(
                id=num_talks + venue,
                duration=talk_length,
                allowed_venues={venue},
                speakers={1000},
                allowed_times=[(ts("2016-08-05 10:00"), ts("2016-08-05 11:00"))],
            )
        )

    schedule_assert_fail(talks)


def test_invalid_allowed_time():
    # start_time is before the earliest allowed_time - don't generate a negative slot number
    talks = [
        Talk(
            id=1,
            duration=30,
            allowed_venues={1},
            speakers={1},
            allowed_times=[(ts("2016-08-05 10:00"), ts("2016-08-05 19:00"))],
            start_time=ts("2016-08-04 10:00"),
            venue=1,
        )
    ]

    schedule_assert_solvable(talks)
