import argparse

from kaizen import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kaizen")
    parser.add_argument("--version", action="store_true")
    parser.add_subparsers(dest="command")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"kaizen {__version__}")
        return 0
    parser.print_help()
    return 2
