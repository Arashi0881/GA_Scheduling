"""Hybrid genetic timetabling for the supplied 60-course instance. Python 3.10+."""
import argparse
import csv
import hashlib
import json
import platform
import random
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations, product
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parent
if ROOT.name == "src":
    ROOT = ROOT.parent
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
HARD_WEIGHT = 10_000
LOWER_BOUND = 360
POPULATION = 28
LOCAL_ATTEMPTS = 420
MAX_GENERATIONS=450
FLEXIBLE_EVALUATIONS = 200_000
VARIANTS = ("plain", "hybrid", "flexible")
INPUT_FILES = ("rooms.csv", "professors.csv", "sections.csv")
MAX_SECTIONS = 10
MAX_SHIFT_SECTIONS = len(DAYS) * 3 // 2  # Two slots per section, three slots per day and shift.


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)


@dataclass(frozen=True)
class Section:
    course: str
    name: str
    size: int
    shift: int


class Instance:
    def __init__(self, directory):
        faculty = read_csv(directory / "professors.csv")
        self.professors = [row["professor"] for row in faculty]
        if len(self.professors) != 60 or set(self.professors) != {f"p{i:02}" for i in range(1, 61)}:
            raise ValueError("Expected professors p01 through p60 exactly once.")
        courses = {f"c{i:02}" for i in range(1, 61)}
        favorites = {}
        for row in faculty:
            professor = row["professor"]
            choices = {row[f"favorite_{i}"] for i in (1, 2, 3)}
            if len(choices) != 3:
                raise ValueError(f"{professor}: duplicate favorite course")
            if choices - courses:
                raise ValueError(f"{professor}: unknown favorite course {sorted(choices - courses)}")
            favorites[professor] = choices
        by_professor = defaultdict(list)
        course_shifts = defaultdict(set)
        keys = set()
        for row in read_csv(directory / "sections.csv"):
            professor = row.get("professor")
            if not professor:
                raise ValueError("Sections need a professor. Run python -m src.assign first.")
            shift = ("AM", "PM").index(row["period"])
            s = Section(row["course"], row["section"], int(row["registration_size"]), shift)
            key = (s.course, s.name)
            if key in keys or s.course not in favorites.get(professor, ()) or s.size not in (0, 1, 2):
                raise ValueError(f"Invalid section assignment for {professor}: {key}")
            keys.add(key)
            by_professor[professor].append(s)
            course_shifts[s.course].add(shift)
        expected = {(f"c{c:02}", f"s{s:02}") for c in range(1, 61) for s in range(1, 9)}
        if keys != expected or any(len(shifts) != 1 for shifts in course_shifts.values()):
            raise ValueError("Expected 60 single-shift courses with eight sections each.")
        self.sections = [by_professor[p] for p in self.professors]
        self.groups = []
        legacy_layout = True
        for professor, sections in zip(self.professors, self.sections):
            shifts = [tuple(i for i, s in enumerate(sections) if s.shift == h) for h in (0, 1)]
            signature = sorted(map(len, shifts))
            if not 1 <= len(sections) <= MAX_SECTIONS or signature[-1] > MAX_SHIFT_SECTIONS:
                raise ValueError(f"{professor}: expected 1–10 sections total and at most 7 in each shift.")
            legacy_layout &= signature in ([0, 7], [3, 6])
            self.groups.append(shifts)
        # The original templates have constant calendar cost. Score the actual
        # calendar for other workloads, even with the plain or hybrid operators.
        self.calendar_penalty = LOWER_BOUND if legacy_layout else None
        rooms = read_csv(directory / "rooms.csv")
        if {r["room"] for r in rooms} != {f"rm{i:02}" for i in range(1, 36)} or len(rooms) != 35:
            raise ValueError("Expected 35 distinct rooms.")
        self.available = [[[] for _ in range(3)] for _ in range(30)]
        for row in rooms:
            day = DAYS.index(row["closed_day"])
            slot, size = int(row["closed_slot"]), int(row["size"])
            if not 1 <= slot <= 6 or size not in (0, 1, 2):
                raise ValueError(f"Invalid room: {row}")
            closed = day * 6 + slot - 1
            for time in range(30):
                if time != closed:
                    self.available[time][size].append(row["room"])
        self.capacity = [tuple(map(len, rooms_at_time)) for rooms_at_time in self.available]


