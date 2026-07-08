import logging
import time
from datetime import timedelta

from ortools.sat.python import cp_model

from .data import SchedulingProblem, SchedulingSolution, SpeakerID, TalkID, VenueID
from .slots import Slot, SlotInterval, SlottedTalk


class Unsatisfiable(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


class SlotMachine:
    def __init__(self, problem: SchedulingProblem) -> None:
        self.log = logging.getLogger(__name__)
        self.problem = problem

        # Vars representing the selected talk slot and venue
        self.talk_slot_vars: dict[TalkID, cp_model.IntVar] = {}
        self.talk_venue_active_vars: dict[tuple[TalkID, VenueID], cp_model.IntVar] = {}

    def generate_problem(self, talks: list[SlottedTalk]) -> None:
        self.model = cp_model.CpModel()
        self.talk_slot_vars = {}
        self.talk_venue_active_vars = {}

        venue_intervals: dict[VenueID, list[cp_model.IntervalVar]] = {}
        talk_intervals: dict[TalkID, cp_model.IntervalVar] = {}
        talk_slot_max: dict[TalkID, Slot] = {}

        ## Main constraint problem generation
        #
        # This ensures that talks are placed into one venue at a time they are
        # permitted without clashing or forcing people to be in multiple places
        # at once. It does _not_ ensure that we don't totally regenerate the
        # existing schedule, or optimise the schedule in any way.

        for talk in talks:
            # Build a per-venue map of allowed time intervals, keeping only
            # intervals large enough to fit the talk.
            venue_allowed_intervals: dict[VenueID, list[SlotInterval]] = {}
            for vt in talk.venue_intervals:
                for interval in vt.intervals:
                    int_start, int_end = interval
                    if int_end - int_start + 1 >= talk.duration:
                        venue_allowed_intervals.setdefault(vt.venue, []).append(interval)

            # If no venue has an interval large enough to fit this talk, create a
            # variable that cannot possibly be satisfied for warning purposes. We
            # do this because otherwise the valid talk domain would end up empty,
            # and instead of failing to solve the talk would just be ignored.
            if not venue_allowed_intervals:
                oh_no_var = self.model.new_bool_var(f"_impossible_{talk.id}")
                self.model.add(oh_no_var == 1)
                self.model.add(oh_no_var == 0)
                continue

            allowed_intervals = {
                (int_start, int_end - talk.duration + 1)
                for intervals in venue_allowed_intervals.values()
                for int_start, int_end in intervals
            }

            # The highest slot a talk can occupy, used later for setting
            # variable search bounds
            talk_slot_max[talk.id] = max(latest_start for _, latest_start in allowed_intervals)

            # Int var representing the possible talk slots inside the set of
            # permitted intervals for this talk
            start_var = self.model.new_int_var_from_domain(
                cp_model.Domain.from_intervals(allowed_intervals),
                f"talk_slot_{talk.id}",
            )
            self.talk_slot_vars[talk.id] = start_var

            # Interval var representing the talk period without venue, used to
            # prevent speakers being in multiple places at the same time
            talk_intervals[talk.id] = self.model.new_interval_var(
                start_var, talk.duration, start_var + talk.duration, f"talk_interval_{talk.id}"
            )

            # A set of optional Interval vars that represent all possible
            # slot/venue placements inside our permitted intervals, of which
            # only one will be chosen (enforced by the followup constraint).
            # The active bool var will be true for the slot that is selected.
            venue_active_vars: list[cp_model.IntVar] = []
            for venue in sorted(venue_allowed_intervals):
                active = self.model.new_bool_var(f"talk_venue_active_{talk.id}_{venue}")
                self.talk_venue_active_vars[(talk.id, venue)] = active
                venue_active_vars.append(active)

                optional_talk_venue_interval = self.model.new_optional_interval_var(
                    start_var,
                    talk.duration,
                    start_var + talk.duration,
                    active,
                    f"talk_venue_interval_{talk.id}_{venue}",
                )
                venue_intervals.setdefault(venue, []).append(optional_talk_venue_interval)

                # Constrain this talk to only be allowed to be active in this
                # venue in time intervals where it is allowed to be scheduled
                in_interval_vars: list[cp_model.IntVar] = []
                for i, (int_start, int_end) in enumerate(venue_allowed_intervals[venue]):
                    in_this_venue = self.model.new_bool_var(
                        f"talk_venue_interval_allowed_{talk.id}_{venue}_{i}"
                    )
                    self.model.add(start_var >= int_start).only_enforce_if(in_this_venue)
                    self.model.add(start_var <= int_end - talk.duration + 1).only_enforce_if(in_this_venue)

                    # We use an implication rather than directly referring to
                    # "active" because otherwise it would be impossible to have
                    # more than one possible time window in a given venue
                    self.model.add_implication(in_this_venue, active)
                    in_interval_vars.append(in_this_venue)

                # At least one of the venue's intervals must be active
                #
                # This is unpacked rather than concatenated because otherwise
                # you end up in mypy hell due to ortools internal types
                self.model.add_bool_or([active.Not(), *in_interval_vars])

            # Exactly one venue must be chosen for a talk
            self.model.add(cp_model.LinearExpr.sum(venue_active_vars) == 1)

        # No two talks may overlap in the same venue
        for _venue, intervals in sorted(venue_intervals.items()):
            self.model.add_no_overlap(intervals)

        # And a speaker cannot give multiple talks simultaneously
        talks_by_speaker: dict[SpeakerID, list[TalkID]] = {}
        for talk in talks:
            # Ensure we've not filtered the talk for being impossible
            if talk.id in talk_intervals:
                for speaker in sorted(talk.speakers):
                    talks_by_speaker.setdefault(speaker, []).append(talk.id)

        for _speaker, conflicts in sorted(talks_by_speaker.items()):
            if len(conflicts) > 1:
                self.model.add_no_overlap([talk_intervals[talk_id] for talk_id in conflicts])

        ## Optimisation objective generation
        #
        # This is a maximisation objective where all possible solutions to the
        # previous problem are evaluated. This aims to place talks within the
        # preferred Intervals and venues specified, and minimise changes from
        # the previous schedule needed to satisfy the current constraints.

        obj_vars: list[cp_model.LinearExprT] = []
        obj_scores: list[int] = []

        # Maximise the number of things in their preferred venues (for putting
        # big talks on big stages)
        VENUE_WEIGHT_CAP = 5
        max_venue_weight = max((vt.venue_weight for talk in talks for vt in talk.venue_intervals), default=1)
        for talk in talks:
            for vt in talk.venue_intervals:
                venue_var = self.talk_venue_active_vars.get((talk.id, vt.venue))
                if vt.venue_weight <= 0 or venue_var is None:
                    continue
                weight = round(vt.venue_weight / max_venue_weight * VENUE_WEIGHT_CAP)
                if weight > 0:
                    obj_vars.append(venue_var)
                    obj_scores.append(weight * talk.duration)

        # Maximise the number of things in their preferred slots. This is
        # frustratingly ugly because while or-tools provides clean interfaces
        # for restricting Interval overlaps, it doesn't provide a clean
        # interface for optimising Interval overlaps.
        #
        # To achieve this we create two Int vars representing the possible
        # start and end slots of the talk, bounded by the maximum slot the talk
        # could be placed in, then score the possibility based on the amount of
        # slots that are within the preferred interval x10.
        #
        # More explanation of Interval relationships and overlaps:
        # * https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md#time-relations-between-intervals
        # * https://github.com/google/or-tools/blob/stable/ortools/sat/docs/scheduling.md#detecting-if-two-intervals-overlap
        for talk in talks:
            if talk.id not in self.talk_slot_vars:
                continue

            start = self.talk_slot_vars[talk.id]
            start_max = talk_slot_max[talk.id]
            for i, (int_start, int_end) in enumerate(talk.preferred_intervals):
                start_var = self.model.new_int_var(
                    int_start, max(start_max, int_start), f"pref_start_{talk.id}_{i}"
                )
                self.model.add_max_equality(start_var, [start, int_start])

                end_var = self.model.new_int_var(int_start, int_end + 1, f"pref_end_{talk.id}_{i}")
                self.model.add_min_equality(end_var, [start + talk.duration, int_end + 1])

                overlap_var = self.model.new_int_var(
                    0, min(talk.duration, int_end - int_start + 1), f"pref_overlap_{talk.id}_{i}"
                )
                self.model.add_max_equality(overlap_var, [end_var - start_var, 0])

                obj_vars.append(overlap_var)
                obj_scores.append(10)

        # Maximise the number of things staying in the same slot and venue, as
        # we always want to make the minimal changes to the schedule when
        # altering talk constraints
        for talk in talks:
            # We're only considering talks with an existing scheduled time
            if not talk.start or not talk.venue:
                continue

            if talk.id not in self.talk_slot_vars:
                continue

            start = self.talk_slot_vars[talk.id]

            # Attempt to keep talks in the same slot, or within a two-hour
            # window of the current slot. The cost of the slot move grows
            # proportionally with the number of slots it is moved, until it
            # hits the two hour window and is capped. After that we may as well
            # move them anywhere as it is a major schedule change.
            max_displacement = 6 * 2  # Two hours
            abs_diff_var = self.model.new_int_var(
                0, talk_slot_max[talk.id] + abs(talk.start), f"talk_slot_abs_diff_{talk.id}_{talk.start}"
            )
            self.model.add_max_equality(abs_diff_var, [start - talk.start, talk.start - start])
            diff_var = self.model.new_int_var(0, max_displacement, f"talk_slot_diff_{talk.id}_{talk.start}")
            self.model.add_min_equality(diff_var, [abs_diff_var, max_displacement])
            obj_vars.append(diff_var)
            obj_scores.append(-(talk.duration + 10))

            # Attempt to keep talks in the same venue. We prefer to keep talks
            # in the same timeslot over the same venue, so note that the score
            # is artificially increased by +10 above otherwise they would score
            # equally.
            if (talk.id, talk.venue) in self.talk_venue_active_vars:
                obj_vars.append(self.talk_venue_active_vars[(talk.id, talk.venue)])
                obj_scores.append(talk.duration)

        # Optionally discourage groups of talks from running at the same time.
        #
        # This breaks down into two separate user-specified sections:
        # - Conflicts, for nudging specific talks to be run at separate times
        # - Tags, for ensuring topic diversty across time ranges
        #
        # This is modelled as a set of _optional_ intervals that are not
        # allowed to overlap, with a positive weight for each optional interval
        # that is active - thus rewarding the most non-overlapping intervals
        content_duration = {talk.id: talk.content_duration for talk in talks}

        def discourage_concurrency(talk_ids: list[TalkID], weight: int, name: str) -> None:
            intervals: list[cp_model.IntervalVar] = []
            for talk_id in talk_ids:
                start = self.talk_slot_vars[talk_id]
                duration = content_duration[talk_id]
                present = self.model.new_bool_var(f"{name}_present_{talk_id}")
                intervals.append(
                    self.model.new_optional_interval_var(
                        start, duration, start + duration, present, f"{name}_interval_{talk_id}"
                    )
                )
                obj_vars.append(present)
                obj_scores.append(weight)
            self.model.add_no_overlap(intervals)

        # Conflicts
        #
        # A conflict is a group of two or more talks with a weight. The weight
        # is rescaled between 1-CONFLICT_WEIGHT_CAP to prevent someone giving a
        # conflict weight of 999999 overriding everything in the solver
        # optimisation by accident. It might be nice to permit this one day.
        #
        # Generally a good idea is to pass the number of attendees who would be
        # affected by a conflict as the weight.
        CONFLICT_WEIGHT_CAP = 15
        max_weight = max((conflict.weight for conflict in self.problem.conflicts), default=1)
        sorted_conflicts = sorted(self.problem.conflicts, key=lambda c: (sorted(c.talks), c.weight))
        for conflict_index, conflict in enumerate(sorted_conflicts):
            group = [talk_id for talk_id in sorted(conflict.talks) if talk_id in self.talk_slot_vars]
            if len(group) >= 2:
                weight = max(1, round(conflict.weight / max_weight * CONFLICT_WEIGHT_CAP))
                discourage_concurrency(group, weight, f"conflict_{conflict_index}")

        # Tags
        #
        # Tags are used to encourage talks to be scheduled at different times
        # from talks that share one or more of the same tags, to create topic
        # diversity across times. They have a very weak weight so will just
        # break score ties in the solver.
        #
        # A talk with multiple tags will score more highly if multiple tags do
        # _not_ overlap, thus meaning we force tags sharing multiple tags apart
        # more strongly
        talks_by_tag: dict[str, list[TalkID]] = {}
        for talk in talks:
            if talk.id in self.talk_slot_vars:
                for tag in sorted(talk.tags):
                    talks_by_tag.setdefault(tag, []).append(talk.id)

        for tag_index, tag in enumerate(sorted(talks_by_tag)):
            if len(talks_by_tag[tag]) >= 2:
                discourage_concurrency(talks_by_tag[tag], 1, f"tag_{tag_index}")

        if obj_vars:
            self.model.maximize(cp_model.LinearExpr.weighted_sum(obj_vars, obj_scores))

        # Anything that is already scheduled is likely to be in a valid slot &
        # venue, and quite probably the optimal one. We also want talks to stay
        # in their slots where possible. Given this, we give the solver a hint
        # that the current slot/venue is a good place to start searching for
        # all of these talks, radically improving performance when the schedule
        # is mostly already scheduled.
        for talk in talks:
            if talk.start is None or talk.venue is None:
                continue
            if talk.id not in self.talk_slot_vars:
                continue
            self.model.add_hint(self.talk_slot_vars[talk.id], talk.start)
            if (talk.id, talk.venue) in self.talk_venue_active_vars:
                self.model.add_hint(self.talk_venue_active_vars[(talk.id, talk.venue)], 1)

    def solve(self, debug: bool = False, max_time_in_seconds: float = 30.0) -> SchedulingSolution:
        t0 = time.monotonic()

        self.log.info("Generating schedule problem...")

        talks = [SlottedTalk(talk, self.problem) for talk in sorted(self.problem.talks, key=lambda t: t.id)]

        self.generate_problem(talks)

        self.log.info(
            "Problem generated (%s variables) in %.3f seconds, attempting to solve...",
            len(self.model.proto.variables),
            time.monotonic() - t0,
        )

        solve_start = time.monotonic()
        self._solver = cp_model.CpSolver()
        self._solver.parameters.num_search_workers = 8
        self._solver.parameters.max_time_in_seconds = max_time_in_seconds
        self._solver.parameters.log_search_progress = debug
        self._solver.parameters.log_to_stdout = debug

        log = self.log

        class SolverCallback(cp_model.CpSolverSolutionCallback):
            def __init__(self):
                super().__init__()
                self._count = 0

            def on_solution_callback(self):
                self._count += 1
                log.info(
                    "Solution %d found: objective=%.0f, elapsed=%.2fs",
                    self._count,
                    self.objective_value,
                    time.monotonic() - solve_start,
                )

        callback = SolverCallback()
        status = self._solver.solve(self.model, callback)
        time_complete = time.monotonic()

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise Unsatisfiable(self._solver.status_name(status))

        self.log.info(
            "Problem solved (%s, %d solutions) in %.2f seconds. Total runtime %.2f seconds.",
            self._solver.status_name(status),
            callback._count,
            time_complete - solve_start,
            time_complete - t0,
        )

        for talk in talks:
            if talk.id not in self.talk_slot_vars:
                continue
            start_val = self._solver.value(self.talk_slot_vars[talk.id])
            # This iterates over all possible venue placement vars to find the
            # one that was actually selected ("active")
            for venue in sorted(self.problem.venues):
                if (talk.id, venue) in self.talk_venue_active_vars and bool(
                    self._solver.value(self.talk_venue_active_vars[(talk.id, venue)])
                ):
                    talk.start = start_val
                    talk.venue = venue
                    break

        return SchedulingSolution(
            talks=[talk.to_talk(self.problem) for talk in talks],
            timings={
                "total": timedelta(seconds=time_complete - t0),
                "solve": timedelta(seconds=time_complete - solve_start),
            },
            solution_type=self._solver.status_name(status),
            variables=len(self.model.proto.variables),
        )
