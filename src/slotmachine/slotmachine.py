import logging
import time

from ortools.sat.python import cp_model

from .data import SchedulingProblem, SchedulingSolution, SpeakerID, TalkID, VenueID
from .slots import Slot, SlottedTalk


class Unsatisfiable(Exception):
    pass


class SlotMachine:
    def __init__(self, problem: SchedulingProblem) -> None:
        self.log = logging.getLogger(__name__)
        self.problem = problem

        # Vars representing the selected talk slot and venue
        self.talk_slot_vars: dict[TalkID, cp_model.IntVar] = {}
        self.talk_venue_active_vars: dict[tuple[TalkID, VenueID], cp_model.IntVar] = {}

    def generate_problem(self, venues, talks: list[SlottedTalk]) -> None:
        self.model = cp_model.CpModel()
        self.talk_slot_vars = {}
        self.talk_venue_active_vars = {}

        venue_intervals: dict[VenueID, list[cp_model.IntervalVar]] = {v: [] for v in venues}
        talk_intervals: dict[TalkID, cp_model.IntervalVar] = {}
        talk_slot_max: dict[TalkID, Slot] = {}

        ## Main constraint problem generation
        #
        # This ensures that talks are placed into one venue at a time they are
        # permitted without clashing or forcing people to be in multiple places
        # at once. It does _not_ ensure that we don't totally regenerate the
        # existing schedule, or optimise the schedule in any way.

        for talk in talks:
            # Calculate start slots that a talk can actually be in, filtering
            # intervals to remove any that are too small
            allowed_intervals = [
                [int_start, int_end - talk.duration + 1]
                for int_start, int_end in talk.allowed_intervals
                if int_end - int_start + 1 >= talk.duration
            ]

            # If we don't have any intervals, or any intervals large enough to
            # fit this talk, or no venues specified exist, create a variable
            # that cannot possibly be satisfied for warning purposes. We do
            # this because otherwise the valid talk domain or venues would end
            # up being empty and instead of failing to solve the talk would
            # just be ignored.
            if not allowed_intervals or not talk.allowed_venues:
                oh_no_var = self.model.new_bool_var(f"_impossible_{talk.id}")
                self.model.add(oh_no_var == 1)
                self.model.add(oh_no_var == 0)
                continue

            # The highest slot a talk can occupy, used later for setting
            # variable search bounds
            talk_slot_max[talk.id] = max(interval[1] for interval in allowed_intervals)

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
            for venue in talk.allowed_venues:
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

            # Exactly one venue must be chosen for a talk
            self.model.add(cp_model.LinearExpr.sum(venue_active_vars) == 1)

        # No two talks may overlap in the same venue
        for intervals in venue_intervals.values():
            if intervals:
                self.model.add_no_overlap(intervals)

        # And a speaker cannot give multiple talks simultaneously
        talks_by_speaker: dict[SpeakerID, list[TalkID]] = {}
        for talk in talks:
            # Ensure we've not filtered the talk for being impossible
            if talk.id in talk_intervals:
                for speaker in talk.speakers:
                    talks_by_speaker.setdefault(speaker, []).append(talk.id)

        for conflicts in talks_by_speaker.values():
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
        for talk in talks:
            for venue in talk.preferred_venues:
                if (talk.id, venue) in self.talk_venue_active_vars:
                    obj_vars.append(self.talk_venue_active_vars[(talk.id, venue)])
                    obj_scores.append(5 * talk.duration)

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
                0, max(talk_slot_max[talk.id], talk.start), f"talk_slot_abs_diff_{talk.id}_{talk.start}"
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

        if obj_vars:
            self.model.maximize(cp_model.LinearExpr.weighted_sum(obj_vars, obj_scores))

    def solve(self, debug: bool = False) -> SchedulingSolution:
        t0 = time.time()

        self.log.info("Generating schedule problem...")

        talks = [SlottedTalk(talk, self.problem) for talk in self.problem.talks]

        self.generate_problem(self.problem.venues, talks)

        self.log.info(
            "Problem generated (%s variables) in %.3f seconds, attempting to solve...",
            len(self.model.proto.variables),
            time.time() - t0,
        )

        solve_start = time.time()
        self._solver = cp_model.CpSolver()
        self._solver.parameters.num_search_workers = 8
        self._solver.parameters.max_time_in_seconds = 30.0
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
                    time.time() - solve_start,
                )

        callback = SolverCallback()
        status = self._solver.solve(self.model, callback)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise Unsatisfiable()

        self.log.info(
            "Problem solved (%s, %d solutions) in %.2f seconds. Total runtime %.2f seconds.",
            self._solver.status_name(status),
            callback._count,
            time.time() - solve_start,
            time.time() - t0,
        )

        for talk in talks:
            if talk.id not in self.talk_slot_vars:
                continue
            start_val = self._solver.value(self.talk_slot_vars[talk.id])
            # This iterates over all possible venue placement vars to find the
            # one that was actually selected ("active")
            for venue in self.problem.venues:
                if (talk.id, venue) in self.talk_venue_active_vars and bool(
                    self._solver.value(self.talk_venue_active_vars[(talk.id, venue)])
                ):
                    talk.start = start_val
                    talk.venue = venue
                    break

        return SchedulingSolution(talks=[talk.to_talk(self.problem) for talk in talks])
