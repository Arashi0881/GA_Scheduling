"""Assign sections to professors from ranked preferences using a genetic algorithm."""
import argparse
import random
import shutil
from collections import Counter, defaultdict, deque
from pathlib import Path

from src.schedule_ga import MAX_SECTIONS, MAX_SHIFT_SECTIONS, ROOT, read_csv, write_csv

SECTION_FIELDS = ("course", "section", "registration_size", "professor", "period")
POPULATION = 28


def augment_flow(graph, source, sink):
    """Add flow to a residual network until no augmenting path remains."""
    total = 0
    while True:
        previous = {source: None}
        queue = deque([source])
        while queue and sink not in previous:
            node = queue.popleft()
            for neighbor, remaining in graph[node].items():
                if remaining and neighbor not in previous:
                    previous[neighbor] = node
                    queue.append(neighbor)
        if sink not in previous:
            return total
        path = []
        node = sink
        while node != source:
            parent = previous[node]
            path.append((parent, node))
            node = parent
        flow = min(graph[a][b] for a, b in path)
        for a, b in path:
            graph[a][b] -= flow
            graph[b][a] += flow
        total += flow


class Assignment:
    def __init__(self, sections, faculty):
        self.sections = sections
        self.professors = []
        self.allowed = defaultdict(dict)
        courses = {row["course"] for row in sections}
        for row in faculty:
            p = row["professor"]
            choices = [row[f"favorite_{i}"] for i in range(1, 4)]
            if p in self.professors:
                raise ValueError(f"{p}: duplicate professor")
            if len(set(choices)) != 3 or set(choices) - courses:
                raise ValueError(f"{p}: expected three distinct courses from the input")
            self.professors.append(p)
            for rank, course in enumerate(choices):
                self.allowed[course][p] = rank
        expected_courses = {f"c{i:02}" for i in range(1, 61)}
        expected_sections = {(c, f"s{i:02}") for c in expected_courses for i in range(1, 9)}
        if len(sections) != 480 or {(r["course"], r["section"]) for r in sections} != expected_sections:
            raise ValueError("Expected eight sections each for courses c01 through c60")
        if set(self.professors) != {f"p{i:02}" for i in range(1, 61)}:
            raise ValueError("Expected professors p01 through p60")
        course_periods = defaultdict(set)
        for row in sections:
            course_periods[row["course"]].add(row["period"])
            if int(row["registration_size"]) not in (0, 1, 2):
                raise ValueError(f"Invalid size for {row['course']}/{row['section']}")
        if any(periods not in ({"AM"}, {"PM"}) for periods in course_periods.values()):
            raise ValueError("Each course must use a single shift, AM or PM")
        self.periods = [row["period"] for row in sections]
        self.owners = [self.allowed[row["course"]] for row in sections]
        self.by_course = defaultdict(list)
        for i, row in enumerate(sections):
            course = row["course"]
            if not self.allowed[course]:
                raise ValueError(f"{course}: no professor lists this course in their top 3")
            self.by_course[course].append(i)

    def initial_gene(self, rng):
        # Randomized maximum flow initializes legal individuals. Each professor
        # must receive one class for the bonus, then may fill up to ten places.
        graph = defaultdict(dict)
        source, sink = "source", "sink"

        def edge(a, b, capacity):
            graph[a][b] = capacity
            graph[b][a] = 0

        courses = list(self.by_course)
        rng.shuffle(courses)
        for course in courses:
            indices = self.by_course[course]
            edge(source, course, len(indices))
            candidates = list(self.allowed[course])
            rng.shuffle(candidates)
            for p in candidates:
                edge(course, (p, self.periods[indices[0]]), len(indices))
        for p in self.professors:
            for period in ("AM", "PM"):
                edge((p, period), p, MAX_SHIFT_SECTIONS)
            edge(p, sink, 1)

        minimum = augment_flow(graph, source, sink)
        if minimum != len(self.professors):
            raise ValueError("Top 3 cannot give every professor at least one section")
        for p in self.professors:
            graph[p][sink] += MAX_SECTIONS - 1
        if minimum + augment_flow(graph, source, sink) != len(self.sections):
            raise ValueError("Top 3 and teaching limits cannot cover all sections")

        gene = [None] * len(self.sections)
        for course, indices in self.by_course.items():
            period = self.periods[indices[0]]
            professors = [p for p in self.allowed[course]
                          for _ in range(graph[p, period][course])]
            rng.shuffle(professors)
            for i, p in zip(indices, professors):
                gene[i] = p
        return gene

    def score(self, gene):
        return sum(owners[p] for owners, p in zip(self.owners, gene))

    def move(self, gene, i, target, totals, shifts):
        current, period = gene[i], self.periods[i]
        if (current == target or totals[current] <= 1 or totals[target] >= MAX_SECTIONS
                or shifts[target, period] >= MAX_SHIFT_SECTIONS):
            return False
        gene[i] = target
        totals[current] -= 1
        totals[target] += 1
        shifts[current, period] -= 1
        shifts[target, period] += 1
        return True

    def crossover(self, left, right, rng):
        child = left.copy()
        totals = Counter(child)
        shifts = Counter(zip(child, self.periods))
        order = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        rng.shuffle(order)
        for i in order:
            if rng.random() < 0.5:
                self.move(child, i, right[i], totals, shifts)
        return child, totals, shifts

    def mutate(self, gene, totals, shifts, rng):
        i = rng.randrange(len(gene))
        candidates = list(self.owners[i])
        rng.shuffle(candidates)
        for target in candidates:
            if self.move(gene, i, target, totals, shifts):
                return

        # At full capacity, swapping two classes in the same shift can
        # change who teaches each course while preserving both workloads.
        p = gene[i]
        eligible = [j for j, other in enumerate(gene)
                    if other != p and self.periods[j] == self.periods[i]
                    and other in self.owners[i] and p in self.owners[j]]
        if eligible:
            j = rng.choice(eligible)
            gene[i], gene[j] = gene[j], gene[i]


