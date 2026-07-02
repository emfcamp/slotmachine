"""Internal data model which represents time in terms of slots."""

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from dateutil import relativedelta

from .data import SchedulingProblem, SpeakerID, Talk, TalkID, VenueID

type Slot = int
type SlotInterval = tuple[Slot, Slot]


@dataclass
class SlottedVenueIntervals:
    """A mirror of the VenueTimes class with interval time measured in slots."""

    venue: VenueID
    intervals: list[SlotInterval]
    venue_weight: int = 0


def calc_slot(range_start: datetime, range_end: datetime, slot_duration: int) -> Slot:
    """Calculate the number of slots between two times."""
    return int((range_end - range_start).total_seconds() / 60 / slot_duration)


def calculate_slots(
    event_start: datetime,
    range_start: datetime,
    range_end: datetime,
    slot_duration: int,
    spacing_slots: int = 1,
) -> SlotInterval:
    slot_start = calc_slot(event_start, range_start, slot_duration)
    if slot_start < 0:
        raise ValueError("Invalid slot: range_start is before event_start")
    # We add the number of slots that must be between events to the end to
    # allow events to finish in the last period of the schedule
    return (
        slot_start,
        slot_start + calc_slot(range_start, range_end, slot_duration) + spacing_slots - 1,
    )


def calc_time(event_start: datetime, slots: int, slot_duration: int) -> datetime:
    return event_start + relativedelta.relativedelta(minutes=slots * slot_duration)


def merge_intervals(intervals: list[SlotInterval]) -> list[SlotInterval]:
    """Merge overlapping and adjacent slot intervals into contiguous ones.

    If we don't do this then talks will be unable to span across intervals.
    """

    merged: list[SlotInterval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class SlottedTalk:
    """A mirror of the Talk class with time measured in slots.

    Data is copied from the Talk object here because mypy doesn't have a good way of type-checking proxy objects.
    """

    id: TalkID
    #: Slotted duration, including changeover
    duration: Slot
    #: Slotted duration, excluding changeover
    content_duration: Slot
    speakers: set[SpeakerID]

    #: Tags used to gently prevent similar talks from running concurrently
    tags: set[str]

    #: The venues the talk may be scheduled in, each with the slot intervals allowed in that venue.
    venue_intervals: list[SlottedVenueIntervals]
    preferred_intervals: list[SlotInterval]

    start: Slot | None
    venue: VenueID | None

    talk: Talk

    def __init__(self, talk: Talk, problem: SchedulingProblem) -> None:
        self.talk = talk
        self.id = talk.id

        self.duration = (talk.duration + talk.minutes_after) // problem.slot_duration
        self.content_duration = talk.duration // problem.slot_duration

        self.speakers = talk.speakers
        self.tags = talk.tags

        changeover_after = talk.minutes_after // problem.slot_duration
        self.venue_intervals = [
            SlottedVenueIntervals(
                venue=vt.venue,
                venue_weight=vt.venue_weight,
                intervals=merge_intervals(
                    [
                        calculate_slots(
                            problem.start_time,
                            *time_range,
                            problem.slot_duration,
                            spacing_slots=changeover_after,
                        )
                        for time_range in vt.times
                    ]
                ),
            )
            for vt in talk.venue_times
        ]
        self.preferred_intervals = merge_intervals(
            [
                calculate_slots(
                    problem.start_time, *time_range, problem.slot_duration, spacing_slots=changeover_after
                )
                for time_range in talk.preferred_times
            ]
        )

        if talk.start_time:
            self.start = calc_slot(problem.start_time, talk.start_time, problem.slot_duration)
        else:
            self.start = None

        self.venue = talk.venue

    def to_talk(self, problem: SchedulingProblem) -> Talk:
        if self.start is None:
            raise ValueError("Attempting to convert talk without start slot")
        return dataclasses.replace(
            self.talk,
            start_time=calc_time(problem.start_time, self.start, problem.slot_duration),
            venue=self.venue,
        )

    def __repr__(self) -> str:
        return f"<SlottedTalk {self.id}, duration: {self.duration}, speakers: {self.speakers}, venue_intervals: {self.venue_intervals}>"
