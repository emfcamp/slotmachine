"""Public interface classes for slotmachine."""

from dataclasses import dataclass, field
from datetime import datetime
from itertools import chain

type TalkID = int
type VenueID = int
type SpeakerID = int

type TimeRange = tuple[datetime, datetime]


@dataclass
class Talk:
    #: Integer identifier for the talk
    id: TalkID

    #: Duration of the talk in minutes
    duration: int

    #: List of speaker IDs who are presenting this talk.
    #: Talks from the same speaker will be prevented from being scheduled at the same time.
    speakers: set[SpeakerID]

    #: Venues the talk is allowed to be scheduled in.
    allowed_venues: set[VenueID]
    #: Time ranges the talk is allowed to be scheduled in.
    allowed_times: list[TimeRange]

    #: Preferred venues: used to assign more popular talks to larger venues.
    preferred_venues: set[VenueID] = field(default_factory=set)
    preferred_times: list[TimeRange] = field(default_factory=list)

    #: Number of minutes allowed after the talk for changeover
    minutes_after: int = 10

    #: Scheduled start time of the talk - when passed to the scheduler, it will try and
    #: minimise changes.
    start_time: datetime | None = None
    #: Scheduled venue of the talk - when passed to the scheduler, it will try and
    #: minimise changes.
    venue: VenueID | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "duration": self.duration,
            "speakers": list(self.speakers),
            "valid_venues": list(self.allowed_venues),
            "time_ranges": [
                {"start": tr[0].isoformat(), "end": tr[1].isoformat()} for tr in self.allowed_times
            ],
            "preferred_venues": list(self.preferred_venues),
            "preferred_times": [
                {"start": tr[0].isoformat(), "end": tr[1].isoformat()} for tr in self.preferred_times
            ],
            "minutes_after": self.minutes_after,
            "time": self.start_time.isoformat() if self.start_time else None,
            "venue": self.venue,
        }


@dataclass()
class SchedulingProblem:
    """A problem for SlotMachine to solve.

    This is an immutable object.
    """

    talks: list[Talk]
    slot_duration: int

    start_time: datetime
    venues: set[VenueID]

    def __init__(self, talks: list[Talk], slot_duration: int):
        if len(talks) == 0:
            raise ValueError("No talks provided")

        self.talks = talks
        self.slot_duration = slot_duration

        self.start_time = min(range[0] for talk in self.talks for range in talk.allowed_times)
        self.venues = set(chain.from_iterable(talk.allowed_venues for talk in self.talks))

        for talk in self.talks:
            if talk.duration % self.slot_duration != 0:
                raise ValueError(
                    f"Talk {talk.id} duration {talk.duration} is not a multiple of slot duration {self.slot_duration}"
                )
            if talk.minutes_after % self.slot_duration != 0:
                raise ValueError(
                    f"Talk {talk.id} minutes_after {talk.minutes_after} is not a multiple of slot duration {self.slot_duration}"
                )


@dataclass
class SchedulingSolution:
    talks: list[Talk]

    def to_dict(self) -> list[dict]:
        return [talk.to_dict() for talk in self.talks]
