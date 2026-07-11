"""``python -m wordle_solver.generators`` -> run the full artifact build."""

from .build_all import main

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="python -m wordle_solver.generators")
    ap.add_argument("--quick", action="store_true",
                    help="only rebuild word data + matrix; skip committed heavy artifacts")
    args = ap.parse_args()
    main(quick=args.quick)
