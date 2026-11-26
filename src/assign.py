"""Assign teachers with the original four-course timetable pattern."""
import argparse
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path

from src.schedule_ga import ROOT, read_csv, write_csv

SECTION_FIELDS = ("course", "section", "registration_size", "professor", "period")


@dataclass(frozen=True)
class CourseSplit:
    course: str
    first: str
    first_count: int
    second: str


@dataclass(frozen=True)
class Block:
    courses: tuple[CourseSplit, ...]

    @property
    def members(self):
        return frozenset(split.course for split in self.courses) | frozenset(
            professor for split in self.courses for professor in (split.first, split.second))


def candidate_blocks(favorites, periods, eligible):
    """Build blocks with loads (7,0), (3,6), (0,7) and (6,3)."""
    for left, right in combinations(favorites, 2):
        shared = favorites[left].keys() & favorites[right].keys()
        for morning in sorted(course for course in shared if periods[course] == "AM"):
            for afternoon in sorted(course for course in shared if periods[course] == "PM"):
                for short_am, short_pm in ((left, right), (right, left)):
                    for morning_only in favorites[short_am]:
                        if morning_only == morning or periods[morning_only] != "AM":
                            continue
                        for afternoon_only in favorites[short_pm]:
                            if afternoon_only == afternoon or periods[afternoon_only] != "PM":
                                continue
                            for am_teacher in eligible[morning_only]:
                                if am_teacher in (short_am, short_pm):
                                    continue
                                for pm_teacher in eligible[afternoon_only]:
                                    if pm_teacher in (short_am, short_pm, am_teacher):
                                        continue
                                    yield Block((
                                        CourseSplit(morning_only, am_teacher, 7, short_am),
                                        CourseSplit(morning, short_am, 2, short_pm),
                                        CourseSplit(afternoon_only, pm_teacher, 7, short_pm),
                                        CourseSplit(afternoon, short_pm, 2, short_am),
                                    ))


def cover_blocks(entities, blocks):
    """Select disjoint blocks covering every course and professor once."""
    by_member = defaultdict(list)
    for block in blocks:
        members = block.members
        for member in members:
            by_member[member].append((members, block))

    @lru_cache(maxsize=None)
    def find(remaining):
        if not remaining:
            return ()
        # Try the course or professor with the fewest valid blocks first.
        options = min(([entry for entry in by_member[member] if entry[0] <= remaining]
                       for member in sorted(remaining)), key=len)
        for members, block in options:
            rest = find(remaining - members)
            if rest is not None:
                return (block, *rest)
        return None

    return find(frozenset(entities))


def assign(sections, faculty, seed=42):
    courses = {f"c{i:02}" for i in range(1, 61)}
    expected_sections = {(c, f"s{i:02}") for c in courses for i in range(1, 9)}
    if len(sections) != 480 or {(r["course"], r["section"]) for r in sections} != expected_sections:
        raise ValueError("Expected eight sections each for courses c01 through c60")

    periods = {}
    for row in sections:
        course, period = row["course"], row["period"]
        if period not in ("AM", "PM") or periods.setdefault(course, period) != period:
            raise ValueError(f"{course}: expected one shift (AM or PM) for all eight sections")
        if int(row["registration_size"]) not in (0, 1, 2):
            raise ValueError(f"{course}/{row['section']}: invalid section size")
    if Counter(periods.values()) != {"AM": 30, "PM": 30}:
        raise ValueError("The original pattern requires 30 morning and 30 afternoon courses")

    favorites = {}
    eligible = defaultdict(list)
    for row in faculty:
        professor = row["professor"]
        choices = [row[f"favorite_{rank}"] for rank in (1, 2, 3)]
        if professor in favorites:
            raise ValueError(f"{professor}: duplicate professor")
        if len(set(choices)) != 3 or set(choices) - courses:
            raise ValueError(f"{professor}: expected three distinct courses from the input")
        favorites[professor] = {course: rank for rank, course in enumerate(choices)}
        for course in choices:
            eligible[course].append(professor)
    if set(favorites) != {f"p{i:02}" for i in range(1, 61)}:
        raise ValueError("Expected professors p01 through p60")

    candidates = list(candidate_blocks(favorites, periods, eligible))
    random.Random(seed).shuffle(candidates)

    def preference_penalty(block):
        return sum(split.first_count * favorites[split.first][split.course]
                   + (8 - split.first_count) * favorites[split.second][split.course]
                   for split in block.courses)

    candidates.sort(key=preference_penalty)
    blocks = cover_blocks(courses | favorites.keys(), candidates)
    if blocks is None:
        raise ValueError("No complete assignment fits the original 7/0, 0/7, 3/6 and 6/3 "
                         "workloads with these top-three lists and course shifts")

    splits = {split.course: split for block in blocks for split in block.courses}
    assigned = []
    for row in sections:
        split = splits[row["course"]]
        professor = split.first if int(row["section"][1:]) <= split.first_count else split.second
        assigned.append(dict(row, professor=professor))
    return assigned, blocks, sum(map(preference_penalty, blocks))


def solve_assignment(source, output, seed=42):
    faculty = read_csv(source / "professors.csv")
    sections = read_csv(source / "sections.csv")
    assigned, blocks, penalty = assign(sections, faculty, seed)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("professors.csv", "rooms.csv"):
        if (source / name).resolve() != (output / name).resolve():
            shutil.copyfile(source / name, output / name)
    write_csv(output / "sections.csv", SECTION_FIELDS,
              ([row[field] for field in SECTION_FIELDS] for row in assigned))
    loads = Counter((row["professor"], row["period"]) for row in assigned)
    write_csv(output / "teaching_load.csv", ("professor", "am_sections", "pm_sections", "weekly_sessions"),
              ((p, loads[p, "AM"], loads[p, "PM"], 2 * (loads[p, "AM"] + loads[p, "PM"]))
               for p in sorted(row["professor"] for row in faculty)))
    write_csv(output / "assignment_blocks.csv",
              ("block", "course", "first_professor", "first_sections", "second_professor", "second_sections"),
              ((index, split.course, split.first, split.first_count, split.second, 8 - split.first_count)
               for index, block in enumerate(blocks, 1) for split in block.courses))
    print(f"Assigned {len(assigned)} sections in {len(blocks)} blocks. Preference penalty: {penalty}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "input")
    parser.add_argument("--out", type=Path, default=ROOT / "assigned_input")
    parser.add_argument("--seed", type=int, default=42, help="tie-breaking seed for valid blocks")
    args = parser.parse_args()
    try:
        solve_assignment(args.input, args.out, args.seed)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
