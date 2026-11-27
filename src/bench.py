"""Benchmark the GA variants against non-GA baselines over many seeds.

Every method gets the same budget of fitness evaluations (local-search trials
count as evaluations) and the same seeds. The best schedule of every run is
decoded and checked with the independent checker in src/verify.py.

    python -m src.bench --seeds 30 --budget 300000 --out results/bench
"""
import argparse
import contextlib
import datetime
import hashlib
import io
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from src.assign import solve_assignment
from src.schedule_ga import (HARD_WEIGHT, INPUT_FILES, LOWER_BOUND, ROOT, SCHEDULE_FIELDS, VARIANTS,
                             Instance, Progress, decode, evaluate, evolve, fitness, new_gene, read_csv,
                             write_csv)
from src.stats import fisher_exact, mann_whitney, prob_better, quantile, wilson_interval
from src.verify import verify

METHODS = {
    "plain": "GA: selection, crossover and mutation",
    "hybrid": "GA + local search after each crossover (the default solver)",
    "flexible": "GA + local search with moves that relocate sessions",
    "random": "baseline: best of independent random schedules",
    "hillclimb": "baseline: one schedule improved by hybrid's local search, no population",
    "hillclimb-flex": "baseline: one schedule improved by flexible's local search, no population",
}
REFERENCE = "hybrid"
DEFAULT_BUDGET = 300_000

RUN_FIELDS = ("method", "seed", "budget", "evaluations", "generations", "wall_s", "feasible",
              "reached_bound", "H", "P", "gap", "cost", "fitness", "evals_to_feasible",
              "evals_to_bound", "violations", "consistent", "G", "W", "M", "C", "R", "U")


def checkpoints(budget):
    """About ten points per decade, so convergence curves look even on a log axis."""
    points = {round(10 ** (k / 10)) for k in range(int(10 * math.log10(budget)) + 1)}
    return sorted(p for p in points | {budget} if p <= budget)


class Tracker(Progress):
    """Progress that also samples the best cost at fixed evaluation counts."""

    def __init__(self, limit):
        super().__init__(limit)
        self.points = checkpoints(limit)
        self.trace = []
        self.to_bound = None

    def record(self, cost, genes):
        super().record(cost, genes)
        if self.to_bound is None and self.best.cost == LOWER_BOUND:
            self.to_bound = self.used
        while len(self.trace) < len(self.points) and self.used >= self.points[len(self.trace)]:
            self.trace.append((self.points[len(self.trace)], self.best.cost))

    def finish(self):
        # A run that stops at the lower bound cannot improve, so its curve stays flat.
        self.trace += [(point, self.best.cost) for point in self.points[len(self.trace):]]


def run_method(instance, method, seed, progress):
    """Run one method; returns the number of GA generations (None for baselines)."""
    if method in VARIANTS:
        _, history = evolve(instance, seed, None, variant=method, progress=progress)
        return history[-1][0]
    rng = random.Random(seed)
    n = len(instance.professors)
    if method == "random":
        while not progress.budget_stop():
            evaluate(instance, [new_gene(instance, p, rng) for p in range(n)], rng, progress=progress)
    else:
        genes = [new_gene(instance, p, rng) for p in range(n)]
        # evaluate() skips proposals equal to the current gene without counting
        # them, so keep calling it until the budget is really spent.
        while not progress.budget_stop():
            evaluate(instance, genes, rng, progress.limit - progress.used,
                     flexible=method == "hillclimb-flex", progress=progress)
    return None


_CACHE = {}


def load(input_dir):
    if input_dir not in _CACHE:
        path = Path(input_dir)
        _CACHE[input_dir] = (Instance(path), *(read_csv(path / name) for name in
                                                ("sections.csv", "rooms.csv", "professors.csv")))
    return _CACHE[input_dir]


