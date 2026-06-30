from dateutil.parser import parse as ts

from slotmachine.data import SchedulingProblem, Talk, VenueTimes
from slotmachine.slots import SlottedTalk, calculate_slots


def test_talk_can_span_adjacent_slot_ranges():
    # This talk is longer than either of the two time ranges passed, but
    # they're adjacent so it should be able to span them because they're
    # internally made contiguous once converted to slots
    talk = Talk(
        id=1,
        venue_times=[
            VenueTimes(
                venue=101,
                times=[
                    (ts("2016-08-05 10:00"), ts("2016-08-05 12:00")),
                    (ts("2016-08-05 12:00"), ts("2016-08-05 14:00")),
                ],
            )
        ],
        duration=240,
        speakers={1},
    )
    problem = SchedulingProblem(talks=[talk], slot_duration=10)

    t = SlottedTalk(talk, problem)
    assert t.venue_intervals[0].intervals == [(0, 24)]


def test_calculate_slots():
    event_start = ts("2016-08-05 13:00")
    slots_minimal = calculate_slots(event_start, ts("2016-08-05 13:00"), ts("2016-08-05 14:00"), 10)
    # the final slot is because all talks are made one slot longer for changeover
    assert slots_minimal == (0, 6)

    slots_sat_13_16 = calculate_slots(event_start, ts("2016-08-06 13:00"), ts("2016-08-06 16:00"), 10)
    assert slots_sat_13_16 == (144, 144 + 18)


def test_slot_conversion():
    talks = [
        Talk(
            id=1,
            venue_times=[VenueTimes(venue=101, times=[(ts("2016-08-05 13:00"), ts("2016-08-05 14:00"))])],
            duration=60,
            speakers={1},
        ),
        Talk(
            id=2,
            venue_times=[VenueTimes(venue=102, times=[(ts("2016-08-05 14:00"), ts("2016-08-05 15:00"))])],
            duration=60,
            speakers={2},
        ),
    ]

    problem = SchedulingProblem(talks=talks, slot_duration=10)

    assert problem.start_time == ts("2016-08-05 13:00")

    t = SlottedTalk(talks[1], problem)
    assert t.venue_intervals[0].venue == 102
    assert t.venue_intervals[0].intervals[0] == (6, 12)
    assert t.duration == 7  # 60 minutes + changover
