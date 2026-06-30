"""Public interface classes for slotmachine."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from dateutil.parser import parse as parse_datetime

type TalkID = int
type VenueID = int
type SpeakerID = int

type TimeRange = tuple[datetime, datetime]


def parse_time_range(range: dict[str, str]) -> tuple[datetime, datetime]:
    return (parse_datetime(range["start"]), parse_datetime(range["end"]))


def time_range_to_dict(time_range: TimeRange) -> dict[str, str]:
    return {"start": time_range[0].isoformat(), "end": time_range[1].isoformat()}


@dataclass
class VenueTimes:
    """A venue and the time ranges a talk is allowed to be scheduled in it."""

    #: A venue the talk may be scheduled in.
    venue: VenueID
    #: Time ranges the talk is allowed to be scheduled in this venue.
    times: list[TimeRange]


@dataclass
class Talk:
    #: Integer identifier for the talk
    id: TalkID

    #: Duration of the talk in minutes
    duration: int

    #: List of speaker IDs who are presenting this talk.
    #: Talks from the same speaker will be prevented from being scheduled at the same time.
    speakers: set[SpeakerID]

    #: The venues the talk may be scheduled in, each with the time ranges it's allowed in that venue.
    venue_times: list[VenueTimes]

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

        if all(
            end - start < timedelta(minutes=self.duration)
            for vt in self.venue_times
            for start, end in vt.times
        ):
            raise ValueError(f"Talk {self.id} has no allowed time ranges long enough to schedule into.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "duration": self.duration,
            "speakers": list(self.speakers),
            "venue_times": [
                {"venue": vt.venue, "times": [time_range_to_dict(tr) for tr in vt.times]}
                for vt in self.venue_times
            ],
            "preferred_venues": list(self.preferred_venues),
            "preferred_times": [time_range_to_dict(tr) for tr in self.preferred_times],
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
            venue_times=[
                VenueTimes(venue=vt["venue"], times=[parse_time_range(r) for r in vt["times"]])
                for vt in talk["venue_times"]
            ],
            preferred_venues=set(talk.get("preferred_venues", [])),
            preferred_times=[parse_time_range(r) for r in talk.get("preferred_times", [])],
            minutes_after=talk.get("minutes_after", 10),
            start_time=parse_datetime(talk.get("time", "")) if talk.get("time") else None,
            venue=talk.get("venue"),
        )


@dataclass()
class SchedulingProblem:
    """A problem for SlotMachine to solve.

    This is an immutable object.
    """

    #: The list of Talk objects to be scheduled.
    talks: list[Talk]

    #: The duration of a "slot" in minutes: this is the minimum granularity of the scheduler.
    #: All durations and timestamp properties of talks must be a multiple of this, or an exception will be thrown.
    slot_duration: int

    ## Calculated fields
    start_time: datetime
    venues: set[VenueID]

    def __init__(self, talks: list[Talk], slot_duration: int):
        if len(talks) == 0:
            raise ValueError("No talks provided")

        self.talks = talks
        self.slot_duration = slot_duration

        # The start_time is the epoch that the solver uses, so it must be the earliest time present
        # in any part of the scheduling problem, or negative slot numbers will cause issues.
        self.start_time = min(
            [time_range[0] for talk in self.talks for vt in talk.venue_times for time_range in vt.times]
            + [time_range[0] for talk in self.talks for time_range in talk.preferred_times]
            + [talk.start_time for talk in self.talks if talk.start_time is not None]
        )

        self.venues = {vt.venue for talk in self.talks for vt in talk.venue_times}

        for talk in self.talks:
            talk.validate(self.slot_duration)

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> "SchedulingProblem":
        talks = []
        for talk_data in data:
            talks.append(Talk.from_dict(talk_data))
        return SchedulingProblem(talks=talks, slot_duration=10)


@dataclass(frozen=True)
class SchedulingSolution:
    """A solution to a SchedulingProblem"""

    #: A list of talks, with their start_time and venue properties set
    talks: list[Talk]

    ## Detail about the solution
    #: How long the scheduler took to run
    timings: dict[str, timedelta]
    #: The type of solution
    solution_type: str
    #: Number of variables in the linear programming model
    variables: int

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, SchedulingSolution) and self.talks == other.talks

    def to_dict(self) -> list[dict[str, Any]]:
        return [talk.to_dict() for talk in self.talks]
