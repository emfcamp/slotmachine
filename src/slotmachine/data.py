"""Public interface classes for slotmachine."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import chain
from typing import Any

from dateutil.parser import parse as parse_datetime

type TalkID = int
type VenueID = int
type SpeakerID = int

type TimeRange = tuple[datetime, datetime]


def parse_time_range(range: dict[str, str]) -> tuple[datetime, datetime]:
    return (parse_datetime(range["start"]), parse_datetime(range["end"]))


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

    #: Preferred venues: can be used to assign more popular talks to larger venues.
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

    @property
    def end_time(self) -> datetime | None:
        """End time, calculated from the start_time plus the duration"""
        if self.start_time is None:
            return None
        return self.start_time + timedelta(minutes=self.duration)

    def validate(self, slot_duration: int) -> None:
        if self.duration % slot_duration != 0:
            raise ValueError(
                f"Talk {self.id} duration {self.duration} is not a multiple of slot duration {slot_duration}"
            )

        if self.duration <= 0:
            raise ValueError(f"Talk {self.id} has an invalid duration: {self.duration}")

        if self.minutes_after % slot_duration != 0:
            raise ValueError(
                f"Talk {self.id} minutes_after {self.minutes_after} is not a multiple of slot duration {slot_duration}"
            )

        if all(end - start < timedelta(minutes=self.duration) for start, end in self.allowed_times):
            raise ValueError(f"Talk {self.id} has no allowed time ranges long enough to schedule into.")

    def to_dict(self) -> dict[str, Any]:
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

    @classmethod
    def from_dict(cls, talk: dict[str, Any]) -> "Talk":
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
            talk.validate(self.slot_duration)

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> "SchedulingProblem":
        talks = []
        for talk_data in data:
            talks.append(Talk.from_dict(talk_data))
        return SchedulingProblem(talks=talks, slot_duration=10)


@dataclass
class SchedulingSolution:
    talks: list[Talk]

    def to_dict(self) -> list[dict[str, Any]]:
        return [talk.to_dict() for talk in self.talks]
