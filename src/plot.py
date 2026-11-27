"""Plots for one solver run or for a benchmark. Needs matplotlib.

    python -m src.plot run results            # fitness.png from fitness.csv
    python -m src.plot bench results/bench    # convergence, run-time and final-quality plots
"""
import argparse
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.schedule_ga import HARD_WEIGHT, LOWER_BOUND, fitness, read_csv  # noqa: E402
from src.stats import quantile  # noqa: E402

COLORS = {"plain": "#1f77b4", "hybrid": "#d62728", "flexible": "#2ca02c",
          "random": "#7f7f7f", "hillclimb": "#ff7f0e", "hillclimb-flex": "#9467bd"}


def plot_run(directory):
    rows = read_csv(directory / "fitness.csv")
    generation = [int(r["generation"]) for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(generation, [float(r["best_fitness"]) for r in rows], label="best fitness", color="#d62728")
    ax.plot(generation, [float(r["mean_fitness"]) for r in rows], label="population mean", color="#1f77b4")
    ax.set_xlabel("generation")
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_ylabel("fitness F = 1 / (1 + H + P/10 000)")
    ax.grid(alpha=0.3)
    missing = ax.twinx()
    missing.step(generation, [int(r["best_missing"]) for r in rows], where="post", color="#7f7f7f",
                 linestyle="--", label="best: sessions without a room (H)")
    missing.set_ylabel("H")
    missing.set_ylim(bottom=0)
    lines = ax.get_legend_handles_labels()
    extra = missing.get_legend_handles_labels()
    ax.legend(lines[0] + extra[0], lines[1] + extra[1], loc="lower right")
    ax.set_title("GA fitness by generation")
    fig.tight_layout()
    fig.savefig(directory / "fitness.png", dpi=150)
    plt.close(fig)
    return [directory / "fitness.png"]


def load_bench(directory):
    runs = read_csv(directory / "runs.csv")
    methods = list(dict.fromkeys(r["method"] for r in runs))
    traces = defaultdict(lambda: defaultdict(list))
    for row in read_csv(directory / "convergence.csv"):
        traces[row["method"]][int(row["evaluations"])].append(int(row["best_cost"]))
    return runs, methods, traces


def plot_convergence(directory, methods, traces):
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for method in methods:
        points = sorted(traces[method])
        values = [[fitness(c) for c in traces[method][e]] for e in points]
        median = [quantile(v, 0.5) for v in values]
        ax.plot(points, median, label=method, color=COLORS.get(method))
        ax.fill_between(points, [quantile(v, 0.25) for v in values], [quantile(v, 0.75) for v in values],
                        color=COLORS.get(method), alpha=0.15, linewidth=0)
    ax.axhline(fitness(LOWER_BOUND), color="black", linewidth=0.8, linestyle=":")
    ax.annotate("H = 0, P = 360 (optimum)", (1, fitness(LOWER_BOUND)), xycoords=("axes fraction", "data"),
                ha="right", va="bottom", fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("fitness evaluations")
    ax.set_ylabel("best fitness so far")
    ax.set_title("Convergence: median over seeds, band = interquartile range")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    fig.tight_layout()
    fig.savefig(directory / "convergence.png", dpi=150)
    plt.close(fig)
    return directory / "convergence.png"


def plot_runtime(directory, runs, methods):
    """Share of runs that have reached a target after a given number of evaluations."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    budget = max(int(r["budget"]) for r in runs)
    for ax, key, title in ((axes[0], "evals_to_feasible", "feasible (H = 0)"),
                           (axes[1], "evals_to_bound", "optimum (H = 0, P = 360)")):
        for method in methods:
            mine = [r for r in runs if r["method"] == method]
            hits = sorted(int(r[key]) for r in mine if r[key])
            xs = [1] + [x for x in hits for _ in (0, 1)] + [budget]
            ys = [0] + [y for i in range(len(hits)) for y in (i / len(mine), (i + 1) / len(mine))]
            ys.append(len(hits) / len(mine))
            ax.plot(xs, ys, label=method, color=COLORS.get(method))
        ax.set_xscale("log")
        ax.set_xlim(1, budget)
        ax.set_xlabel("fitness evaluations")
        ax.set_title(f"runs that reached {title}")
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel("share of runs")
    axes[0].legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(directory / "runtime.png", dpi=150)
    plt.close(fig)
    return directory / "runtime.png"


def plot_final(directory, runs, methods):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    data = [[int(r["cost"]) % HARD_WEIGHT for r in runs if r["method"] == m] for m in methods]
    ax.boxplot(data, showfliers=False)
    ax.set_xticks(range(1, len(methods) + 1), methods)
    for i, (method, values) in enumerate(zip(methods, data), 1):
        jitter = [i + 0.25 * ((k * 0.618) % 1 - 0.5) for k in range(len(values))]
        ax.scatter(jitter, values, s=10, alpha=0.6, color=COLORS.get(method), zorder=3)
        infeasible = sum(r["feasible"] == "False" for r in runs if r["method"] == method)
        if infeasible:
            ax.annotate(f"{infeasible} run(s) H > 0", (i, max(values)), textcoords="offset points",
                        xytext=(0, 6), ha="center", fontsize=8, color="#d62728")
    ax.axhline(LOWER_BOUND, color="black", linewidth=0.8, linestyle=":")
    low, high = ax.get_ylim()
    ax.set_ylim(low, high + 0.08 * (high - low))
    ax.set_ylabel("final soft penalty P (lower bound 360)")
    ax.set_title("Final soft penalty per run")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(directory / "final.png", dpi=150)
    plt.close(fig)
    return directory / "final.png"


def plot_bench(directory):
    runs, methods, traces = load_bench(directory)
    return [plot_convergence(directory, methods, traces), plot_runtime(directory, runs, methods),
            plot_final(directory, runs, methods)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=("run", "bench"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    files = (plot_run if args.kind == "run" else plot_bench)(args.directory)
    print("Wrote " + ", ".join(str(f) for f in files))


if __name__ == "__main__":
    main()