def run_one(task):
    input_dir, method, seed, budget = task
    instance, sections, rooms, professors = load(input_dir)
    progress = Tracker(budget)
    start = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):  # evolve prints every improvement
        generations = run_method(instance, method, seed, progress)
    wall = time.perf_counter() - start
    progress.finish()
    best = progress.best
    rows = [dict(zip(SCHEDULE_FIELDS, map(str, row))) for row in decode(instance, best)]
    report = verify(rows, sections, rooms, professors)
    missing, soft = divmod(best.cost, HARD_WEIGHT)
    run = dict(method=method, seed=seed, budget=budget, evaluations=progress.used,
               generations="" if generations is None else generations, wall_s=round(wall, 3),
               feasible=missing == 0, reached_bound=progress.to_bound is not None, H=missing, P=soft,
               gap=soft - LOWER_BOUND, cost=best.cost, fitness=fitness(best.cost),
               evals_to_feasible=progress.first_feasible or "", evals_to_bound=progress.to_bound or "",
               violations=report.violations,
               consistent=(report.hard["room_unassigned"], report.penalty) == (missing, soft),
               **report.soft)
    return run, progress.trace


def censored(value):
    """Runs that never reached a target rank after every run that did."""
    return math.inf if value == "" else value


def describe(values):
    return [quantile(values, q) for q in (0.5, 0.25, 0.75)]


def summarise(runs, methods):
    rows = []
    for method in methods:
        mine = [r for r in runs if r["method"] == method]
        n, feasible = len(mine), sum(r["feasible"] for r in mine)
        bound = sum(r["reached_bound"] for r in mine)
        low, high = wilson_interval(feasible, n)
        bound_low, bound_high = wilson_interval(bound, n)
        row = dict(method=method, runs=n, feasible=feasible, feasible_rate=feasible / n,
                   feasible_low=low, feasible_high=high, reached_bound=bound, bound_rate=bound / n,
                   bound_low=bound_low, bound_high=bound_high,
                   H_mean=sum(r["H"] for r in mine) / n, H_max=max(r["H"] for r in mine),
                   P_best=min(r["P"] for r in mine), P_worst=max(r["P"] for r in mine))
        for name, values in (("P", [r["P"] for r in mine]),
                             ("evals_to_feasible", [censored(r["evals_to_feasible"]) for r in mine]),
                             ("evals_to_bound", [censored(r["evals_to_bound"]) for r in mine]),
                             ("wall_s", [r["wall_s"] for r in mine])):
            row.update(zip((f"{name}_median", f"{name}_q1", f"{name}_q3"), describe(values)))
        row["violations"] = sum(r["violations"] for r in mine)
        row["inconsistent"] = sum(not r["consistent"] for r in mine)
        rows.append(row)
    return rows


def compare(runs, methods, reference):
    """Each method against the reference: Fisher for rates, Mann–Whitney for the rest."""
    rows = []
    ref = [r for r in runs if r["method"] == reference]
    for method in methods:
        if method == reference:
            continue
        mine = [r for r in runs if r["method"] == method]
        for metric, key in (("feasible_rate", "feasible"), ("bound_rate", "reached_bound")):
            a, b = sum(r[key] for r in mine), sum(r[key] for r in ref)
            rows.append(dict(method=method, reference=reference, metric=metric, test="fisher",
                             value=a / len(mine), reference_value=b / len(ref), statistic="",
                             p_value=fisher_exact(a, len(mine), b, len(ref)), prob_better=""))
        for metric, get in (("cost", lambda r: r["cost"]),
                            ("evals_to_feasible", lambda r: censored(r["evals_to_feasible"])),
                            ("evals_to_bound", lambda r: censored(r["evals_to_bound"])),
                            ("wall_s", lambda r: r["wall_s"])):
            x, y = [get(r) for r in mine], [get(r) for r in ref]
            u, p = mann_whitney(x, y)
            rows.append(dict(method=method, reference=reference, metric=metric, test="mann-whitney",
                             value=quantile(x, 0.5), reference_value=quantile(y, 0.5), statistic=u,
                             p_value=p, prob_better=prob_better(x, y)))
    return rows


def git_commit():
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    return (done.stdout.strip() + ("-dirty" if dirty.strip() else "")) if done.returncode == 0 else None


def write_manifest(out, **fields):
    path = out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    manifest.update(fields)
    path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")


def text_value(value):
    if isinstance(value, float):
        return "inf" if math.isinf(value) else f"{value:.6g}"
    return value


