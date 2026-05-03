"""Internal data model which represents time in terms of slots."""

from datetime import datetime

from dateutil import relativedelta

from .data import SchedulingProblem, SpeakerID, Talk, TalkID, VenueID

type Slot = int
type SlotInterval = tuple[Slot, Slot]


def calc_slot(range_start: datetime, range_end: datetime, slot_duration: int) -> Slot:
    """Calculate the number of slots between two times."""
    return int((range_end - range_start).total_seconds() / 60 / slot_duration)


def calculate_slots(event_start, range_start, range_end, slot_duration: int, spacing_slots=1) -> SlotInterval:
    slot_start = calc_slot(event_start, range_start, slot_duration)
    # We add the number of slots that must be between events to the end to
    # allow events to finish in the last period of the schedule
    return (
        slot_start,
        slot_start + calc_slot(range_start, range_end, slot_duration) + spacing_slots - 1,
    )


def calc_time(event_start: datetime, slots: int, slot_duration: int) -> datetime:
    return event_start + relativedelta.relativedelta(minutes=slots * slot_duration)


class SlottedTalk:
    """A mirror of the Talk class with time measured in slots.

    Data is copied from the Talk object here because mypy doesn't have a good way of type-checking proxy objects.
    """

    id: TalkID
    #: Slotted duration, including changeover
    duration: Slot
    speakers: set[SpeakerID]

    allowed_venues: set[VenueID]
    preferred_venues: set[VenueID]

    allowed_intervals: list[SlotInterval]
    preferred_intervals: list[SlotInterval]

    start: Slot | None
    venue: VenueID | None

    talk: Talk

    def __init__(self, talk: Talk, problem: SchedulingProblem) -> None:
        self.talk = talk
        self.id = talk.id

        self.duration = (talk.duration + talk.minutes_after) // problem.slot_duration

        self.speakers = talk.speakers
        self.allowed_venues = talk.allowed_venues
        self.preferred_venues = talk.preferred_venues

        changeover_after = talk.minutes_after // problem.slot_duration
        self.allowed_intervals = [
            calculate_slots(problem.start_time, *range, problem.slot_duration, spacing_slots=changeover_after)
            for range in talk.allowed_times
        ]
        self.preferred_intervals = [
            calculate_slots(problem.start_time, *range, problem.slot_duration, spacing_slots=changeover_after)
            for range in talk.preferred_times
        ]

        if talk.start_time:
            self.start = calc_slot(problem.start_time, talk.start_time, problem.slot_duration)
        else:
            self.start = None

        self.venue = talk.venue

    def to_talk(self, problem: SchedulingProblem) -> Talk:
        if self.start is None:
            raise ValueError("Attempting to convert talk without start slot")
        talk = self.talk
        talk.start_time = calc_time(problem.start_time, self.start, problem.slot_duration)
        talk.venue = self.venue
        return talk
