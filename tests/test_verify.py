import copy
import json

import pytest

from src.assign import solve_assignment
from src.schedule_ga import ROOT, read_csv, solve
from src.verify import verify, verify_directory


@pytest.fixture(scope="module")
def solved(tmp_path_factory):
    base = tmp_path_factory.mktemp("verify")
    solve_assignment(ROOT / "input", base / "input")
    out = base / "out"
    solve(base / "input", out, seed=1, variant="flexible", max_evaluations=3000)
    return out


def load(directory):
    return (read_csv(directory / "schedule.csv"), read_csv(directory / "sections.csv"),
            read_csv(directory / "rooms.csv"), read_csv(directory / "professors.csv"))


def test_solver_output_passes_and_soft_score_matches(solved):
    report = verify_directory(solved)
    run = json.loads((solved / "run.json").read_text())
    assert report.violations == 0
    assert report.hard["room_unassigned"] == run["H"]
    assert report.penalty == run["P"]
    for key in "GWMCRU":
        assert report.soft[key] == run[key]


def mutated(solved, change):
    rows, sections, rooms, professors = load(solved)
    rows = copy.deepcopy(rows)
    change(rows, rooms)
    return verify(rows, sections, rooms, professors)


def first_session(rows, index=0):
    """A section's two rows, by the position of its first session in the schedule."""
    row = rows[index]
    other = next(r for r in rows if r is not row and (r["course"], r["section"]) == (row["course"], row["section"]))
    return row, other


def test_adjacent_days_detected(solved):
    def change(rows, _):
        first, second = first_session(rows)
        days = ("Mon", "Tue", "Wed", "Thu", "Fri")
        second["day"] = days[days.index(first["day"]) + 1] if first["day"] != "Fri" else "Thu"
    assert mutated(solved, change).hard["section_days"] >= 1


def test_room_clash_and_professor_clash_detected(solved):
    def change(rows, _):
        a, b = rows[0], next(r for r in rows if r["professor"] != rows[0]["professor"]
                             and (r["day"], r["slot"]) != (rows[0]["day"], rows[0]["slot"]))
        b["day"], b["slot"], b["room"] = a["day"], a["slot"], a["room"]
        c = next(r for r in rows if r["professor"] == a["professor"] and r is not a
                 and (r["day"], r["slot"]) != (a["day"], a["slot"]))
        c["day"], c["slot"] = a["day"], a["slot"]
    report = mutated(solved, change)
    assert report.hard["room_clash"] >= 1
    assert report.hard["professor_clash"] >= 1


def test_small_room_and_closed_room_detected(solved):
    def change(rows, rooms):
        small = next(r["room"] for r in rooms if r["size"] == "0")
        large_section = next(r for r in rows if r["registration_size"] == "2")
        large_section["room"] = small
        closed = rooms[0]
        target = next(r for r in rows if r is not large_section)
        target["room"], target["day"], target["slot"] = closed["room"], closed["closed_day"], closed["closed_slot"]
    report = mutated(solved, change)
    assert report.hard["room_too_small"] >= 1
    assert report.hard["room_closed"] >= 1


def test_overload_missing_session_and_wrong_professor_detected(solved):
    def change(rows, _):
        rows.pop()
        busiest = max({r["professor"] for r in rows}, key=lambda p: sum(r["professor"] == p for r in rows))
        for row in [r for r in rows if r["professor"] != busiest][:6]:
            row["professor"] = busiest
    report = mutated(solved, change)
    assert report.hard["section_sessions"] >= 1
    assert report.hard["professor_overload"] >= 1
    assert report.hard["wrong_professor"] >= 1
