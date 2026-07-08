# SlotMachine

An automatic conference schedule optimiser, built on the [OR-Tools](https://github.com/google/or-tools) linear programming library and solver.

SlotMachine generates an optimal schedule for a multi-venue event, solving thousands of constraints on speaker availability and venue requirements in seconds.
It can also take an existing schedule and calculate the minimum number of changes required to accommodate a change in constraints.

SlotMachine is used to generate the schedule for [Electromagnetic Field](https://www.emfcamp.org) events.

## How to use

Create a `SchedulingProblem` out of a list of `Talk`s:

```python
from slotmachine import Talk, VenueTimes, SchedulingProblem, Conflict

talks = [
    Talk(
        # Talk ID for identifying talks in the result
        id=1,
        # Speaker IDs - the system will avoid scheduling two talks from the same speaker at the same time.
        speakers={1, 2},
        # Duration of the talk in minutes
        duration=30,
        # Optional: The system will attempt to avoid running talks with the same tags at the same time.
        tags={"security", "hardware"},
        # The venues the talk may be scheduled in, each with its own allowed
        # time ranges. An optional venue_weight expresses how much the talk
        # benefits from being scheduled in that venue (0 = no preference).
        # For sorting popular talks onto bigger stages, supply weights in a range
        # from 0-100.
        # It is suggested that you calculate it as popularity_rank * capacity_rank
        # popularity_rank is the talk's popularity bucketed into 1 (least popular)
        # to 10 (most popular)
        # capacity_rank is venue's capacity bucketed into 1 (smallest venue) to
        # 10 (largest venue)
        venue_times=[
            VenueTimes(
                venue=1,
                times=[
                    (datetime(2026, 5, 16, 12, 0, 0), datetime(2026, 5, 16, 19, 0, 0)),
                ],
                # Optional: Weights above 0 increase the chance of this venue being selected.
                # Higher numbers have higher weight, equal numbers get equal preference.
                venue_weight=10,
            ),
            VenueTimes(
                venue=2,
                times=[
                    (datetime(2026, 5, 16, 14, 0, 0), datetime(2026, 5, 16, 19, 0, 0)),
                ],
            ),
            ...
        ],
    ),
    ...
]

problem = SchedulingProblem(
    talks=talks,
    # The length of a "slot" in minutes - this is the granularity the scheduler will operate at.
    # All durations and allowed times must be multiples of this number.
    slot_duration=10,
    # Optional: Weighted groups of talks to strongly discourage from running at
    # the same time. Each referenced talk must be in `talks`, and weight must
    # be a positive integer. Suggestion is to use the number of attendees who
    # would be affected by this conflict.
    conflicts=[
        Conflict(talks={1, 2}, weight=10),
        Conflict(
            talks={3, 4},
            weight=50,
            # Optional: Specify a set of time ranges to attempt to spread the
            # conflict across, there must be at least the same number of ranges
            # as there are talks in the conflict. This is useful for ensuring that
            # something running multiple times has instances on different days.
            spread_across={
                (datetime(2026, 5, 16, 0, 0, 0), datetime(2026, 5, 17, 0, 0, 0)),
                (datetime(2026, 5, 17, 0, 0, 0), datetime(2026, 5, 18, 0, 0, 0)),
            },
        ),
        ...
    ],
)
```

There are other options to the `Talk` class which are documented [in the code](src/slotmachine/data.py). Now you can run the solver:

```python
from slotmachine import SlotMachine

slotmachine = SlotMachine(problem)
result = slotmachine.solve()
```

`result.talks` will be a list of talks with the `start_time` and `venue` fields set.

### Updating a schedule

If you need to update your schedule, you can pass a list of `Talks` with their existing `start_time` and `venue` values set.
The solver will minimise the number of schedule changes required to accommodate the changes in constraints.

### Venue/speaker availability

This library does not deal directly with venue or speaker availability, as this can be quite complex and event-specific.
It can be handled outside SlotMachine by setting each `VenueTimes.times` to the intersection of the speaker and venue availability for that venue.

## Acknowledgements

- The concept and code for the original version of this library was from [David MacIver](http://www.drmaciver.com/).
- For more information on this approach, see David's talk [Easy solutions to hard problems](https://www.youtube.com/watch?v=OkusHEBOhmQ) from PyCon UK 2016.
- A similar library with a slightly different approach is [conference-scheduler](http://conference-scheduler.readthedocs.io/en/latest/).
