"""Independent checker for a schedule.csv: hard constraints and the soft penalty.

It reads only the CSV files, never the solver's data structures, so it can
catch solver bugs. Usage: python -m src.verify RESULTS_DIR
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from src.schedule_ga import DAYS, read_csv

MAX_SESSIONS = 20

# Hard constraints, numbered as in requirement.md.
HARD = {
    "room_too_small": "1. room smaller than the section",
    "section_days": "2. a section's two sessions on the same or adjacent days",
    "professor_clash": "3. professor teaches two sessions at once",
    "professor_overload": "3. professor teaches more than 20 sessions",
    "room_unassigned": "4. session without a room (H)",
    "room_closed": "4. session in a room while it is closed",
    "section_clash": "5. section in two rooms at once",
    "room_clash": "6. room holds two sessions at once",
    "section_sessions": "data: section without exactly two sessions",
    "session_index": "data: section session indices must be 1 and 2",
    "invalid_time": "data: day must be Mon-Fri and slot must be 1-6",
    "wrong_period": "data: period or slot differs from the assigned shift",
    "wrong_professor": "data: professor differs from the assignment",
    "not_favorite": "bonus 2: professor teaches a course outside their top 3",
}
SOFT = {
    "G": "idle slots between a professor's first and last session of a day",
    "W": "span of each professor's week, first to last teaching day",
    "M": "days on which a professor teaches mornings and afternoons (weight 2)",
    "C": "per course, sessions in its minority shift",
    "R": "room size minus section size, summed",
    "U": "professors without a top-3 course",
}


@dataclass
class Report:
    hard: dict = field(default_factory=lambda: dict.fromkeys(HARD, 0))
    soft: dict = field(default_factory=lambda: dict.fromkeys(SOFT, 0))

    @property
    def violations(self):
        """Hard violations other than a missing room, which the solver reports as H."""
        return sum(n for key, n in self.hard.items() if key != "room_unassigned")

    @property
    def penalty(self):
        s = self.soft
        return s["G"] + s["W"] + 2 * s["M"] + s["C"] + s["R"] + s["U"]


def verify(rows, sections, rooms, professors):
    """Check schedule rows (dicts of strings, as read from schedule.csv)."""
    report = Report()
    hard, soft = report.hard, report.soft
    room_size = {r["room"]: int(r["size"]) for r in rooms}
    closed = {(r["room"], r["closed_day"], int(r["closed_slot"])) for r in rooms}
    assigned = {(s["course"], s["section"]): s for s in sections}
    favorites = {p["professor"]: {p[f"favorite_{i}"] for i in (1, 2, 3)} for p in professors}

    by_section = defaultdict(list)
    session_indices = defaultdict(list)
    professor_time, room_time, section_time = Counter(), Counter(), Counter()
    professor_days = defaultdict(lambda: defaultdict(list))
    course_shifts = defaultdict(Counter)
    for row in rows:
        key = (row["course"], row["section"])
        professor, room = row["professor"], row["room"]
        day = DAYS.index(row["day"]) if row["day"] in DAYS else -1
        try:
            slot = int(row["slot"])
        except (TypeError, ValueError):
            slot = 0
        session_indices[key].append(row.get("session"))
        valid_time = day >= 0 and 1 <= slot <= 6
        if not valid_time:
            hard["invalid_time"] += 1
        else:
            period = "AM" if slot <= 3 else "PM"
            if row.get("period") != period or (key in assigned and assigned[key]["period"] != period):
                hard["wrong_period"] += 1
        size = int(assigned[key]["registration_size"]) if key in assigned else int(row["registration_size"])
        by_section[key].append(day)
        if valid_time:
            professor_time[professor, day, slot] += 1
            section_time[key, day, slot] += 1
            professor_days[professor][day].append(slot)
            course_shifts[row["course"]][slot >= 4] += 1
        if key not in assigned or assigned[key]["professor"] != professor:
            hard["wrong_professor"] += 1
        if row["course"] not in favorites.get(professor, ()):
            hard["not_favorite"] += 1
        if room == "UNASSIGNED":
            hard["room_unassigned"] += 1
            continue
        if valid_time:
            room_time[room, day, slot] += 1
        if room_size[room] < size:
            hard["room_too_small"] += 1
        else:
            soft["R"] += room_size[room] - size
        if (room, row["day"], slot) in closed:
            hard["room_closed"] += 1

    hard["section_sessions"] = sum(len(by_section.get(key, ())) != 2 for key in assigned)
    hard["section_sessions"] += sum(key not in assigned for key in by_section)
    hard["session_index"] = sum(
        Counter(indices) != Counter(("1", "2")) for indices in session_indices.values())
    hard["section_days"] = sum(len(days) == 2 and abs(days[0] - days[1]) < 2 for days in by_section.values())
    for counter, name in ((professor_time, "professor_clash"), (room_time, "room_clash"),
                          (section_time, "section_clash")):
        hard[name] = sum(n - 1 for n in counter.values() if n > 1)
    hard["professor_overload"] = sum(
        sum(map(len, days.values())) > MAX_SESSIONS for days in professor_days.values())

    for days in professor_days.values():
        teaching = sorted(days)
        soft["W"] += teaching[-1] - teaching[0] + 1
        for slots in days.values():
            unique = set(slots)
            soft["G"] += max(unique) - min(unique) + 1 - len(unique)
            soft["M"] += min(unique) <= 3 < max(unique)
    soft["C"] = sum(min(shifts[False], shifts[True]) for shifts in course_shifts.values())
    soft["U"] = sum(not any(row["course"] in favorites[p] for row in rows if row["professor"] == p)
                    for p in favorites)
    return report


def verify_directory(directory):
    directory = Path(directory)
    return verify(*(read_csv(directory / name) for name in
                    ("schedule.csv", "sections.csv", "rooms.csv", "professors.csv")))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path, help="folder with schedule.csv and the input CSVs")
    args = parser.parse_args()
    report = verify_directory(args.directory)
    print("Hard constraints")
    for key, label in HARD.items():
        print(f"  {report.hard[key]:5}  {label}")
    print("Soft penalty")
    for key, label in SOFT.items():
        print(f"  {key} = {report.soft[key]:4}  {label}")
    print(f"  P = {report.penalty}")
    problems = []
    run_file = args.directory / "run.json"
    if run_file.exists():
        run = json.loads(run_file.read_text(encoding="utf-8"))
        if (run["H"], run["P"]) != (report.hard["room_unassigned"], report.penalty):
            problems.append(f"run.json says H={run['H']}, P={run['P']}; the schedule gives "
                            f"H={report.hard['room_unassigned']}, P={report.penalty}")
    if report.violations:
        problems.append(f"{report.violations} hard-constraint violations")
    result = dict(hard=report.hard, soft=report.soft, P=report.penalty,
                  violations=report.violations, problems=problems)
    (args.directory / "verify.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("OK: every hard constraint holds" if not report.hard["room_unassigned"]
          else f"OK apart from {report.hard['room_unassigned']} sessions without a room")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