@lru_cache(maxsize=None)
def pair_patterns(degrees):
    """All multisets of legal day pairs matching a shift's meeting counts."""
    if not any(degrees):
        return ((),)
    first = next(i for i, n in enumerate(degrees) if n)
    patterns = set()
    for other in range(first + 2, 5):
        if not degrees[other]:
            continue
        rest = list(degrees)
        rest[first] -= 1
        rest[other] -= 1
        for suffix in pair_patterns(tuple(rest)):
            patterns.add(tuple(sorted(((first, other),) + suffix)))
    return tuple(sorted(patterns))


LEGAL_DAYS = tuple((a, b) for a, b in combinations(range(5), 2) if b - a >= 2)


@lru_cache(maxsize=None)
def shift_degrees(section_count):
    return tuple(degrees for degrees in product(range(4), repeat=len(DAYS))
                 if sum(degrees) == 2 * section_count and pair_patterns(degrees))


def new_gene(instance, p, rng):
    groups = instance.groups[p]
    degrees = [[0] * 5 for _ in range(2)]
    if instance.calendar_penalty is None:
        options = [shift_degrees(len(indices)) for indices in groups]
        proposals = [[rng.choice(values) for values in options] for _ in range(4)]

        def day_penalty(candidate):
            morning, afternoon = candidate
            days = [day for day, (am, pm) in enumerate(zip(morning, afternoon)) if am or pm]
            mixed = sum(bool(am and pm) for am, pm in zip(morning, afternoon))
            return days[-1] - days[0] + 1 + 2 * mixed

        degrees = min(proposals, key=day_penalty)
    elif len(instance.sections[p]) == 7:
        shift = 0 if groups[0] else 1
        degrees[shift] = [3] * 5
        degrees[shift][rng.randrange(5)] = 2
    else:
        short = 0 if len(groups[0]) == 3 else 1
        a, b = rng.choice(LEGAL_DAYS)
        degrees[short][a] = degrees[short][b] = 3
        degrees[1 - short] = [3] * 5
        degrees[1 - short][rng.choice((a, b))] = 0
    gene = [None] * len(instance.sections[p])
    for shift, indices in enumerate(groups):
        if not indices:
            continue
        pairs = list(rng.choice(pair_patterns(tuple(degrees[shift]))))
        rng.shuffle(pairs)
        slots = []
        for day, count in enumerate(degrees[shift]):
            start = 6 * day + 3 * shift
            if instance.calendar_penalty is None and count and degrees[1 - shift][day]:
                if shift == 0:
                    start += 3 - count
            elif count == 2:
                start += rng.randrange(2)
            free = list(range(start, start + count))
            rng.shuffle(free)
            slots.append(free)
        for i, (a, b) in zip(indices, pairs):
            gene[i] = (slots[a].pop(), slots[b].pop())
    return tuple(gene)


