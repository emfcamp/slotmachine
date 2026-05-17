# SlotMachine

A conference schedule optimizer using mixed integer linear programming, using the [OR-Tools](https://github.com/google/or-tools) library and solver.

SlotMachine generates an optimal schedule for a multi-venue event, solving thousands of constraints on speaker availability and venue requirements in seconds.
It can also take an existing schedule and calculate the minimum number of changes required to accommodate a change in constraints.

SlotMachine is used to generate the schedule for [Electromagnetic Field](https://www.emfcamp.org) events.

## How to use

Create a `SchedulingProblem` out of a list of `Talk`s:

```python
from slotmachine import Talk, SchedulingProblem

talks = [
    Talk(
        # Talk ID for identifying talks in the result
        id=1,
        # Speaker IDs - the system will avoid scheduling two talks from the same speaker at the same time.
        speakers={1, 2},
        # Venue IDs
        allowed_venues={1},
        # Duration of the talk in minutes
        duration=30,
        # Time ranges when the talk is allowed to be scheduled
        allowed_times=[
            (datetime(2026, 5, 16, 12, 0, 0), datetime(2026, 5, 16, 19, 0, 0))
        ]
    ),
    ...
]

problem = SchedulingProblem(
    talks=talks,
    # The size of a "slot" - this is the granularity the scheduler will operate at.
    # All durations and allowed times must be multiples of this number.
    slot_duration=10
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

This library intentionally does not deal with venue or speaker availability, as this can be quite complex and event-specific.
This can be handled outside slotmachine by setting `allowed_times` to the intersection of the speaker and venue availability.

Per-venue allowed time ranges are [coming soon](https://github.com/emfcamp/slotmachine/issues/14).

## Acknowledgements

The concept and code for the original [CBC](https://projects.coin-or.org/Cbc)-based version of this library is from [David MacIver](http://www.drmaciver.com/).

For more information on this approach, see David's talk [Easy solutions to hard
problems](https://www.youtube.com/watch?v=OkusHEBOhmQ) from PyCon UK 2016.

A similar library with a slightly different approach is [conference-scheduler](http://conference-scheduler.readthedocs.io/en/latest/).
