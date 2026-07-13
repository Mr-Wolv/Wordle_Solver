"""Convenience dispatcher: ``python -m wordle_solver.tools [benchmark|profiler|tester]``.

Defaults to ``benchmark`` when no subcommand is given.
"""

import argparse
import sys

from . import benchmark, profiler, tester

_DISPATCH = {
    "benchmark": benchmark.main,
    "profiler": profiler.main,
    "tester": tester.main,
}


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m wordle_solver.tools",
        description="Run a solver dev tool (benchmark / profiler / tester).",
    )
    ap.add_argument(
        "tool",
        nargs="?",
        default="benchmark",
        choices=sorted(_DISPATCH),
        help="which tool to run (default: benchmark)",
    )
    args, rest = ap.parse_known_args()
    # Forward remaining argv to the chosen tool's argparse.
    sys.argv = [f"wordle_solver.tools.{args.tool}", *rest]
    _DISPATCH[args.tool]()


if __name__ == "__main__":
    main()