def write_rows(path, rows):
    write_csv(path, list(rows[0]), ([text_value(v) for v in row.values()] for row in rows))


def show(value, digits=0):
    if value == math.inf:
        return "never"
    return f"{value:,.{digits}f}"


def print_summary(summary):
    print(f"\n{'method':>15} {'feasible':>10} {'P = 360':>9} {'median P':>9} "
          f"{'evals to feasible':>18} {'evals to 360':>13} {'median s':>9}")
    for r in summary:
        print(f"{r['method']:>15} {r['feasible']:>4}/{r['runs']:<5} {r['reached_bound']:>4}/{r['runs']:<4} "
              f"{show(r['P_median'], 1):>9} {show(r['evals_to_feasible_median']):>18} "
              f"{show(r['evals_to_bound_median']):>13} {show(r['wall_s_median'], 1):>9}")


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=ROOT / "input",
                   help="input folder; sections without a professor column are assigned first")
    p.add_argument("--out", type=Path, default=ROOT / "results" / "bench")
    p.add_argument("--methods", nargs="+", choices=list(METHODS), default=list(METHODS))
    p.add_argument("--seeds", type=int, default=30, help="runs per method, seeds 1..N")
    p.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="fitness evaluations per run")
    p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                   help="runs at the same time, one process each")
    p.add_argument("--force", action="store_true", help="overwrite an existing results folder")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.seeds < 2 or args.budget < 28 or args.jobs < 1:
        p.error("use at least 2 seeds, a budget of at least 28 evaluations and 1 job")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()) and not args.force:
        p.error(f"{out} already has results; pass --force or choose another --out")
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").unlink(missing_ok=True)

    data = out / "input"
    try:
        if "professor" in read_csv(args.input / "sections.csv")[0]:
            data.mkdir(exist_ok=True)
            for name in INPUT_FILES:
                (data / name).write_bytes((args.input / name).read_bytes())
        else:
            solve_assignment(args.input, data)
        Instance(data)
    except (ValueError, KeyError, OSError) as error:
        p.error(str(error))

    methods = [m for m in METHODS if m in args.methods]
    write_manifest(out, args={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                   methods={m: METHODS[m] for m in methods}, reference=REFERENCE,
                   lower_bound=LOWER_BOUND, hard_weight=HARD_WEIGHT, git_commit=git_commit(),
                   python=platform.python_version(), platform=platform.platform(),
                   cpu_count=os.cpu_count(),
                   input_sha256={n: hashlib.sha256((data / n).read_bytes()).hexdigest() for n in INPUT_FILES},
                   started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   complete=False)

    # Interleave methods so a slow method does not finish last on its own.
    tasks = [(str(data), method, seed, args.budget)
             for seed in range(1, args.seeds + 1) for method in methods]
    runs, traces = [], []
    with ProcessPoolExecutor(args.jobs) as pool:
        for done, (run, trace) in enumerate(pool.map(run_one, tasks), 1):
            runs.append(run)
            traces += [dict(method=run["method"], seed=run["seed"], evaluations=e, best_cost=c)
                       for e, c in trace]
            flag = "" if run["violations"] == 0 and run["consistent"] else "  CHECK FAILED"
            print(f"[{done:3}/{len(tasks)}] {run['method']:>14} seed {run['seed']:2}: H={run['H']} "
                  f"P={run['P']} evals={run['evaluations']} {run['wall_s']:.1f}s{flag}", flush=True)

    runs.sort(key=lambda r: (methods.index(r["method"]), r["seed"]))
    write_rows(out / "runs.csv", runs)
    write_rows(out / "convergence.csv", traces)
    summary = summarise(runs, methods)
    write_rows(out / "summary.csv", summary)
    if REFERENCE in methods and len(methods) > 1:
        write_rows(out / "tests.csv", compare(runs, methods, REFERENCE))
    write_manifest(out, complete=True,
                   finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
    print_summary(summary)
    print(f"\nFiles: {out}")
    bad = sum(r["violations"] or not r["consistent"] for r in runs)
    if bad:
        print(f"FAIL: {bad} runs broke a hard constraint or disagree with the checker", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
