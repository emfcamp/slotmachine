import json
from pathlib import Path

import pytest

from slotmachine import SchedulingProblem, SlotMachine

from .test_slotmachine import assert_solution_looks_reasonable

TEST_JSON = [
    pytest.param("unscheduled_easy.json"),
    pytest.param("unscheduled_hard.json"),
    pytest.param("scheduled_hard.json", marks=pytest.mark.slow),
    pytest.param("unscheduled_very_hard.json", marks=pytest.mark.slow),
]


@pytest.mark.parametrize("filename", TEST_JSON)
def test_sample(filename):
    file = Path(__file__).parent / ".." / "sample_schedules" / filename
    with file.open() as f:
        data = json.load(f)

        problem = SchedulingProblem.from_dict(data)

    slotmachine = SlotMachine(problem)
    solution = slotmachine.solve()
    assert_solution_looks_reasonable(problem, solution)