def mutate(instance, p, gene, rng):
    if rng.randrange(3) == 0:
        return new_gene(instance, p, rng)
    groups = [g for g in instance.groups[p] if len(g) >= 2]
    if not groups:
        return new_gene(instance, p, rng)
    indices = rng.choice(groups)
    i, j = rng.sample(indices, 2)
    changed = list(gene)
    if rng.randrange(2):
        changed[i], changed[j] = gene[j], gene[i]
    else:
        common_days = [(a, b) for a in (0, 1) for b in (0, 1)
                       if gene[i][a] // 6 == gene[j][b] // 6]
        if not common_days:
            return gene
        a, b = rng.choice(common_days)
        first, second = list(gene[i]), list(gene[j])
        first[a], second[b] = second[b], first[a]
        changed[i], changed[j] = tuple(first), tuple(second)
    return tuple(changed)


@lru_cache(maxsize=100000)
def room_penalty(capacity, small, medium, large):
    """Aggregate version of the room decoder. Allocate scarce large rooms first."""
    r0, r1, r2 = capacity
    missing = max(0, large - r2)
    r2 = max(0, r2 - large)
    medium_overflow = max(0, medium - r1)
    medium_in_large = min(medium_overflow, r2)
    missing += medium_overflow - medium_in_large
    small_overflow = max(0, small - r0)
    small_in_medium = min(small_overflow, max(0, r1 - medium))
    small_in_large = min(small_overflow - small_in_medium, r2 - medium_in_large)
    missing += small_overflow - small_in_medium - small_in_large
    return HARD_WEIGHT * missing + medium_in_large + small_in_medium + 2 * small_in_large


def add_gene(load, sections, gene, sign):
    for section, (first, second) in zip(sections, gene):
        load[first][section.size] += sign
        load[second][section.size] += sign


@lru_cache(maxsize=32768)
def calendar_components(gene):
    slots = [[] for _ in DAYS]
    for pair in gene:
        for time in pair:
            slots[time // 6].append(time % 6)
    days = [i for i, values in enumerate(slots) if values]
    gaps = sum(max(slots[i]) - min(slots[i]) + 1 - len(slots[i]) for i in days)
    mixed = sum(min(slots[i]) < 3 <= max(slots[i]) for i in days)
    return gaps, days[-1] - days[0] + 1, mixed


def calendar_cost(gene):
    gaps, span, mixed = calendar_components(gene)
    return gaps + span + 2 * mixed


def total_cost(instance, load, calendar):
    return calendar + sum(
        room_penalty(capacity, *demand) for capacity, demand in zip(instance.capacity, load))


def flexible_move(instance, genes, load, room_costs, rng):
    # Focus most proposals on shortages. A spare room for a given class size
    # requires spare cumulative capacity at every threshold up to that size.
    shortages = [t for t, cost in enumerate(room_costs) if cost >= HARD_WEIGHT]
    target = rng.choice(shortages) if shortages and rng.random() < 0.9 else None
    if target is None:
        p = rng.randrange(len(genes))
        if rng.random() < 0.5:
            return p, mutate(instance, p, genes[p], rng)
        i = rng.randrange(len(genes[p]))
        target = rng.choice(genes[p][i])
    else:
        options = [(p, i) for p, gene in enumerate(genes)
                   for i, pair in enumerate(gene) if target in pair]
        p, i = rng.choice(options)
    gene = genes[p]
    section = instance.sections[p][i]
    other = next(t for t in gene[i] if t != target)
    occupied = {t for j, pair in enumerate(gene) if j != i for t in pair}
    times = [t for t in range(30) if t not in occupied and (t % 6) // 3 == section.shift]

    def spare(t):
        return all(sum(load[t][k:]) < sum(instance.capacity[t][k:])
                   for k in range(section.size + 1))

    available = [t for t in times if t != target and spare(t)]
    legal = [t for t in available if abs(t // 6 - other // 6) >= 2]
    if legal:
        pair = tuple(sorted((rng.choice(legal), other)))
    else:
        pairs = [(a, b) for a, b in combinations(available, 2) if b // 6 - a // 6 >= 2]
        if pairs:
            pair = rng.choice(pairs)
        else:
            # A neutral move can make room for a later targeted move.
            swaps = [(t, j) for j, previous in enumerate(gene) if j != i for t in previous
                     if (t % 6) // 3 == section.shift and abs(t // 6 - other // 6) >= 2
                     and all(abs(target // 6 - u // 6) >= 2 for u in previous if u != t)]
            if swaps and rng.random() < 0.75:
                t, j = rng.choice(swaps)
                changed = list(gene)
                changed[i] = tuple(sorted((t, other)))
                changed[j] = tuple(sorted(target if u == t else u for u in gene[j]))
                return p, tuple(changed)
            fallback = [t for t in times if t != target and abs(t // 6 - other // 6) >= 2]
            if not fallback:
                return p, mutate(instance, p, gene, rng)
            pair = tuple(sorted((other, rng.choice(fallback))))
    changed = list(gene)
    changed[i] = pair
    return p, tuple(changed)


@dataclass
class Candidate:
    cost: int
    genes: list


@dataclass
class Progress:
    limit: int | None
    used: int = 0
    first_feasible: int | None = None
    best: Candidate | None = None
    reason: str = "generations"

    def record(self, cost, genes):
        self.used += 1
        if cost < HARD_WEIGHT and self.first_feasible is None:
            self.first_feasible = self.used
        if self.best is None or cost < self.best.cost:
            self.best = Candidate(cost, genes.copy())

    def budget_stop(self):
        if self.limit is None:
            return False
        if self.best is not None and self.best.cost == LOWER_BOUND:
            self.reason = "bound"
            return True
        if self.used == self.limit:
            self.reason = "evaluations"
            return True
        return False


def evaluate(instance, genes, rng, attempts=0, *, flexible=False, progress=None):
    load = [[0, 0, 0] for _ in range(30)]
    for sections, gene in zip(instance.sections, genes):
        add_gene(load, sections, gene, 1)
    variable_calendar = flexible or instance.calendar_penalty is None
    calendar = sum(map(calendar_cost, genes)) if variable_calendar else instance.calendar_penalty
    room_costs = [room_penalty(capacity, *demand)
                  for capacity, demand in zip(instance.capacity, load)]
    cost = calendar + sum(room_costs)
    if progress is not None:
        progress.record(cost, genes)
    for _ in range(attempts):
        if cost == LOWER_BOUND or (progress is not None and progress.budget_stop()):
            break
        if flexible:
            p, new = flexible_move(instance, genes, load, room_costs, rng)
        else:
            p = rng.randrange(len(genes))
            new = mutate(instance, p, genes[p], rng)
        old = genes[p]
        if new == old:
            continue
        deltas = defaultdict(int)
        for section, previous, proposed in zip(instance.sections[p], old, new):
            if previous != proposed:
                for t in previous:
                    deltas[t, section.size] -= 1
                for t in proposed:
                    deltas[t, section.size] += 1
        affected = set()
        for (t, size), delta in deltas.items():
            if delta:
                load[t][size] += delta
                affected.add(t)
        calendar_delta = calendar_cost(new) - calendar_cost(old) if variable_calendar else 0
        changed_costs = {t: room_penalty(instance.capacity[t], *load[t]) for t in affected}
        trial = cost + calendar_delta + sum(value - room_costs[t] for t, value in changed_costs.items())
        if trial <= cost:
            genes[p] = new
            cost = trial
            for t, value in changed_costs.items():
                room_costs[t] = value
        else:
            for (t, size), delta in deltas.items():
                load[t][size] -= delta
        # A rejected proposal cannot beat the already recorded incumbent.
        if progress is not None:
            progress.record(trial, genes)
    return Candidate(cost, genes)


def fitness(cost):
    return 1 / (1 + cost / HARD_WEIGHT)


def evolve(instance, seed, generations, *, variant="hybrid", progress=None):
    rng = random.Random(seed)
    n = len(instance.professors)
    progress = progress if progress is not None else Progress(None)
    flexible = variant == "flexible"
    attempts = 0 if variant == "plain" else LOCAL_ATTEMPTS
    population = []
    for _ in range(POPULATION):
        if progress.budget_stop():
            break
        genes = [new_gene(instance, p, rng) for p in range(n)]
        population.append(evaluate(instance, genes, rng, progress=progress))
    history = []
    generation = 0
    partial = len(population) < POPULATION
    while True:
        population.sort(key=lambda candidate: candidate.cost)
        best = population[0]
        missing, soft = divmod(best.cost, HARD_WEIGHT)
        history.append((generation, fitness(best.cost), fmean(fitness(c.cost) for c in population),
                        missing, soft, progress.used, "partial" if partial else "full", len(population)))
        if generation == 0 or history[-1][3:5] != history[-2][3:5]:
            print(f"Generation {generation:3}: missing={missing}, soft={soft}", flush=True)
        if best.cost == LOWER_BOUND:
            progress.reason = "bound"
            return progress.best, history
        if progress.budget_stop() or generation == generations:
            return progress.best, history
        children = population[:2]
        while len(children) < POPULATION and not progress.budget_stop():
            parents = [min(rng.choices(population, k=3), key=lambda c: c.cost) for _ in range(2)]
            genes = []
            for p in range(n):
                parent = parents[1] if rng.random() < 0.2 else parents[0]
                gene = parent.genes[p]
                genes.append(mutate(instance, p, gene, rng) if rng.randrange(n) == 0 else gene)
            children.append(evaluate(instance, genes, rng, attempts,
                                     flexible=flexible, progress=progress))
        partial = len(children) < POPULATION
        population = children + population[2:2 + POPULATION - len(children)]
        generation += 1


def decode(instance, candidate):
    events = defaultdict(list)
    for p, (sections, gene) in enumerate(zip(instance.sections, candidate.genes)):
        for section, pair in zip(sections, gene):
            for session, time in enumerate(sorted(pair), 1):
                events[time].append((section, instance.professors[p], session))
    for time in range(30):
        free = [list(reversed(group)) for group in instance.available[time]]
        for section, professor, session in sorted(events[time], key=lambda e: -e[0].size):
            size = next((s for s in range(section.size, 3) if free[s]), -1)
            room = free[size].pop() if size >= 0 else "UNASSIGNED"
            yield (section.course, section.name, session, professor, DAYS[time // 6],
                   time % 6 + 1, ("AM", "PM")[section.shift], room, section.size, size)


SCHEDULE_FIELDS = ("course", "section", "session", "professor", "day", "slot",
                   "period", "room", "registration_size", "room_size")


def solve(input_dir, output_dir, seed=42, generations=None, *, variant="hybrid",
          max_evaluations=None, dataset_id=None):
    if variant not in VARIANTS:
        raise ValueError(f"Unknown variant: {variant}")
    if generations is not None and generations < 0:
        raise ValueError("generations must be non-negative")
    if max_evaluations is not None:
        if generations is not None or max_evaluations < POPULATION:
            raise ValueError("Use at least 28 evaluations and omit generations")
    elif generations is None:
        if variant == "flexible":
            max_evaluations = FLEXIBLE_EVALUATIONS
        else:
            generations = MAX_GENERATIONS
    instance = Instance(input_dir)
    progress = Progress(max_evaluations)
    best, history = evolve(instance, seed, generations, variant=variant, progress=progress)
    rows = list(decode(instance, best))
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in INPUT_FILES:
        source, target = input_dir / name, output_dir / name
        content = source.read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
        if source.resolve() != target.resolve():
            target.write_bytes(content)
    write_csv(output_dir / "schedule.csv", SCHEDULE_FIELDS, rows)
    write_csv(output_dir / "fitness.csv",
              ("generation", "best_fitness", "mean_fitness", "best_missing", "best_soft_penalty",
               "evaluations", "snapshot", "population_count"), history)
    gaps, span, mixed = map(sum, zip(*(calendar_components(gene) for gene in best.genes)))
    slack = sum(row[-1] - row[-2] for row in rows if row[-1] >= 0)
    missing, soft = divmod(best.cost, HARD_WEIGHT)
    if gaps + span + 2 * mixed + slack != soft or sum(row[-1] == -1 for row in rows) != missing:
        raise RuntimeError("Decoded schedule does not match solver cost")
    metadata = dict(dataset_id=dataset_id or input_dir.resolve().name, input_sha256=hashes,
                    variant=variant, seed=seed, python_version=platform.python_version(),
                    solver_version="2" if instance.calendar_penalty is not None else "4",
                    max_evaluations=max_evaluations, generations=generations,
                    evaluations_used=progress.used, first_feasible_evaluation=progress.first_feasible,
                    stop_reason=progress.reason, H=missing, G=gaps, W=span, M=mixed, C=0, R=slack,
                    U=0, P=soft, fitness=fitness(best.cost), proven_lower_bound=LOWER_BOUND)
    (output_dir / "run.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return best, history


def solver_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--input", type=Path, default=ROOT / "input")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--variant", choices=VARIANTS, default="hybrid")
    limits = parser.add_mutually_exclusive_group()
    limits.add_argument("--generations", type=int, help="generation limit (default: 450 for plain/hybrid)")
    limits.add_argument("--max-evaluations", type=int,
                        help=f"fitness evaluation limit (default: {FLEXIBLE_EVALUATIONS} for flexible)")
    return parser


def main():
    parser = solver_parser(__doc__)
    args = parser.parse_args()
    try:
        winner, _ = solve(args.input, args.out, args.seed, args.generations,
                          variant=args.variant, max_evaluations=args.max_evaluations)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    print(f"Fitness = {fitness(winner.cost):.10f}")
    return 0 if winner.cost < HARD_WEIGHT else 2


if __name__ == "__main__":
    raise SystemExit(main())