def assign(sections, faculty, seed=42, generations=80):
    if generations < 0:
        raise ValueError("Assignment generations must be non-negative")
    problem = Assignment(sections, faculty)
    rng = random.Random(seed)
    population = [problem.initial_gene(rng) for _ in range(POPULATION)]
    history = []
    for generation in range(generations + 1):
        ranked = sorted(((problem.score(gene), gene) for gene in population), key=lambda item: item[0])
        best_score, best = ranked[0]
        history.append((generation, best_score, sum(score for score, _ in ranked) / len(ranked)))
        if generation == generations or best_score == 0:
            return [dict(row, professor=p) for row, p in zip(sections, best)], history
        population = [best, ranked[1][1]]
        while len(population) < POPULATION:
            left, right = (min(rng.sample(ranked, 3), key=lambda item: item[0])[1] for _ in range(2))
            child, totals, shifts = problem.crossover(left, right, rng)
            for _ in range(4):
                problem.mutate(child, totals, shifts, rng)
            population.append(child)


def solve_assignment(source, output, seed=42, generations=80):
    faculty = read_csv(source / "professors.csv")
    sections = read_csv(source / "sections.csv")
    assigned, history = assign(sections, faculty, seed, generations)
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
    write_csv(output / "assignment_history.csv", ("generation", "best_penalty", "mean_penalty"), history)
    print(f"Assigned {len(assigned)} sections with preference penalty {history[-1][1]} "
          f"(initial best {history[0][1]}).")
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "assignment_input")
    parser.add_argument("--out", type=Path, default=ROOT / "assigned_input")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generations", type=int, default=80)
    args = parser.parse_args()
    try:
        solve_assignment(args.input, args.out, args.seed, args.generations)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
