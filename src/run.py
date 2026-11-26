"""Run the solver, independent checks and exports with a single command."""
import subprocess
import sys

from src.schedule_ga import ROOT, HARD_WEIGHT, fitness, solve, solver_parser


def main():
    parser = solver_parser(__doc__)
    args = parser.parse_args()
    directory = args.out.resolve()
    try:
        best, history = solve(args.input, directory, args.seed, args.generations,
                              variant=args.variant, max_evaluations=args.max_evaluations)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    # Prevent a rerun with a short budget from exposing an earlier workbook.
    (directory / "Thoi_khoa_bieu_Python.xlsx").unlink(missing_ok=True)
    if best.cost < HARD_WEIGHT:
        subprocess.run([sys.executable, "-m", "tools.verify", directory], cwd=ROOT, check=True)
        subprocess.run([sys.executable, "-m", "tools.export_excel", directory], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "tools.plot_fitness", directory], cwd=ROOT, check=True)
    print(f"Generation {history[-1][0]}, fitness {fitness(best.cost):.10f}. Files: {directory}")
    return 0 if best.cost < HARD_WEIGHT else 2


if __name__ == "__main__":
    raise SystemExit(main())
