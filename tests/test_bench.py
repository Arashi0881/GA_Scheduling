import json
import math

import pytest

from src.bench import METHODS, main
from src.schedule_ga import ROOT, read_csv

BUDGET = 600


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    out = tmp_path_factory.mktemp("bench") / "run"
    code = main(["--input", str(ROOT / "input"), "--out", str(out), "--seeds", "2",
                 "--budget", str(BUDGET), "--jobs", "2"])
    assert code == 0
    return out


def test_every_method_and_seed_runs_within_budget(bench):
    runs = read_csv(bench / "runs.csv")
    assert sorted((r["method"], r["seed"]) for r in runs) == sorted(
        (m, str(s)) for m in METHODS for s in (1, 2))
    for run in runs:
        assert int(run["evaluations"]) <= BUDGET
        assert run["violations"] == "0" and run["consistent"] == "True"
        assert int(run["H"]) * 10_000 + int(run["P"]) == int(run["cost"])


def test_convergence_is_monotone_and_ends_at_final_cost(bench):
    runs = {(r["method"], r["seed"]): int(r["cost"]) for r in read_csv(bench / "runs.csv")}
    trace = {}
    for row in read_csv(bench / "convergence.csv"):
        trace.setdefault((row["method"], row["seed"]), []).append(
            (int(row["evaluations"]), int(row["best_cost"])))
    assert trace.keys() == runs.keys()
    for key, points in trace.items():
        assert [e for e, _ in points] == sorted({e for e, _ in points})
        assert points[-1][0] == BUDGET
        costs = [c for _, c in points]
        assert costs == sorted(costs, reverse=True)
        assert costs[-1] == runs[key]


def test_summary_tests_and_manifest(bench):
    summary = {r["method"]: r for r in read_csv(bench / "summary.csv")}
    assert set(summary) == set(METHODS)
    for row in summary.values():
        assert row["runs"] == "2"
        assert 0 <= float(row["feasible_low"]) <= float(row["feasible_rate"]) <= float(row["feasible_high"]) <= 1
    tests = read_csv(bench / "tests.csv")
    assert {r["method"] for r in tests} == set(METHODS) - {"hybrid"}
    assert all(0 <= float(r["p_value"]) <= 1 for r in tests)
    manifest = json.loads((bench / "manifest.json").read_text())
    assert manifest["args"]["budget"] == BUDGET and manifest["complete"] is True
    assert set(manifest["input_sha256"]) == {"sections.csv", "rooms.csv", "professors.csv"}


def test_refuses_to_overwrite_results(bench):
    with pytest.raises(SystemExit):
        main(["--out", str(bench), "--seeds", "1", "--budget", str(BUDGET)])


def test_fisher_exact():
    from src.stats import fisher_exact
    # Lady tasting tea: 3/4 vs 1/4, two-sided p = 34/70.
    assert fisher_exact(3, 4, 1, 4) == pytest.approx(34 / 70)
    assert fisher_exact(5, 5, 5, 5) == 1.0
    assert not math.isnan(fisher_exact(0, 30, 30, 30))
